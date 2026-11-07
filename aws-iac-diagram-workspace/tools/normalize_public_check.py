# /// script
# requires-python = ">=3.12"
# dependencies = ["python-hcl2==8.1.4", "PyYAML==6.0.3", "jsonschema==4.26.0"]
# ///
"""正規化（raw IR → normalized IR）の公開サンプルでの確認（フェーズ 3 の手順 6 の後半。設計草案の 6 章の 6 行目と 7.5）。
tests/integration/normalize/test_public_samples.py も同じ関数を使う。

1. 全公開サンプルの一巡（CRITERIA の 6 章（m）と 1.8（l））: survey_public.py の SAMPLES のすべてのルート（T20 は 26 ルート、
   T18・P01・C04 は複数のルート。ルートごとに 1 入力）をアダプタで読み、正規化し、次を数える。
   - 例外で止まらない（`exception`）
   - `build.check` の網羅分類の漏れ・重複と仮のままの分類（`check`）
   - check_coverage.check_ir の独立な照合（X4。正規化のコードを使わず入力を数え直す。`x4`）
   - validate_ir の検査（スキーマと意味の整合。`validate`）
   - `unknown` の件数と型、`NORM-UNUSED-REF` の件数と属性名の内訳（1.8 の 4 番目）、そのほかの `NORM-` の診断の件数
   - ノード・辺の数（辺は kind・確信度ごと、R-SG の辺の数。設計草案の 8 章の 6）と、読み込みと正規化の時間
   `--only ID ...` で入力を絞る（ID は INPUTS のキー。`T20` のように前に一致するものすべて）。
2. TF／SAM の対（CRITERIA の 1.4（n）。SELECTION.md の 3 の 3）: 対の正規化の出力どうしで、ノードの型の多重集合と、
   辺の (from の型, to の型, kind) の多重集合を比べる。違いは PAIR_ALLOWED（対ごとの「許す違いの一覧」。理由つき）と突き合わせる。
   道具の限界で出る違いは KNOWN_LIMITATIONS に分けて書き、1.4 の判定では除かない（その対は「NG（既知の制約・ユーザーの確認待ち）」）。

使い方:
  uv run python aws-iac-diagram-workspace/tools/normalize_public_check.py [--only ID ...] [--jobs N] [--pairs] [--out <report.json>]

終了コード: 0 = すべて通った、1 = 失敗がある（例外・網羅分類・X4・検査の誤り・対の基準を満たさない（既知の制約による
もの（NG（既知の制約・ユーザーの確認待ち））を含む）・許す違いの一覧と合わない）
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
WS = TOOLS.parent
PUB = WS / "fixtures" / "public"
SCRIPTS = WS.parent / "skills" / "aws-iac-diagram" / "scripts"
for p in (str(SCRIPTS), str(TOOLS)):
    if p not in sys.path:
        sys.path.insert(0, p)

import check_coverage  # noqa: E402
import survey_public  # noqa: E402
import validate_ir  # noqa: E402
from aws_iac_diagram.adapters.cloudformation import build as cfn_build  # noqa: E402
from aws_iac_diagram.adapters.terraform import build as tf_build  # noqa: E402
from aws_iac_diagram.core import rules as rules_mod  # noqa: E402
from aws_iac_diagram.normalize import build  # noqa: E402

T20_BASE = "sample-multi-source-cdc-iceberg-lakehouse/iac/roots/"


# --------------------------------------------------------------------------------------------------------------
# 1. 全公開サンプルの一巡
# --------------------------------------------------------------------------------------------------------------

def inputs() -> dict[str, tuple[str, str]]:
    """入力の ID → (形式, fixtures/public からの相対パス)。ルートが 1 つのサンプルは ID のまま、複数なら `<ID>:<ルートの短い名前>`。"""
    out: dict[str, tuple[str, str]] = {}
    for sid, (fmt, roots) in survey_public.SAMPLES.items():
        if sid == "T20":
            roots = survey_public.t20_roots()
        if len(roots) == 1:
            out[sid] = (fmt, roots[0])
            continue
        for r in roots:
            if sid == "T20":
                short = r.removeprefix(T20_BASE)
            elif fmt == "cfn":
                short = Path(r).name.split(".")[0]
            else:
                short = Path(r).name
            out[f"{sid}:{short}"] = (fmt, r)
    return out


INPUTS = inputs()


def select(only: list[str] | None) -> list[str]:
    """`--only` の ID（完全一致か、`<ID>:` で始まるもの）。省略すると全部。"""
    if not only:
        return list(INPUTS)
    out = [i for i in INPUTS if any(i == o or i.startswith(o + ":") for o in only)]
    unknown = [o for o in only if not any(i == o or i.startswith(o + ":") for i in INPUTS)]
    if unknown:
        raise KeyError(f"INPUTS に無い ID: {unknown}")
    return out


def raw_of(iid: str) -> dict:
    fmt, rel = INPUTS[iid]
    return (tf_build.build_raw if fmt == "tf" else cfn_build.build_raw)(PUB / rel, WS)


def ir_name(iid: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", iid.lower()).strip("-")


_ATTR = re.compile(r"^[^.\[]+")


def ref_attr(path: str) -> str:
    """`NORM-UNUSED-REF` の内訳に使う属性名: raw の path の最初の要素（`environment[0].variables.X` → `environment`）。"""
    m = _ATTR.match(path)
    return m.group(0) if m else path


def validate(ir: dict) -> list[str]:
    """validate_ir.py <ファイル> と同じスキーマと意味の検査（出力の形は canonical_dump で書くので見ない）。"""
    errs = validate_ir.schema_errors(ir)
    if errs:
        return errs
    return validate_ir.semantic_errors(ir, validate_ir.defined_rules(), validate_ir.drawable_types())


def check_input(iid: str) -> dict:
    """1 入力を読み、正規化し、要約を返す（ProcessPoolExecutor から呼べるように top-level に置く）。"""
    fmt, rel = INPUTS[iid]
    out: dict = {"id": iid, "format": fmt, "root": rel, "problems": []}
    t0 = time.perf_counter()
    try:
        raw = raw_of(iid)
    except Exception as e:  # noqa: BLE001
        out["problems"].append(f"adapter exception {type(e).__name__}: {e}")
        return out
    t1 = time.perf_counter()
    try:
        ir = build.normalize(raw, name=ir_name(iid))
    except Exception as e:  # noqa: BLE001
        out["problems"].append(f"normalize exception {type(e).__name__}: {e}")
        return out
    t2 = time.perf_counter()
    out["seconds"] = {"raw": round(t1 - t0, 2), "normalize": round(t2 - t1, 2)}
    out.update(summarize(raw, ir))
    problems, provisional = build.check(raw, ir)
    out["problems"] += [f"check: {p}" for p in problems] + [f"provisional: {p}" for p in provisional]
    out["problems"] += [f"X4 [{f}]: {e}" for f, _, es, _ in check_coverage.check_ir(ir) for e in es]
    out["problems"] += [f"validate: {e}" for e in validate(ir)]
    return out


def summarize(raw: dict, ir: dict) -> dict:
    """件数の要約（時間を含まない。毎回同じ値）。"""
    res = ir["sources"][raw["format"]]["resources"]
    types = {n["id"]: n["type"] for n in ir["nodes"]}
    codes = Counter(d["code"] for d in ir["diagnostics"])
    unused = [d for d in ir["diagnostics"] if d["code"] == "NORM-UNUSED-REF"]
    rules_of = {x["edge"]: x["rules"] for x in ir["sources"][raw["format"]]["edges"]}
    return {
        "resources": len(res),
        "classes": dict(sorted(Counter(r["class"] for r in res).items())),
        "nodes": len(ir["nodes"]),
        "edges": len(ir["edges"]),
        "edges_by_kind": dict(sorted(Counter(e["kind"] for e in ir["edges"]).items())),
        "edges_by_confidence": dict(sorted(Counter(e["confidence"] for e in ir["edges"]).items())),
        "edges_r_sg": sum(1 for e in ir["edges"] if "R-SG" in rules_of.get(e["id"], ())),
        "edges_internet": sum(1 for e in ir["edges"] if types.get(e["from"]) == "external"),
        "references_active": sum(1 for r in raw["references"] if r["state"] == "active"),
        "unknown": dict(sorted(Counter(r["type"] for r in res if r["class"] == "unknown").items())),
        "unused_refs": len(unused),
        "unused_ref_attrs": dict(sorted(Counter(ref_attr(d["path"]) for d in unused).items())),
        "norm_diagnostics": dict(sorted((k, v) for k, v in codes.items() if k != "NORM-UNUSED-REF")),
        "raw_diagnostics": dict(sorted(Counter(d["level"] for d in raw["diagnostics"]).items())),
    }


def run_inputs(ids: list[str], jobs: int = 1) -> list[dict]:
    if jobs > 1:
        with ProcessPoolExecutor(max_workers=jobs) as ex:
            return list(ex.map(check_input, ids))
    return [check_input(i) for i in ids]


# --------------------------------------------------------------------------------------------------------------
# 2. TF／SAM の対（CRITERIA の 1.4）
# --------------------------------------------------------------------------------------------------------------

# CRITERIA の 1.4 の対は T06・T07・T11。T01・T05 は補助セット（6 章）の対で、1.4 の基準の対象ではないが、同じ比べ方で参考に出す
PAIRS = {"T06": "T06s", "T07": "T07s", "T11": "T11s", "T01": "T01s", "T05": "T05s"}
CRITERIA_PAIRS = ("T06", "T07", "T11")
EDGE_MATCH_MIN = 0.90  # CRITERIA の 1.4: 辺の多重集合の一致率の下限

# 対ごとの「許す違いの一覧」（CRITERIA の 1.4。半自動の基準）。正規化の出力を見る前に、入力のコード・規則表・主セットの正解 IR
# （expected/public/。出力を見る前に別のサブエージェントが書いたもの）から書いた（2026-11-08、フェーズ 3 の手順 6 の後半）。
# 構成そのものの違い（作者の選んだ型・TF 版だけが作る補助のもの）だけを書く。道具の限界による違いはここに書かない（KNOWN_LIMITATIONS）。
#   same_type: {TF の側のノードの型: (SAM の側の型, 置き換える件数, 理由)}。同じ役目のものを作者が別の型で作った。比べる前に置き換える
#   nodes／edges: 置き換えの後に片側にだけ残ってよいもの {"only_tf"／"only_sam": {型 または (from の型, to の型, kind): (件数, 理由)}}
# 件数まで書く。実際の違い・置き換えの件数が一覧より多くても少なくても失敗にする（tf_public_check.py の PAIR_EXPECTED と同じ。
# 一覧が古くならない）。結果を見てから一覧を変えるときは、理由をここに書き足す（CRITERIA の 0 の 4）。
# 2026-11-08 の第三者レビューで、T11 の辺（API → ステートマシン）を一覧から KNOWN_LIMITATIONS へ移した（SAM 版も統合を宣言しており、
# 構成の違いではなく CFN アダプタの限界のため）。T07 の 2 件は構成の違いとして認められた。
HTTP_VS_REST = "TF 版は HTTP API（API Gateway v2）、SAM 版は Events の Type: Api の暗黙の REST API。作者の選んだ API の種類の違い（tf_public_check.py の T07）"
EMPTY = {"only_tf": {}, "only_sam": {}}
PAIR_ALLOWED: dict[str, dict] = {
    "T06": {"same_type": {}, "nodes": EMPTY, "edges": EMPTY},
    "T07": {
        "same_type": {"apigw_http_api": ("apigw_rest_api", 1, HTTP_VS_REST)},
        "nodes": {
            "only_tf": {"s3_bucket": (1, "TF 版は Lambda のコードの置き場のバケットを自分で作る（描く型）。SAM 版は CodeUri を "
                                         "sam package が上げるのでテンプレートに無い（正解 IR の T07 と T07s も同じ違い）")},
            "only_sam": {},
        },
        "edges": EMPTY,  # コードの置き場への参照（s3_bucket・s3_key）は辺にしない（関数 → バケットの辺は無い）
    },
    "T11": {"same_type": {}, "nodes": EMPTY, "edges": EMPTY},
    # 補助セットの対（参考）
    "T01": {"same_type": {}, "nodes": EMPTY, "edges": EMPTY},
    "T05": {"same_type": {}, "nodes": EMPTY, "edges": EMPTY},
}

# 道具の限界で出る違い（許す違いではない。1.4 の判定には使わず、合否は「NG（既知の制約・ユーザーの確認待ち）」と出す）。
# 形は PAIR_ALLOWED の nodes／edges と同じ。違いがこれで説明しきれることだけを確かめる（ほかの違いは NG）
KNOWN_LIMITATIONS: dict[str, dict] = {
    "T11": {
        "nodes": EMPTY,
        "edges": {
            "only_tf": {("apigw_rest_api", "sfn_state_machine", "request"): (
                1, "SAM 版も API → ステートマシンの統合を宣言している（DefinitionBody の AWS::Include の api.openapi.yaml と、ApiRole の "
                   "states:StartSyncExecution）が、CFN アダプタは AWS::Include を展開しないので raw に載らない（ir-schema の 8 章、"
                   "test_main_set_criteria.py の KNOWN_MISSING）。ユーザーの確認待ち")},
            "only_sam": {},
        },
    },
}
LIMITATION_NG = "NG（既知の制約・ユーザーの確認待ち）"


def pair_signature(ir: dict, same_type: dict[str, str] | None = None) -> tuple[Counter, Counter, Counter]:
    """(ノードの型の多重集合, 辺の (from の型, to の型, kind) の多重集合, 置き換えた件数 {(もとの型, 置き換えた型): 件数})。"""
    same_type = same_type or {}
    types = {n["id"]: same_type.get(n["type"], n["type"]) for n in ir["nodes"]}
    nodes = Counter(types.values())
    edges = Counter((types[e["from"]], types[e["to"]], e["kind"]) for e in ir["edges"])
    subst = Counter((n["type"], same_type[n["type"]]) for n in ir["nodes"] if n["type"] in same_type)
    return nodes, edges, subst


def match_ratio(a: Counter, b: Counter) -> float | None:
    """一致率 = 多重集合の共通部分の件数 ÷ 大きい方の件数（CRITERIA の 1.4）。両方空なら None。"""
    big = max(sum(a.values()), sum(b.values()))
    return None if big == 0 else sum((a & b).values()) / big


def _counts(table: dict) -> Counter:
    return Counter({k: n for k, (n, _) in table.items()})


def compare_pair_irs(pid: str, tf_ir: dict, sam_ir: dict) -> dict:
    """対の 2 つの normalized IR を比べる。`status` は OK／NG／LIMITATION_NG、`criteria_1_4` は 1.4 を満たすか（基準の対のとき）、
    `problems` は一覧（許す違い・既知の制約）で説明できない違いと、置き換えの件数の食い違い。"""
    allow, lim = PAIR_ALLOWED[pid], KNOWN_LIMITATIONS.get(pid, {"nodes": EMPTY, "edges": EMPTY})
    same = {k: v for k, (v, _, _) in allow["same_type"].items()}
    tn, te, subst = pair_signature(tf_ir, same)
    sn, se, _ = pair_signature(sam_ir)
    out: dict = {"pair": f"{pid}+{PAIRS[pid]}", "criteria": pid in CRITERIA_PAIRS, "problems": [],
                 "same_type": [[k[0], k[1], n] for k, n in sorted(subst.items())]}
    want_subst = Counter({(k, v): n for k, (v, n, _) in allow["same_type"].items()})
    if subst != want_subst:
        out["problems"].append(f"{out['pair']} same_type: 一覧は {sorted(want_subst.items())}、実際の置き換えは {sorted(subst.items())}")
    rest: dict[str, tuple[Counter, Counter]] = {}
    for what, a, b in (("nodes", tn, sn), ("edges", te, se)):
        diff = {"only_tf": a - b, "only_sam": b - a}
        out[what] = {"tf": sum(a.values()), "sam": sum(b.values()), "common": sum((a & b).values()),
                     "only_tf": _items(diff["only_tf"]), "only_sam": _items(diff["only_sam"])}
        for side in ("only_tf", "only_sam"):
            want = _counts(allow[what][side]) + _counts(lim[what][side])
            if diff[side] != want:
                out["problems"].append(f"{out['pair']} {what} {side}: 許す違い＋既知の制約は {_items(want)}、実際は {_items(diff[side])}")
        rest[what] = (a - _counts(allow[what]["only_tf"]), b - _counts(allow[what]["only_sam"]))
    ratio = match_ratio(*rest["edges"])
    out["edge_match"] = {"raw": match_ratio(te, se), "allowed_removed": ratio,
                         "limitations_removed": match_ratio(rest["edges"][0] - _counts(lim["edges"]["only_tf"]),
                                                            rest["edges"][1] - _counts(lim["edges"]["only_sam"]))}
    fails = []
    if rest["nodes"][0] != rest["nodes"][1]:
        fails.append("ノードの型の多重集合が、許す違いを除いて一致しない")
    if ratio is not None and ratio < EDGE_MATCH_MIN:
        fails.append(f"辺の一致率 {ratio:.3f} < {EDGE_MATCH_MIN}")
    out["criteria_1_4"] = not fails
    out["criteria_failures"] = fails
    out["known_limitations"] = [why for what in ("nodes", "edges") for side in ("only_tf", "only_sam")
                                for _, (_, why) in lim[what][side].items()]
    if out["problems"]:
        out["status"] = "NG"
    elif fails and out["criteria"]:
        out["status"] = LIMITATION_NG if out["known_limitations"] else "NG"
        if not out["known_limitations"]:
            out["problems"] += [f"{out['pair']}: {f}（CRITERIA の 1.4）" for f in fails]
    else:
        out["status"] = "OK"
    return out


def _items(c: Counter) -> list:
    """Counter を JSON にできる [[キー, 件数], …]（キーの順）にする。"""
    return [[list(k) if isinstance(k, tuple) else k, n] for k, n in sorted(c.items(), key=lambda kv: str(kv[0]))]


def compare_pair(pid: str) -> dict:
    tf_ir = build.normalize(raw_of(pid), name=ir_name(pid))
    sam_ir = build.normalize(raw_of(PAIRS[pid]), name=ir_name(PAIRS[pid]))
    return compare_pair_irs(pid, tf_ir, sam_ir)


def run_pairs() -> list[dict]:
    return [compare_pair(pid) for pid in PAIRS]


# --------------------------------------------------------------------------------------------------------------

def fmt_counter(d: dict) -> str:
    return ", ".join(f"{k}×{v}" for k, v in d.items()) or "-"


def print_inputs(results: list[dict]) -> None:
    print("| 入力 | 形式 | リソース | ノード | 辺 | R-SG | unknown | UNUSED-REF | NORM-（UNUSED 以外） | 問題 | 秒（raw+正規化） |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for r in results:
        if "resources" not in r:
            print(f"| {r['id']} | {r['format']} | — | — | — | — | — | — | — | {'; '.join(r['problems'])} | — |")
            continue
        s = r["seconds"]
        unk = sum(r["unknown"].values())
        print(f"| {r['id']} | {r['format']} | {r['resources']} | {r['nodes']} | {r['edges']} | {r['edges_r_sg']} | "
              f"{unk}{' (' + fmt_counter(r['unknown']) + ')' if unk else ''} | "
              f"{r['unused_refs']}{' (' + fmt_counter(r['unused_ref_attrs']) + ')' if r['unused_refs'] else ''} | "
              f"{fmt_counter(r['norm_diagnostics'])} | {len(r['problems'])} | {s['raw']}+{s['normalize']} |")


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):  # テストで差し替えた StringIO には無い
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="正規化を公開サンプルで確かめる（フェーズ 3 の手順 6）")
    ap.add_argument("--only", nargs="+", help="入力を絞る（INPUTS の ID か、その前の部分。例: T19 C05 T20）")
    ap.add_argument("--jobs", type=int, default=1, help="並列に動かすプロセスの数")
    ap.add_argument("--pairs", action="store_true", help="TF／SAM の対の比較だけを出す（一巡はしない）")
    ap.add_argument("--out", type=Path, help="結果の JSON を書くファイル（時間は入れない）")
    a = ap.parse_args(argv)

    failed = False
    report: dict = {}
    if not a.pairs:
        t0 = time.perf_counter()
        results = run_inputs(select(a.only), a.jobs)
        print_inputs(results)
        bad = [r for r in results if r["problems"]]
        print(f"{'NG' if bad else 'OK'} inputs={len(results)} problems={sum(len(r['problems']) for r in bad)} "
              f"({time.perf_counter() - t0:.1f} s)")
        for r in bad:
            for p in r["problems"][:20]:
                print(f"  NG {r['id']}: {p}")
        failed |= bool(bad)
        report["inputs"] = [{k: v for k, v in r.items() if k != "seconds"} for r in results]
    if a.pairs or not a.only:
        pairs = run_pairs()
        for r in pairs:
            em = r["edge_match"]
            print(f"{r['status']} {r['pair']}{'' if r['criteria'] else '（参考。1.4 の対象外）'}: "
                  f"nodes tf={r['nodes']['tf']} sam={r['nodes']['sam']} common={r['nodes']['common']}; "
                  f"edges tf={r['edges']['tf']} sam={r['edges']['sam']} common={r['edges']['common']} "
                  f"match={em['raw']}（許す違いを除くと {em['allowed_removed']}。既知の制約も除くと {em['limitations_removed']}）"
                  f" 1.4={'満たす' if r['criteria_1_4'] else '満たさない'}")
            for tf_type, sam_type, n in r["same_type"]:
                print(f"    same_type {tf_type} → {sam_type} x{n}")
            for what in ("nodes", "edges"):
                for side in ("only_tf", "only_sam"):
                    for k, n in r[what][side]:
                        print(f"    {what} {side} {k} x{n}")
            for f in r["criteria_failures"]:
                print(f"    1.4: {f}")
            for why in r["known_limitations"]:
                print(f"    既知の制約: {why}")
            for p in r["problems"]:
                print(f"  NG {p}")
        failed |= any(r["status"] != "OK" for r in pairs)  # 既知の制約の NG も、ユーザーが決めるまで失敗として返す
        report["pairs"] = pairs
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
