# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""normalized IR から `.drawio` のビューと `coverage.md` を書く（フェーズ 4）。

使い方:
  uv run scripts/diagram.py --input <normalized IR の JSON> --out-dir <フォルダ> [--no-external]
  --no-external: PNG の書き出しと mmdc の描画確認をしない（出力の固定の比較用。環境に依らない）

書くもの: ビュー（overview・network・detail。分割のときは -1、-2）ごとの <名前>.<ビュー>.drawio・.mmd・.png、coverage.md、result.json。
draw.io や mmdc が使えないときは、その確認だけをスキップして result.json に理由を書く（終了コードは失敗にしない）。

終了コード: 0 = 書けて、見やすさの検査に問題が無い
            1 = 書けたが、問題がある（内容は result.json と標準エラー）
            2 = 書けなかった（入力を読めない・normalized IR でない・出力を書けない）

このファイルは入口だけ。中身は scripts/aws_iac_diagram/{layout,emit,validate}/。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from aws_iac_diagram.core import rules  # noqa: E402
from aws_iac_diagram.emit import coverage, drawio as emit_drawio, mermaid as emit_mermaid  # noqa: E402
from aws_iac_diagram.layout import search, views  # noqa: E402
from aws_iac_diagram.platform import drawio_cli, external  # noqa: E402
from aws_iac_diagram.validate import drawio as check_drawio, mermaid as check_mermaid  # noqa: E402


def render_view(ir: dict, view: views.View, r: rules.Rules, catalog: dict) -> tuple[str, str, list[check_drawio.Problem]]:
    """(選んだ候補の名前, XML, 問題の一覧)。"""
    sub = {"name": f"{ir['name']}-{view.name}", "nodes": view.nodes, "edges": view.edges}
    name, layout, _ = search.best(view.nodes, view.edges, lambda c: check_drawio.score(emit_drawio.emit(sub, c, r, catalog)))
    xml = emit_drawio.emit(sub, layout, r, catalog)
    return name, xml, check_drawio.check(xml)


def _external_checks(stem: Path, state: dict) -> tuple[dict, list[str]]:
    """PNG を書き、`.mmd` の描画を確かめる。(そのビューの状態, 検証の問題)。無いツールは 1 回だけ探す（state）。"""
    out: dict = {}
    problems: list[str] = []
    png = stem.with_suffix(".png")
    if state["drawio"] is None:
        out["png"] = {"status": "skipped", "reason": state["drawio_reason"]}
    else:
        try:
            drawio_cli.export_png(stem.with_suffix(".drawio"), png, exe=state["drawio"])
            bad = external.png_problem(png)
            out["png"] = {"status": "failed" if bad else "ok", "reason": bad}
            if bad:
                problems.append(f"png: {bad}")
        except drawio_cli.DrawioError as ex:  # 起動できない・タイムアウト・無出力はスキップ（PLAN の 5）
            out["png"] = {"status": "skipped", "reason": str(ex).splitlines()[0][:200]}
    status, reason = external.check_mermaid(stem.with_suffix(".mmd"), state["mmdc"]) if state["mmdc"] else ("skipped", "mmdc が見つからない")
    out["mermaid"] = {"status": status, "reason": reason}
    if status == "failed":
        problems.append(f"mermaid: {reason}")
    return out, problems


def _tools(external_on: bool) -> dict | None:
    if not external_on:
        return None
    state: dict = {"drawio": None, "drawio_reason": "", "mmdc": external.find_mmdc()}
    try:
        state["drawio"] = drawio_cli.find_drawio()
    except drawio_cli.DrawioError as ex:
        state["drawio_reason"] = str(ex).splitlines()[0][:200]
    return state


def write_all(ir: dict, out_dir: Path, r: rules.Rules, catalog: dict, external_on: bool = True) -> int:
    """図と付属のファイルを書き、見つかった問題の数を返す。"""
    result: dict = {"name": ir["name"], "views": {}}
    bad = 0
    tools = _tools(external_on)
    drawn_nodes: set[str] = set()
    drawn_edges: set[str] = set()
    queue = [(v, True) for v in views.build(ir)]
    while queue:
        view, may_split = queue.pop(0)
        candidate, xml, problems = render_view(ir, view, r, catalog)
        parts = views.split_by_root(view) if may_split and any(p.kind == "pierce" for p in problems) else [view]
        if len(parts) > 1:  # 貫通が残る図は枠ごとに分ける（B2）。分けた図はもう分けない
            queue = [(p, False) for p in parts] + queue
            continue
        problems = problems + check_drawio.check_shape(xml) + check_drawio.check_view(xml, {n["id"] for n in view.nodes}, view.edges)
        icons = views.icon_count(view.nodes)
        if icons > views.MAX_ICONS:
            problems.append(check_drawio.Problem("over40", view.name, str(icons)))
        if view.name.split("-")[0] == "overview":
            drawn_nodes |= {n["id"] for n in view.nodes}
            drawn_edges |= {e["id"] for e in view.edges}
        stem = out_dir / f"{ir['name']}.{view.name}"
        Path(f"{stem}.drawio").write_text(xml, encoding="utf-8", newline="\n")
        mmd = emit_mermaid.flowchart(view.nodes, view.edges)
        Path(f"{stem}.mmd").write_text(mmd, encoding="utf-8", newline="\n")
        problems += [check_drawio.Problem("mermaid", view.name, m) for m in check_mermaid.check(mmd, view.nodes, view.edges)]
        entry = {"candidate": candidate, "icons": icons, "edges": len(view.edges)}
        if tools is not None:
            status, extra = _external_checks(Path(f"{stem}.x"), tools)
            entry.update(status)
            problems += [check_drawio.Problem("external", view.name, m) for m in extra]
        entry["problems"] = [[p.kind, p.subject, p.other] for p in problems]
        result["views"][view.name] = entry
        bad += len(problems)
        for p in problems:
            print(f"{view.name}: {p.kind}: {p.subject} {p.other}", file=sys.stderr)
    lost = sorted(({n["id"] for n in ir["nodes"]} - drawn_nodes) | ({e["id"] for e in ir["edges"]} - drawn_edges))
    if lost:
        result["lost"] = lost
        bad += len(lost)
        print(f"全体図に出ていないもの: {lost}", file=sys.stderr)
    (out_dir / "coverage.md").write_text(coverage.render(ir), encoding="utf-8", newline="\n")
    (out_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                                         encoding="utf-8", newline="\n")
    return bad


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="normalized IR から .drawio と coverage.md を書く")
    ap.add_argument("--input", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--no-external", action="store_true", help="PNG の書き出しと mmdc の描画確認をしない")
    a = ap.parse_args(argv)
    try:
        ir = json.loads(a.input.read_text(encoding="utf-8"))
        if not isinstance(ir, dict) or ir.get("stage") != "normalized":
            raise ValueError("normalized IR ではない（stage が normalized でない）")
        r, catalog = rules.default(), emit_drawio.load_catalog()
        a.out_dir.mkdir(parents=True, exist_ok=True)
    except (OSError, ValueError, KeyError, rules.RulesError) as ex:
        print(f"書けません: {ex}", file=sys.stderr)
        return 2
    try:
        bad = write_all(ir, a.out_dir, r, catalog, not a.no_external)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, StopIteration) as ex:  # 形の壊れた IR・書けない出力
        print(f"書けません: {type(ex).__name__}: {ex}", file=sys.stderr)
        return 2
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
