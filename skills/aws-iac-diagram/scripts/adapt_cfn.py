# /// script
# requires-python = ">=3.12"
# dependencies = ["PyYAML==6.0.3"]
# ///
"""CloudFormation のテンプレートを読み、アダプタの出力（raw IR。references/ir-schema.md の 7章）を作る。

いまの範囲（フェーズ1 の手順2〜4）:
  - YAML の短縮タグ（!Ref など）を Fn::* の長い形に正規化する（PLAN 2.2 の失敗知見 13。awscli の yamlhelper と同じ考え方）
  - Ref・Fn::GetAtt・Fn::Sub・Fn::Join・Fn::Select・Fn::Split・Fn::GetAZs・Fn::ImportValue・DependsOn を評価し、
    props の印（$res・$pseudo・$concat・$json・$az・$import・$unknown）と references を作る
  - パラメータは、外から渡した値（--param、--param-file）→ Default の順に使う（どちらも無ければ $unknown）。
    ネストスタックでは親から渡された値を使う
  - A4: Conditions（Fn::Equals・And・Or・Not・Condition）を 真／偽／決まらない の3つの値で評価する。
    リソースの Condition から enabled を決め、ネストスタックの子にも伝える。Fn::If・Fn::FindInMap（DefaultValue を含む）・
    Fn::Length・Fn::ToJsonString を評価する。Fn::ForEach（AWS::LanguageExtensions）を展開する（値が決まらなければ ×N）
  - YAML の値の真偽値は YAML 1.1 のまま（cfn-lint と同じ）。マップのキーは元の文字のまま読む
  - SAM: Globals を各リソースに混ぜる。Events に API の指定が無いときは、暗黙の API（implicit）を足す
  - ネストスタック: 子テンプレートを展開し、Outputs・Parameters をたどって元のリソースへの $res にする（経路は through）。
    TemplateURL が URL なら手元のファイルに読み替え、読めなければ黒箱（via: module_blackbox）にする
  - cdk.out: manifest.json のスタックをすべて読み、address に "<スタック名>::" を付ける。Export を ImportValue で解決する
評価できない値（決まらない条件の Fn::If、Fn::Base64、Fn::Cidr など）は $unknown にし、中の参照は
state: "unevaluated" で残す。選ばれなかった値の中の参照は state: "pruned" で残す。

使い方:
  uv run scripts/adapt_cfn.py --input <テンプレートか cdk.out のフォルダ> --out <raw.json>
      [--root-base <フォルダ>] [--param KEY=VALUE ...] [--param-file <parameters.json> ...]
  --root-base: raw IR の root を、このフォルダからの相対パスで書く（既定: 作業中のフォルダ）
  --param: パラメータの値。AWS::Region などの擬似パラメータは、条件の評価にだけ使う（props は $pseudo のまま）
  --param-file: aws cloudformation の CLI の形（[{"ParameterKey", "ParameterValue"}]）、{"Parameters": {...}}、{キー: 値}

終了コード: 0 = 書けた（diagnostics に warn・error があっても）、2 = テンプレートを読めなかった

このファイルは入口（引数の処理と終了コード）だけ。中身は scripts/aws_iac_diagram/adapters/cloudformation/（docs/architecture.md の 2 と 6）。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

from aws_iac_diagram.adapters.cloudformation.build import build_raw, dump  # noqa: E402
from aws_iac_diagram.adapters.cloudformation.params import load_parameter_file  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="CloudFormation のテンプレートから raw IR を作る")
    ap.add_argument("--input", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--root-base", type=Path, default=None)
    ap.add_argument("--param", action="append", default=[], metavar="KEY=VALUE",
                    help="パラメータの値（何回でも指定できる。AWS::Region などは条件の評価にだけ使う）")
    ap.add_argument("--param-file", type=Path, action="append", default=[],
                    help="パラメータの値のファイル（CLI の parameters.json の形、{\"Parameters\": {...}}、{キー: 値}）")
    a = ap.parse_args(argv)
    try:
        params: dict = {}
        for f in a.param_file:
            params.update(load_parameter_file(f))
        for kv in a.param:
            if "=" not in kv:
                print(f"--param は KEY=VALUE の形で指定してください: {kv}", file=sys.stderr)
                return 2
            k, v = kv.split("=", 1)
            params[k] = v
        raw = build_raw(a.input, a.root_base, params)
    except (OSError, ValueError, yaml.YAMLError) as e:
        print(f"テンプレートを読めませんでした: {a.input}: {e}", file=sys.stderr)
        return 2
    except Exception as e:  # noqa: BLE001  想定外の失敗も終了コード 2 で返す（自分を指すアンカーの RecursionError など）
        print(f"テンプレートの評価に失敗しました: {a.input}: {type(e).__name__}: {e}", file=sys.stderr)
        return 2
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(dump(raw), encoding="utf-8", newline="\n")
    print(f"raw: resources={len(raw['resources'])} references={len(raw['references'])} "
          f"diagnostics={len(raw['diagnostics'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
