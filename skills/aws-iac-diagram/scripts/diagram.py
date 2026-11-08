# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""normalized IR から `.drawio` のビューと `coverage.md` を書く（フェーズ 4）。

使い方:
  uv run scripts/diagram.py --input <normalized IR の JSON> --out-dir <フォルダ>

書くもの: <名前>.overview.drawio・<名前>.network.drawio・<名前>.detail.drawio（分割のときは -1、-2）、coverage.md、result.json。

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
from aws_iac_diagram.emit import coverage, drawio as emit_drawio  # noqa: E402
from aws_iac_diagram.layout import search, views  # noqa: E402
from aws_iac_diagram.validate import drawio as check_drawio  # noqa: E402


def render_view(ir: dict, view: views.View, r: rules.Rules, catalog: dict) -> tuple[str, str, list[check_drawio.Problem]]:
    """(選んだ候補の名前, XML, 問題の一覧)。"""
    sub = {"name": f"{ir['name']}-{view.name}", "nodes": view.nodes, "edges": view.edges}
    name, layout, _ = search.best(view.nodes, view.edges, lambda c: check_drawio.score(emit_drawio.emit(sub, c, r, catalog)))
    xml = emit_drawio.emit(sub, layout, r, catalog)
    return name, xml, check_drawio.check(xml)


def write_all(ir: dict, out_dir: Path, r: rules.Rules, catalog: dict) -> int:
    """図と付属のファイルを書き、見つかった問題の数を返す。"""
    result: dict = {"name": ir["name"], "views": {}}
    bad = 0
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
        (out_dir / f"{ir['name']}.{view.name}.drawio").write_text(xml, encoding="utf-8", newline="\n")
        result["views"][view.name] = {"candidate": candidate, "icons": icons, "edges": len(view.edges),
                                      "problems": [[p.kind, p.subject, p.other] for p in problems]}
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
        bad = write_all(ir, a.out_dir, r, catalog)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, StopIteration) as ex:  # 形の壊れた IR・書けない出力
        print(f"書けません: {type(ex).__name__}: {ex}", file=sys.stderr)
        return 2
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
