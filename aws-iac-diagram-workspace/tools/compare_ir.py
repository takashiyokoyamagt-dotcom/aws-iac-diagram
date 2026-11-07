# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""正解 IR（G）と正規化の出力（O）を比べ、CRITERIA.md の指標を出す（フェーズ 3。設計草案の 7.1）。

比べ方は CRITERIA.md の 1.0 と docs/spec/ir-schema/ の 5 のとおり:

- 比べる前に、網羅分類が `drawn` のリソースの address で O のノードの id を G の id に置き換える（1 つのノードに address が
  複数あれば、どれか 1 つが一致すればよい。O の複数のノードが同じ G のノードに当たるときは、O の id 順で最初の 1 つだけ）。
  address で対応づかないノード（合成ノードなど）は id のまま比べる。
- N = `(id, type)`、E = `(from, to, kind)`（向きを区別）、P = `(id, parent)` と `(id, span)`、C = 形式ごとの
  `(address, class, node／into, rule)`、付随 = 一致した辺の `confidence`・`label` と、一致したノードの `label`、
  名前の一致率、`unknown` の件数、E の向きを無視した一致率（参考）。
- 複数の入力はマイクロ平均（件数を合算してから割る）。入力ごとの下限は、母数が 10 以上なら割合、10 未満なら誤り 1 件以内。
- 重大な誤り X1〜X3（CRITERIA の 1.5）。X4 は `check_coverage.py` の仕事（ツールが自分の出力を検算しないため）。

基準値は THRESHOLDS の 1 か所に置き、CRITERIA.md の表と同じであることを単体テスト（tests/unit/validate/test_compare_ir.py）が確かめる。

使い方（リポジトリのルートで。--pair は 正解 IR・出力・形式（tf／cfn）の 3 つで、繰り返せる）:
  uv run python aws-iac-diagram-workspace/tools/compare_ir.py --set custom \\
      --pair aws-iac-diagram-workspace/expected/three-tier.ir.json out/three-tier.tf.json tf [--json]

終了コード: 0 = 基準を満たす、1 = 満たさない（重大な誤りを含む）、2 = 読めない・使い方の誤り
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

INTERNET = "external/internet"
SMALL = 10  # 母数がこれ未満の入力は、割合ではなく「誤り 1 件以内」で見る（CRITERIA の 1.0）

# CRITERIA.md の基準値。キーは指標の名前、値は (全体の下限, 入力ごとの下限 または None)
THRESHOLDS: dict[str, dict[str, tuple[float, float | None]]] = {
    "custom": {  # 1.1 自作の fixture
        "N.recall": (1.0, 1.0), "N.precision": (1.0, 1.0), "E.recall": (1.0, 1.0), "E.precision.confirmed_derived": (1.0, 1.0),
        "E.precision.inferred": (1.0, 1.0), "P.recall": (1.0, 1.0), "P.precision": (1.0, 1.0), "name": (1.0, 1.0),
        "C": (1.0, 1.0), "edge.confidence": (1.0, 1.0), "edge.label": (1.0, 1.0), "node.label": (1.0, 1.0),
    },
    "main": {  # 1.2 公開サンプルの主セット
        "N.recall": (0.95, 0.90), "N.precision": (0.95, 0.90), "name": (0.90, None), "E.recall": (0.90, 0.80),
        "E.precision.confirmed_derived": (0.95, 0.90), "E.precision.inferred": (0.80, None),
        "P.recall": (0.95, 0.90), "P.precision": (0.95, 0.90), "C": (0.95, 0.90), "edge.confidence": (0.90, None),
    },
}
CONFIRMED_DERIVED = ("confirmed", "derived")


class UsageError(Exception):
    pass


# ------------------------------------------------------------------ id の対応づけ

def drawn_addresses(ir: dict, fmt: str) -> dict[str, list[str]]:
    """ノードの id → そのノードに `drawn` で分類された address の一覧（形式 fmt の由来部から）。"""
    out: dict[str, list[str]] = {}
    for r in ir.get("sources", {}).get(fmt, {}).get("resources", []):
        if r.get("class") == "drawn" and r.get("node"):
            out.setdefault(r["node"], []).append(r["address"])
    return out


def id_map(g: dict, o: dict, fmt: str) -> tuple[dict[str, str], list[tuple[str, str]]]:
    """O の id → G の id の置き換え表と、address で対応づいた組 (O のもとの id, G の id) の一覧。"""
    g_by_addr = {a: gid for gid, addrs in drawn_addresses(g, fmt).items() for a in addrs}
    o_addrs = drawn_addresses(o, fmt)
    mapping: dict[str, str] = {}
    pairs: list[tuple[str, str]] = []
    taken: set[str] = set()
    for oid in sorted(n["id"] for n in o.get("nodes", [])):
        hits = sorted({g_by_addr[a] for a in o_addrs.get(oid, ()) if a in g_by_addr})
        gid = hits[0] if hits else None  # 最初の対応先だけを見る。使用済みなら id のまま（ir-schema の 5）
        if gid is None or gid in taken:
            continue
        taken.add(gid)
        mapping[oid] = gid
        pairs.append((oid, gid))
    return mapping, pairs


def remap_ref(ref: str, m: dict[str, str]) -> str:
    """ノードの id か辺の id（`<from>-><to>`）を置き換える。"""
    if "->" in ref:
        a, b = ref.split("->", 1)
        return f"{m.get(a, a)}->{m.get(b, b)}"
    return m.get(ref, ref)


# ------------------------------------------------------------------ 集合

def node_list(ir: dict, m: dict[str, str]) -> list[tuple]:
    return [(m.get(n["id"], n["id"]), n.get("type")) for n in ir.get("nodes", [])]


def edge_key(e: dict, m: dict[str, str]) -> tuple:
    return (m.get(e["from"], e["from"]), m.get(e["to"], e["to"]), e.get("kind"))


def edge_list(ir: dict, m: dict[str, str], confidences: tuple[str, ...] | None = None) -> list[tuple]:
    return [edge_key(e, m) for e in ir.get("edges", []) if confidences is None or e.get("confidence") in confidences]


def placement_list(ir: dict, m: dict[str, str]) -> list[tuple]:
    """`(id, "parent", 親)` と `(id, "span", サブネット)`。親の無いノードも `(id, "parent", None)` として数える
    （最上位に置くことも入れ子の判断で、正解が最上位のノードを VPC の中に入れた出力を、再現率でも数えるため）。"""
    out = []
    for n in ir.get("nodes", []):
        i = m.get(n["id"], n["id"])
        p = n.get("parent")
        out.append((i, "parent", m.get(p, p) if p else None))
        out += [(i, "span", m.get(s, s)) for s in n.get("spans") or ()]
    return out


def hits(g: list[tuple], o: list[tuple]) -> tuple[int, int, int]:
    """(一致した数, |G|, |O|)。O は重なりも数える（1 つのリソースを 2 つのノードに分けた出力の余りを、適合率で数えるため）。"""
    return len(set(g) & set(o)), len(set(g)), len(o)


def class_map(ir: dict, fmt: str, m: dict[str, str]) -> dict[str, tuple]:
    """address → (class, 先, 規則)。先は drawn ならノード、merged_into なら into（置き換えて並べた tuple）、hidden は無し。
    規則は merged_into・hidden の `rule`（取り違えも C の誤りとして数える）。"""
    out = {}
    for r in ir.get("sources", {}).get(fmt, {}).get("resources", []):
        c = r.get("class")
        if c == "drawn":
            target = remap_ref(r.get("node", ""), m)
        elif c == "merged_into":
            into = r.get("into") or ()
            target = tuple(sorted(remap_ref(x, m) for x in ([into] if isinstance(into, str) else into)))
        else:
            target = None
        out.setdefault(r["address"], (c, target, None if c == "drawn" else r.get("rule")))  # 重なりは最初のもの
    return out


# ------------------------------------------------------------------ 1 入力

def first_by(items: list[dict], key) -> dict:
    """キー → 最初の要素（置き換えの後で重なっても、配列の順で後のものが勝たない）。"""
    out: dict = {}
    for x in items:
        out.setdefault(key(x), x)
    return out


def ratio(hit: int, total: int) -> float | None:
    return None if total == 0 else hit / total


def compare(g: dict, o: dict, fmt: str) -> dict:
    """1 つの入力の件数（ヒット数・母数）と重大な誤り。割合は aggregate で出す。"""
    if fmt not in ("tf", "cfn"):
        raise UsageError(f"形式は tf か cfn: {fmt!r}")
    m, pairs = id_map(g, o, fmt)
    ident: dict[str, str] = {}
    counts: dict[str, tuple[int, int]] = {}

    gn, on = node_list(g, ident), node_list(o, m)
    hit, den_g, den_o = hits(gn, on)
    counts["N.recall"], counts["N.precision"] = (hit, den_g), (hit, den_o)
    counts["name"] = (sum(1 for oid, gid in pairs if oid == gid), len(pairs))

    ge, o_all = edge_list(g, ident), edge_list(o, m)
    counts["E.recall"] = hits(ge, o_all)[:2]
    for name, confs in (("confirmed_derived", CONFIRMED_DERIVED), ("inferred", ("inferred",))):
        hit, _, den_o = hits(ge, edge_list(o, m, confs))
        counts[f"E.precision.{name}"] = (hit, den_o)
    g_pairs = {frozenset((f, t)) for f, t, _ in ge}
    counts["E.undirected"] = (len(g_pairs & {frozenset((f, t)) for f, t, _ in o_all}), len(g_pairs))  # 参考

    hit, den_g, den_o = hits(placement_list(g, ident), placement_list(o, m))
    counts["P.recall"], counts["P.precision"] = (hit, den_g), (hit, den_o)

    gc, oc = class_map(g, fmt, ident), class_map(o, fmt, m)
    counts["C"] = (sum(1 for a, v in gc.items() if oc.get(a) == v), len(gc))

    # 付随: 一致した辺・ノードの中で
    g_edges = first_by(g.get("edges", []), lambda e: edge_key(e, ident))
    o_edges = first_by(o.get("edges", []), lambda e: edge_key(e, m))
    both = sorted(set(g_edges) & set(o_edges), key=str)
    counts["edge.confidence"] = (sum(1 for k in both if g_edges[k].get("confidence") == o_edges[k].get("confidence")), len(both))
    counts["edge.label"] = (sum(1 for k in both if g_edges[k].get("label") == o_edges[k].get("label")), len(both))
    g_nodes = first_by(g.get("nodes", []), lambda n: (n["id"], n.get("type")))
    o_nodes = first_by(o.get("nodes", []), lambda n: (m.get(n["id"], n["id"]), n.get("type")))
    nboth = sorted(set(g_nodes) & set(o_nodes), key=str)
    counts["node.label"] = (sum(1 for k in nboth if g_nodes[k].get("label") == o_nodes[k].get("label")), len(nboth))

    unknown = sum(1 for r in o.get("sources", {}).get(fmt, {}).get("resources", []) if r.get("class") == "unknown")
    return {"counts": counts, "unknown": unknown, "critical": critical(g, o, m, ident),
            "missing": {"N": sorted(set(gn) - set(on), key=str), "E": sorted(set(ge) - set(o_all), key=str)},
            "extra": {"N": sorted(set(on) - set(gn), key=str), "E": sorted(set(o_all) - set(ge), key=str)}}


def critical(g: dict, o: dict, m: dict[str, str], ident: dict[str, str]) -> dict[str, list]:
    """重大な誤り X1〜X3（CRITERIA の 1.5）。"""
    g_types = {n["id"]: n.get("type") for n in g.get("nodes", [])}
    o_types = {m.get(n["id"], n["id"]): n.get("type") for n in o.get("nodes", [])}

    def pairs(ir, mm, pred=lambda f, t: True):
        return {(mm.get(e["from"], e["from"]), mm.get(e["to"], e["to"])) for e in ir.get("edges", [])
                if pred(mm.get(e["from"], e["from"]), mm.get(e["to"], e["to"]))}

    x1 = []
    touch = lambda f, t: INTERNET in (f, t)  # noqa: E731
    gi, oi = pairs(g, ident, touch), pairs(o, m, touch)
    x1 += [f"internet の辺: 正解だけ {p}" for p in sorted(gi - oi)] + [f"internet の辺: 出力だけ {p}" for p in sorted(oi - gi)]
    g_access = {n["id"]: (n.get("attrs") or {}).get("access") for n in g.get("nodes", []) if n.get("type") == "subnet"}
    o_access = {m.get(n["id"], n["id"]): (n.get("attrs") or {}).get("access") for n in o.get("nodes", []) if n.get("type") == "subnet"}
    x1 += [f"サブネットの access: {i} は正解 {g_access[i]!r}、出力 {o_access[i]!r}"
           for i in sorted(set(g_access) & set(o_access)) if g_access[i] != o_access[i]]
    gr = pairs(g, ident, lambda f, t: g_types.get(f) == "subnet" and g_types.get(t) == "internet_gateway")
    orr = pairs(o, m, lambda f, t: o_types.get(f) == "subnet" and o_types.get(t) == "internet_gateway")
    x1 += [f"サブネット → IGW: 正解だけ {p}" for p in sorted(gr - orr)] + [f"サブネット → IGW: 出力だけ {p}" for p in sorted(orr - gr)]

    g_dir = pairs(g, ident)
    g_any = {frozenset(p) for p in g_dir}
    strong = {(m.get(e["from"], e["from"]), m.get(e["to"], e["to"])) for e in o.get("edges", [])
              if e.get("confidence") in CONFIRMED_DERIVED}
    x3 = sorted(p for p in strong if (p[1], p[0]) in g_dir and p not in g_dir)
    x2 = sorted(p for p in strong if frozenset(p) not in g_any and p not in x3)
    return {"X1": x1, "X2": [list(p) for p in x2], "X3": [list(p) for p in x3]}


# ------------------------------------------------------------------ まとめと判定

def aggregate(results: dict[str, dict], set_name: str) -> dict:
    if set_name not in THRESHOLDS:
        raise UsageError(f"--set は {sorted(THRESHOLDS)} のどれか: {set_name!r}")
    th = THRESHOLDS[set_name]
    names = sorted({k for r in results.values() for k in r["counts"]})
    total = {k: (sum(r["counts"][k][0] for r in results.values()), sum(r["counts"][k][1] for r in results.values())) for k in names}
    failures = []
    for k, (overall, per_input) in th.items():
        v = ratio(*total.get(k, (0, 0)))
        if v is not None and v < overall:
            failures.append(f"{k}: 全体 {v:.3f} < {overall}")
        if per_input is None:
            continue
        for name, r in results.items():
            hit, den = r["counts"].get(k, (0, 0))
            if den == 0:
                continue
            if den >= SMALL and hit / den < per_input:
                failures.append(f"{name}: {k} {hit}/{den} = {hit / den:.3f} < {per_input}")
            elif den < SMALL and per_input < 1.0 and den - hit > 1:
                failures.append(f"{name}: {k} の誤り {den - hit} 件（母数 {den} は {SMALL} 未満なので 1 件以内）")
            elif den < SMALL and per_input == 1.0 and hit < den:
                failures.append(f"{name}: {k} {hit}/{den}（基準は 1.0）")
    for name, r in results.items():
        failures += [f"{name}: {x} {v}" for x, vs in r["critical"].items() for v in vs]
        if r["unknown"]:
            failures.append(f"{name}: unknown {r['unknown']} 件")
    return {"set": set_name, "ratios": {k: ratio(*v) for k, v in total.items()}, "counts": total, "failures": failures}


def report(results: dict[str, dict], summary: dict) -> str:
    lines = [f"| 指標 | 全体 | 件数 |", "|---|---|---|"]
    for k, v in summary["ratios"].items():
        hit, den = summary["counts"][k]
        lines.append(f"| {k} | {'—' if v is None else f'{v:.3f}'} | {hit}/{den} |")
    lines.append("")
    lines += [f"NG {f}" for f in summary["failures"]] or ["OK 基準を満たす"]
    return "\n".join(lines)


def load(path: str) -> dict:
    try:
        ir = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise UsageError(f"{path}: 読めない（{e}）") from e
    if not isinstance(ir, dict) or not isinstance(ir.get("nodes"), list):
        raise UsageError(f"{path}: IR の形でない（最上位が nodes を持つオブジェクトでない）")
    return ir


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # Windows でリダイレクトしても cp932 で落ちない（ほかの道具と同じ）
        if hasattr(stream, "reconfigure"):  # テストで差し替えた StringIO には無い
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pair", nargs=3, action="append", required=True, metavar=("EXPECTED", "OUTPUT", "FORMAT"))
    ap.add_argument("--set", default="custom", help="基準の組（custom = CRITERIA の 1.1、main = 1.2）")
    ap.add_argument("--json", action="store_true", help="結果を JSON で出す")
    args = ap.parse_args(argv)
    try:
        results = {}
        for i, (g, o, fmt) in enumerate(args.pair, 1):
            g_ir, o_ir = load(g), load(o)
            try:
                results[f"{i}:{Path(g).name}:{fmt}"] = compare(g_ir, o_ir, fmt)  # 通し番号で、同じ名前の出力が重ならない
            except (KeyError, TypeError, AttributeError) as e:
                raise UsageError(f"{g} と {o}: IR の形でない（{type(e).__name__}: {e}）") from e
        summary = aggregate(results, args.set)
    except UsageError as e:
        print(f"compare_ir: {e}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps({"inputs": results, "summary": summary}, ensure_ascii=False, indent=1, default=list))
    else:
        print(report(results, summary))
    return 1 if summary["failures"] else 0


if __name__ == "__main__":
    sys.exit(main())
