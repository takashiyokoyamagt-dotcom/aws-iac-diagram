# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""raw IR（アダプタの出力。docs/spec/ir-schema/ の 7章）を正規化し、normalized IR（同 1〜6章）を書く（フェーズ 3）。

いまの範囲（手順 3a・3b）: 網羅分類（A6）、ノード（B3・K-NAME）、入れ子（P-*）と AZ のノード（N-AZ）。辺（A1〜A3）と、
辺で決まる分類（R-*。関係リソース → 辺）・合成ノード（`external/internet`・`bedrock_model`）・サブネットの `attrs.access` は
まだ作らない。そのため、関係リソースのある入力では、R-* の分類が「仮」（`into` が空）のまま残り、出力は検査
（`validate_ir.py`。`into` は 1 つ以上）に通らない。**それを隠さず、終了コード 1 で知らせる**（出力のファイルは書く）。

終了コード 0 と `validate_ir.py` の関係: ここが見るのは網羅分類（入力の全リソースがちょうど 1 回ずつ）と仮の分類（`into` が空）だけで、
スキーマと参照の整合の全部は `validate_ir.py` が見る。仮の分類があれば必ず 1 なので、関係リソース（R-*）のある入力は、辺の段階
（手順 4）ができるまで 0 にならない。0 になるのは関係リソースも統合先の見つからない M-* も無い入力だけで、そのときも
`validate_ir.py` に通ることまでは約束しない（辺・合成ノードがまだ無いため、正解 IR とも違う）。

使い方:
  uv run scripts/normalize_ir.py --input <raw IR の JSON> --out <normalized IR の JSON> [--name <名前>]
  --name: IR の名前（小文字・数字・`-`。省略すると root の最後の要素から作る）

終了コード: 0 = 書けて、検査の問題が無い
            1 = 書けたが、検査の問題がある（網羅分類の漏れ・重複、仮のままの分類）。内容は標準エラーに書く
            2 = 書けなかった（入力を読めない・raw IR でない・raw IR の検査に通らない・規則表が壊れている・出力を書けない・想定外の失敗）

このファイルは入口（引数の処理と終了コード）だけ。中身は scripts/aws_iac_diagram/normalize/（docs/architecture.md の 2）。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from aws_iac_diagram.core import ir_norm, ir_raw, rules  # noqa: E402
from aws_iac_diagram.normalize import build  # noqa: E402

NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")  # ir.schema.json の name


def read_raw(path: Path) -> dict:
    """raw IR を読む。読めない・raw IR でない・検査（core/ir_raw.semantic_errors）に通らなければ ValueError。"""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as e:
        raise ValueError(f"読めない: {e}") from e
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON として読めない: {e}") from e
    if not isinstance(raw, dict) or raw.get("stage") != "raw" or raw.get("format") not in ("tf", "cfn") \
            or not isinstance(raw.get("resources"), list) or not isinstance(raw.get("references"), list):
        raise ValueError("raw IR（stage が \"raw\"、format が tf か cfn、resources と references を持つ）でない")
    errors = ir_raw.semantic_errors(raw)
    if errors:
        raise ValueError("raw IR の検査に通らない: " + "; ".join(errors[:5]) + (f"（ほか {len(errors) - 5} 件）" if len(errors) > 5 else ""))
    return raw


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="raw IR を正規化して normalized IR を書く")
    ap.add_argument("--input", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--name", default=None, help="IR の名前（小文字・数字・-）")
    a = ap.parse_args(argv)
    if a.name is not None and not NAME.match(a.name):
        print(f"--name は小文字・数字・- で書いてください（先頭は英数字）: {a.name}", file=sys.stderr)
        return 2
    try:
        raw = read_raw(a.input)
        ir = build.normalize(raw, rules.default(), a.name)
    except ValueError as e:
        print(f"raw IR を読めませんでした: {a.input}: {e}", file=sys.stderr)
        return 2
    except rules.RulesError as e:
        print(str(e), file=sys.stderr)
        return 2
    except Exception as e:  # noqa: BLE001  想定外の失敗も終了コード 2 で返す
        print(f"正規化に失敗しました: {a.input}: {type(e).__name__}: {e}", file=sys.stderr)
        return 2
    try:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(ir_norm.canonical_dump(ir), encoding="utf-8", newline="\n")
    except OSError as e:
        print(f"normalized IR を書けませんでした: {a.out}: {e}", file=sys.stderr)
        return 2
    problems, provisional = build.check(raw, ir)
    print(f"normalized: nodes={len(ir['nodes'])} edges={len(ir['edges'])} resources={len(ir['sources'][raw['format']]['resources'])} "
          f"provisional={len(provisional)} diagnostics={len(ir['diagnostics'])}")
    for p in problems:
        print(f"問題: {p}", file=sys.stderr)
    if provisional:
        print(f"仮のままの分類が {len(provisional)} 件あります（辺の段階が未実装のため。検査に通る IR ではありません）: "
              + ", ".join(provisional[:10]) + (" ほか" if len(provisional) > 10 else ""), file=sys.stderr)
    return 1 if problems or provisional else 0


if __name__ == "__main__":
    sys.exit(main())
