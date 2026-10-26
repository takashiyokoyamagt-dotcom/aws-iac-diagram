"""アダプタが出す診断コード（raw IR の `diagnostics[].code`）の一覧。データだけ（ロジックは引くための関数のみ）。

- **単一の一覧。** アダプタ（Terraform の `TF-…`、CloudFormation の `CFN-…`）が出すコードはすべてここにある。
  コードを足す・消すときは、この一覧と `docs/spec/ir-schema/` の 7.5 の一覧を同じコミットで直す。
  `tests/architecture/test_diagnostics_registry.py`（アダプタのコードにある `TF-…`・`CFN-…` の文字列がこの一覧に無いと失敗。この一覧にあって
  使われていないコードも失敗）と `tests/architecture/test_diagnostics.py`（この一覧と ir-schema が同じ）が守る。
- **実行時には読まない。** アダプタはこのモジュールを import せず、コードを文字列のまま書く（出力のバイト列を変えないため。
  フェーズ 2b の決まり）。この一覧は検査と文書のための表。
- `levels` は、そのコードが出うる level（`error`＞`warn`＞`info`）。同じコードが場所によって level を変えるものがある
  （例: `TF-UNEVALUATED` は既定が warn で、`self` など図に影響しないものは info。作られないリソースの中の決まらない値は
  warn を info に下げる）。level は出力の一部なので、変えるときは golden の更新が要る。
- `NORM-…`（正規化後の IR の診断。フェーズ 3 以降）は、そのときここに足す。
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

ERROR, WARN, INFO = "error", "warn", "info"
LEVELS = (ERROR, WARN, INFO)  # 重い順

# コードの接頭辞 → アダプタ（層）の名前
PREFIXES = {"TF": "terraform", "CFN": "cloudformation"}
# 診断コードとして扱う接頭辞。検査（tests/architecture/test_diagnostics_registry.py）はこの接頭辞のコードだけを数える（"UTF-8" のような別の文字列で
# 誤って落ちないため）。NORM- など新しい接頭辞は、ここに意図して足す（PREFIXES と同じ）
ALLOWED_PREFIXES = tuple(PREFIXES)
CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9]*(-[A-Z0-9]+)+$")


@dataclass(frozen=True)
class Diagnostic:
    code: str
    levels: tuple[str, ...]  # 出うる level（重い順）
    description: str

    @property
    def adapter(self) -> str:
        return PREFIXES[self.code.split("-", 1)[0]]


def _row(code: str, levels: str, description: str) -> Diagnostic:
    return Diagnostic(code, tuple(levels.split("/")), description)


# コード順（アルファベット順）。levels は "warn/info" のように重い順に書く
_ROWS = (
    # --- CloudFormation アダプタ（scripts/adapt_cfn.py と aws_iac_diagram/adapters/cloudformation/）
    _row("CFN-ABSOLUTE-ROOT", "info", "入力が --root-base と別のドライブにあり、root を絶対パスで書いた（Windows）"),
    _row("CFN-CDK-STACKNAME-DUPLICATE", "info", "cdk.out で同じ stackName が複数ある。address には artifact の ID を使った"),
    _row("CFN-CONDITION-CYCLE", "error", "Conditions が自分自身を参照している（値は決まらない）"),
    _row("CFN-CONDITION-UNKNOWN", "warn/info",
         "条件の値が決まらない。Fn::If は warn（値は $unknown）、リソース・Export の Condition は info（enabled は null）"),
    _row("CFN-DYNAMIC-REF", "warn", "{{resolve:…}} の動的参照。値は決まらない"),
    _row("CFN-EXPORT-CONFLICT", "warn", "同じ Export の名前が複数ある。最初のものを使う"),
    _row("CFN-FOREACH-DUPLICATE", "error", "Fn::ForEach の展開で名前が重なった。後のものは無視する"),
    _row("CFN-FOREACH-UNRESOLVED", "warn",
         "Fn::ForEach の集まりが決まらない。Resources・Outputs では ×N で出し、プロパティの中では落とす"),
    _row("CFN-MALFORMED-RESOURCE", "error", "リソースの形が誤り（本体がオブジェクトでない、Type が無い、Fn::ForEach の形が誤り）"),
    _row("CFN-MAPPING-MISSING", "warn", "Fn::FindInMap の引く先が Mappings に無い"),
    _row("CFN-NESTED-CYCLE", "error/warn", "ネストスタックが自分自身を含む。子の展開で見つけたら error、出力をたどる途中なら warn"),
    _row("CFN-NESTED-UNREADABLE", "error/warn",
         "ネストスタックの子テンプレートを読めない（error）か、見つからない（warn。黒箱にする）"),
    _row("CFN-PARAM-NOT-ALLOWED", "warn", "渡したパラメータの値が AllowedValues に無い"),
    _row("CFN-PARAM-UNUSED", "info", "--param・--param-file で渡した名前が、テンプレートの Parameters に無い"),
    _row("CFN-SSM-PARAM", "warn", "AWS::SSM::Parameter::Value<…> 型のパラメータ。値は決まらない"),
    _row("CFN-UNDEFINED-CONDITION", "warn", "定義の無い条件を参照している"),
    _row("CFN-UNDEFINED-REF", "warn", "定義の無い名前への Ref・GetAtt・Sub・DependsOn、子の無い出力への参照"),
    _row("CFN-UNEVALUATED", "warn", "評価しない値（Fn::Base64・Fn::Cidr・Fn::Transform、決まらない式など）。値は $unknown"),
    _row("CFN-UNRESOLVED-PARAM", "warn", "値も Default も無いパラメータ。使ったところごと"),
    # --- Terraform アダプタ（scripts/adapt_tf.py と aws_iac_diagram/adapters/terraform/）
    _row("TF-COUNT-INDEX", "info", "×N のリソースや、作られないブロックの中の count.index・each.*。値は決まらない"),
    _row("TF-COUNT-UNRESOLVED", "warn", "count・for_each が決まらない。×N（enabled: null）で出す"),
    _row("TF-CYCLE", "warn", "変数・local・output が自分自身を参照している（値は決まらない）"),
    _row("TF-DUPLICATE-BLOCK", "warn", "同じ名前の変数・local・output・リソースが複数ある。最初のものを使う"),
    _row("TF-EPHEMERAL", "info", "ephemeral の値。apply の前は決まらない"),
    _row("TF-EVAL-ERROR", "warn/info",
         "Terraform なら誤りになる式（count が null・負、for_each の型の誤りなど）。作られないリソースの中なら info"),
    _row("TF-HEREDOC-TRAILING-SPACE", "info", "heredoc の開始・終端の行の末尾の空白を取ってから読んだ（python-hcl2 が読めないため）"),
    _row("TF-MALFORMED-BLOCK", "warn", "ブロックの形が誤り（provider の指定、providers、dynamic ブロック、モジュールの source など）"),
    _row("TF-MODULE-BLACKBOX", "info", "モジュールを読まず、黒箱にした（レジストリの要約表に無い、source を読めないなど）"),
    _row("TF-MODULE-CYCLE", "warn", "ローカルモジュールが自分自身を呼んでいる。黒箱にする"),
    _row("TF-MODULE-DEPTH", "warn", "モジュールの入れ子が深すぎる。黒箱にする"),
    _row("TF-MODULE-NOT-CREATED", "info", "count が 0 などで作られないモジュールの呼び出し（インスタンスが無い）"),
    _row("TF-MODULE-SUMMARY", "info", "要約表（A5）でモジュールを展開した。主要なリソースだけを書いている"),
    _row("TF-MODULE-SUMMARY-INPUT", "info", "要約表が扱わないモジュールの入力を渡している（その入力が作るリソースは書かない）"),
    _row("TF-MODULE-SUMMARY-OUTPUT", "warn", "要約表に無いモジュールの出力を参照している"),
    _row("TF-MODULE-SUMMARY-TABLE-MISSING", "warn", "要約表 data/module-summaries/ が無い・読めない（vpc・alb・rds・eks のモジュールのフォルダごと無いときを含む）のにレジストリモジュールの呼び出しがある"),
    _row("TF-MODULE-UNREADABLE", "warn", "ローカルモジュールのフォルダを読めない。黒箱にする"),
    _row("TF-OVERRIDE-UNMATCHED", "warn", "*_override.tf のブロックに対応する元のブロックが無い"),
    _row("TF-PARSE-ERROR", "error", ".tf を読めない（ほかのファイルは読む）"),
    _row("TF-PLAN-DESTROY", "warn/info", "destroy の plan（すべてが削除）は warn。一部だけ消える・state から外れる plan は info"),
    _row("TF-PLAN-DYNAMIC-BLOCK", "info", "plan の configuration に無いブロック（dynamic ブロック、provider が埋めるブロック）。中の参照は plan JSON からは分からない"),
    _row("TF-PLAN-ERRORED", "warn", "plan が失敗している（errored: true）。plan は途中までかもしれない"),
    _row("TF-PLAN-EXTRA-REF", "info", "plan の configuration にあって .tf から見つからない参照を、unevaluated で足した"),
    _row("TF-PLAN-INCOMPLETE", "warn", "plan が不完全（incomplete・deferred_changes）"),
    _row("TF-PLAN-LITERAL-ONLY", "info", "作られないリソースの、リテラル以外の値を plan から取らなかった"),
    _row("TF-PLAN-LOCALS", "info", "plan JSON には local の式が無く、local を通した参照は分からない（.tf のフォルダと一緒に読むと分かる）"),
    _row("TF-PLAN-MISMATCH", "warn", "plan と .tf のフォルダが食い違う（おそらく別の構成）"),
    _row("TF-PLAN-NOT-PLANNED", "info", ".tf にあって plan に無いリソースを出力しなかった"),
    _row("TF-PLAN-PATH-OUTSIDE", "info", "ローカルモジュールのフォルダが --input の外にあり、その .tf.json は探さない"),
    _row("TF-PLAN-SENSITIVE", "info", "plan で sensitive の値。値は使わない"),
    _row("TF-PLAN-UNKNOWN", "info", "plan で apply の後にしか決まらない値"),
    _row("TF-PROVIDER-UNCONFIGURED", "info", "alias の provider の設定がモジュールにも呼び出し元にも無く、region を決められない"),
    _row("TF-ROOT-OTHER-DRIVE", "info", "root が別のドライブにあり、ファイル名・フォルダ名だけを書いた（Windows）"),
    _row("TF-SENSITIVE-VAR", "info", "sensitive の変数・出力の値は使わない"),
    _row("TF-TFJSON-UNSUPPORTED", "warn/info", ".tf.json は .tf だけでは読まない（warn）。plan JSON と一緒のときは plan から取る（info）"),
    _row("TF-UNDEFINED-REF", "warn", "定義の無い変数・local・出力・リソースへの参照、depends_on の宛先が無い"),
    _row("TF-UNEVALUATED", "warn/info",
         "決まらない値を含む演算・関数、ファイルを読む関数など（warn）。self・要約表の path.module など図に影響しないものは info"),
    _row("TF-UNRESOLVED-VAR", "warn/info", "値の無い変数。使ったところごと。作られないリソースの中なら info"),
    _row("TF-UNRESOLVED-VARS", "info", "値の無い変数と *.tfvars の候補のまとめ"),
    _row("TF-UNSUPPORTED-FUNCTION", "warn/info", "未対応の関数。作られないリソースの中なら info"),
    _row("TF-VAR-INVALID", "warn", "変数の値が定数でない・式として誤り（--var、tfvars、default）"),
    _row("TF-VAR-UNDECLARED", "warn", "宣言の無い変数に値を渡した（--var、--var-file、--redact-var、モジュールの引数）"),
    _row("TF-VARFILE-OTHER-DRIVE", "info", "変数のファイルが別のドライブにあり、相対パスにできないので名前だけを書いた（Windows）"),
)

DIAGNOSTICS: Mapping[str, Diagnostic] = MappingProxyType({d.code: d for d in _ROWS})  # 読み取り専用


def lookup(code: str) -> Diagnostic | None:
    return DIAGNOSTICS.get(code)


def codes(adapter: str | None = None) -> list[str]:
    """コードの一覧（アルファベット順）。adapter は "terraform" か "cloudformation"。"""
    return [c for c, d in DIAGNOSTICS.items() if adapter is None or d.adapter == adapter]
