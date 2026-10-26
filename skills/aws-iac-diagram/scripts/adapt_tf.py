# /// script
# requires-python = ">=3.12"
# dependencies = ["python-hcl2==8.1.4"]
# ///
"""Terraform のルートモジュール（.tf のフォルダ）を読み、アダプタの出力（raw IR。references/ir-schema.md の 7章）を作る。

いまの範囲（フェーズ2 の手順1〜4）:
  - フォルダ直下の *.tf を python-hcl2 で読み（構文木をそのまま使う）、resource・data・module のブロックを集める。
    check ブロックの中の data も読む。*_override.tf・override.tf は Terraform と同じ規則で元のブロックに重ねる
  - 属性とブロックを props にする（ブロックはリスト。count・for_each・provider・depends_on・lifecycle・
    provisioner・connection はメタ引数なので props に入れない）。dynamic ブロックは for_each が決まれば展開する
  - A4（手順2）: 変数（default → terraform.tfvars → terraform.tfvars.json → *.auto.tfvars(.json)（名前順）→
    --var-file・--var（指定した順））、locals、テンプレート（${…}、%{if}・%{for}）、条件式・演算・for 式・
    組み込み関数（aws_iac_diagram/adapters/terraform/evaluator/）を評価する。count・for_each が決まればインスタンスごとに出し（address の
    [0]・["key"]、0 個なら enabled: false で添字なし）、決まらなければ ×N（[*]、enabled: null）
  - 参照を印にする: resource・data・module への参照は $res（attr は最初の属性名。インスタンスへの参照と
    スプラットはインスタンスごと）、data.aws_region・aws_caller_identity・aws_partition は $pseudo、
    data.aws_availability_zones の names は $az、jsonencode(...) は $json、"${…}" と heredoc は $concat
    （JSON として読めれば $json）。depends_on は references にだけ
  - 評価できなかった値は $unknown（中の参照は state: "unevaluated"）。条件式の選ばれなかった側、try で使わな
    かった式、選ぶ関数（coalesce・element など）とリストの添字で選ばなかった要素、for 式の if で除いた要素の中の
    参照は state: "pruned"（決まった count・for_each の式の参照は残さない。ir-schema.md の 7.2）
  - path.module・path.root・path.cwd はルートからの相対パス（ルートは "."）、terraform.workspace は "default"
    （--workspace で変えられる。使ったとき evaluation.assumptions に書く）
  - provider = aws.<alias> のリソースは provider を書く。region は、リソースの引数 region（AWS provider v6）→
    その provider の region の順で、文字列で決まるときだけ書く
  - heredoc の開始・終端の行の末尾の空白を取ってから読む（python-hcl2 が読めないため。7.4。診断 info）
  - モジュール（手順3。ir-schema.md の 7.2 の「TF のモジュール」）: ローカルモジュール（./・../）は再帰的に
    展開する（address は module.x.…、count・for_each の呼び出しはインスタンスごと）。子の変数は呼び出しの引数を
    親の中で評価した値、module.x.y は子の出力 y の値で、たどった経路を参照の through に書く。terraform-aws-modules
    の vpc・alb・rds・eks は A5 の要約表（references/module-summaries.md、aws_iac_diagram/adapters/terraform/modules/）で展開する
    （via: module_summary）。それ以外のレジストリ・git などのソースと、読めない・循環する・深すぎるものは黒箱の
    呼び出し1件（type: module、via: module_blackbox）。providers 引数で渡した provider をたどって provider・region
    を書く。terraform_remote_state の出力への参照は attr: "outputs.<名前>"（state は読まない）
  - plan JSON（手順4。aws_iac_diagram/adapters/terraform/plan/、ir-schema.md の 7.2「TF の plan JSON」と 7.3「plan JSON の参照」）:
    --input に plan JSON（terraform show -json の出力の .json）を渡すと、plan JSON だけから作る（file は plan JSON
    の名前）。--input にフォルダ、--plan に plan JSON を渡すと、変数の値は plan の variables を使い、address と
    作られるかは plan、file・props・参照の位置は .tf にする（.tf で決まらなかった値は plan の値で埋める）。
    plan の sensitive の値は使わない。.tf.json のブロックは、plan と一緒なら plan から取る
読まないもの:
  - .tf.json は .tf だけでは読まない（診断 TF-TFJSON-UNSUPPORTED、warn）。JSON の書き方では入れ子のブロックと属性
    （オブジェクトの値）を区別できず、区別には provider のスキーマが要るため（ir-schema.md の 7.2「TF のそのほかの
    ブロック」）。plan JSON と一緒なら plan から取る（上）
file()・templatefile() などのファイルを読む関数は、ファイルを読まずに $unknown（診断 TF-UNEVALUATED）。
引数の中の参照は unevaluated で残す。sensitive = true・ephemeral = true の変数と sensitive() の値は使わない
（$unknown。evaluation.vars にも書かない）。

使い方:
  uv run scripts/adapt_tf.py --input <ルートモジュールのフォルダ> --out <raw.json> [--root-base <フォルダ>]
      [--var-file <ファイル> ...] [--var KEY=VALUE ...] [--redact-var <名前> ...] [--plan <plan JSON>]
      [--workspace <名前>]
  uv run scripts/adapt_tf.py --input <plan JSON> --out <raw.json> [--root-base <フォルダ>]
  --plan: 同じ構成の plan JSON（terraform show -json <plan> の出力）。--input のフォルダの .tf と合わせて読む
  --root-base: raw IR の root を、このフォルダからの相対パスで書く（既定: 作業中のフォルダ）
  --var-file: 変数の値のファイル（.tfvars か .tfvars.json）。相対パスは作業中のフォルダ、無ければ --input から
  --var: 変数の値。type が list・map・object などの変数は HCL の式として読む（Terraform の -var と同じ）
  --var-file と --var は、指定した順に後のものが優先する（Terraform と同じ）
  --workspace: terraform.workspace の値（既定は "default"。plan JSON だけのときは使えない）
  --redact-var: 値を伏せる変数（sensitive = true と同じく値を使わず、props では $unknown）。
    sensitive を付けていない変数の値は props（図のラベルなど）に入りうる。evaluation.vars には値を書かない

終了コード: 0 = 書けた（diagnostics に warn・error があっても）、2 = フォルダや変数のファイル・plan JSON を読めなかった
（plan JSON でない .json、state の JSON、plan JSON だけのときの --var-file・--var・--redact-var も 2）

このファイルは入口（引数の処理と終了コード）だけ。中身は scripts/aws_iac_diagram/adapters/terraform/（docs/architecture.md の 2 と 6）。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from aws_iac_diagram.adapters.terraform.build import build_from_plan, build_raw, dump  # noqa: E402
from aws_iac_diagram.adapters.terraform.plan import reader as PR  # noqa: E402


class _OrderedVar(argparse.Action):
    """--var-file と --var を、指定した順のまま1つのリストに入れる。"""

    def __call__(self, parser, namespace, values, option_string=None):
        items = list(getattr(namespace, "var_args", None) or [])
        items.append(("file" if option_string == "--var-file" else "var", values))
        namespace.var_args = items


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Terraform のルートモジュール（か plan JSON）から raw IR を作る")
    ap.add_argument("--input", required=True, type=Path,
                    help="ルートモジュールのフォルダか、plan JSON（terraform show -json の出力の .json）")
    ap.add_argument("--plan", type=Path, default=None,
                    help="同じ構成の plan JSON（--input のフォルダの .tf と合わせて読む）")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--root-base", type=Path, default=None)
    ap.add_argument("--var-file", action=_OrderedVar, dest="var_args", metavar="FILE",
                    help="変数の値のファイル（.tfvars・.tfvars.json。何回でも指定できる）")
    ap.add_argument("--redact-var", action="append", default=[], metavar="NAME",
                    help="値を伏せる変数（何回でも指定できる。sensitive = true と同じく値を使わない）")
    ap.add_argument("--workspace", default="default", metavar="NAME",
                    help="terraform.workspace の値（既定は default。選んだワークスペースの図にするとき）")
    ap.add_argument("--var", action=_OrderedVar, dest="var_args", metavar="KEY=VALUE",
                    help="変数の値（何回でも指定できる。--var-file と合わせて、後のものが優先）")
    a = ap.parse_args(argv)
    var_args = a.var_args or []
    for kind, item in var_args:
        if kind == "var" and "=" not in item:
            print(f"--var は KEY=VALUE の形で指定してください: {item}", file=sys.stderr)
            return 2
    plan_only = a.input.is_file()
    if plan_only and not PR.is_plan_file(a.input):
        why = PR.why_unreadable(a.input) if a.input.suffix.lower() == ".json" else None
        if why:
            print(f"plan JSON を読めませんでした: {why}", file=sys.stderr)
            return 2
        print(f"--input には、ルートモジュールのフォルダか plan JSON（terraform show -json の出力の .json）を指定して"
              f"ください: {a.input.name}", file=sys.stderr)
        return 2
    if not re.fullmatch(r"[A-Za-z0-9._-]+", a.workspace):
        print("--workspace には、英数字と . _ - だけの名前を指定してください（Terraform のワークスペース名）", file=sys.stderr)
        return 2
    if plan_only and (a.plan is not None or var_args or a.redact_var or a.workspace != "default"):
        print("--input に plan JSON を渡したときは、--plan・--var-file・--var・--redact-var・--workspace は使えません（変数の値は "
              "plan のものを使う。値を伏せるには .tf のフォルダを --input に、plan JSON を --plan に渡す）",
              file=sys.stderr)
        return 2
    try:
        if plan_only:
            raw = build_from_plan(a.input, a.root_base)
        else:
            raw = build_raw(a.input, a.root_base, var_args=var_args, redact_vars=a.redact_var, plan=a.plan,
                            workspace=a.workspace)
        text = dump(raw)
    except PR.PlanError as e:
        print(f"plan JSON を読めませんでした: {e}", file=sys.stderr)
        return 2
    except RecursionError:
        print("入力の入れ子が深すぎて処理できませんでした", file=sys.stderr)
        return 2
    except (OSError, ValueError) as e:
        # 絶対パスは書かない（OSError の文には入力のパスが入る）
        print(f"Terraform のフォルダを読めませんでした: {a.input.name}: "
              f"{type(e).__name__ if isinstance(e, OSError) else e}", file=sys.stderr)
        return 2
    except Exception as e:  # noqa: BLE001  想定外の失敗も終了コード 2 で返す
        if plan_only:  # plan JSON の中身や絶対パスは書かない
            print(f"plan JSON の処理に失敗しました: {type(e).__name__}", file=sys.stderr)
        else:
            print(f"Terraform の評価に失敗しました: {a.input.name}: {type(e).__name__}: {e}", file=sys.stderr)
        return 2
    try:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(text, encoding="utf-8", newline="\n")
    except OSError as e:
        print(f"raw IR を書けませんでした: {a.out}: {e}", file=sys.stderr)
        return 2
    print(f"raw: resources={len(raw['resources'])} references={len(raw['references'])} "
          f"diagnostics={len(raw['diagnostics'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
