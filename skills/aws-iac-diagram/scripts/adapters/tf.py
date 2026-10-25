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
    組み込み関数（lib/tf_eval.py）を評価する。count・for_each が決まればインスタンスごとに出し（address の
    [0]・["key"]、0 個なら enabled: false で添字なし）、決まらなければ ×N（[*]、enabled: null）
  - 参照を印にする: resource・data・module への参照は $res（attr は最初の属性名。インスタンスへの参照と
    スプラットはインスタンスごと）、data.aws_region・aws_caller_identity・aws_partition は $pseudo、
    data.aws_availability_zones の names は $az、jsonencode(...) は $json、"${…}" と heredoc は $concat
    （JSON として読めれば $json）。depends_on は references にだけ
  - 評価できなかった値は $unknown（中の参照は state: "unevaluated"）。条件式の選ばれなかった側、try で使わな
    かった式、選ぶ関数（coalesce・element など）とリストの添字で選ばなかった要素、for 式の if で除いた要素の中の
    参照は state: "pruned"（決まった count・for_each の式の参照は残さない。ir-schema.md の 7.2）
  - path.module・path.root・path.cwd はルートからの相対パス（ルートは "."）、terraform.workspace は "default"
  - provider = aws.<alias> のリソースは provider を書く。region は、リソースの引数 region（AWS provider v6）→
    その provider の region の順で、文字列で決まるときだけ書く
  - heredoc の開始・終端の行の末尾の空白を取ってから読む（python-hcl2 が読めないため。7.4。診断 info）
  - モジュール（手順3。ir-schema.md の 7.2 の「TF のモジュール」）: ローカルモジュール（./・../）は再帰的に
    展開する（address は module.x.…、count・for_each の呼び出しはインスタンスごと）。子の変数は呼び出しの引数を
    親の中で評価した値、module.x.y は子の出力 y の値で、たどった経路を参照の through に書く。terraform-aws-modules
    の vpc・alb・rds・eks は A5 の要約表（references/module-summaries.md、lib/tf_modules.py）で展開する
    （via: module_summary）。それ以外のレジストリ・git などのソースと、読めない・循環する・深すぎるものは黒箱の
    呼び出し1件（type: module、via: module_blackbox）。providers 引数で渡した provider をたどって provider・region
    を書く。terraform_remote_state の出力への参照は attr: "outputs.<名前>"（state は読まない）
  - plan JSON（手順4。lib/tf_plan.py、ir-schema.md の 7.2「TF の plan JSON」と 7.3「plan JSON の参照」）:
    --input に plan JSON（terraform show -json の出力の .json）を渡すと、plan JSON だけから作る（file は plan JSON
    の名前）。--input にフォルダ、--plan に plan JSON を渡すと、変数の値は plan の variables を使い、address と
    作られるかは plan、file・props・参照の位置は .tf にする（.tf で決まらなかった値は plan の値で埋める）。
    plan の sensitive の値は使わない。.tf.json のブロックは、plan と一緒なら plan から取る
後の手順に回したもの:
  - 手順5: .tf.json を .tf だけで読むか（いまは TF-TFJSON-UNSUPPORTED）
file()・templatefile() などのファイルを読む関数は、ファイルを読まずに $unknown（診断 TF-UNEVALUATED）。
引数の中の参照は unevaluated で残す。sensitive = true・ephemeral = true の変数と sensitive() の値は使わない
（$unknown。evaluation.vars にも書かない）。

使い方:
  uv run scripts/adapters/tf.py --input <ルートモジュールのフォルダ> --out <raw.json> [--root-base <フォルダ>]
      [--var-file <ファイル> ...] [--var KEY=VALUE ...] [--redact-var <名前> ...] [--plan <plan JSON>]
  uv run scripts/adapters/tf.py --input <plan JSON> --out <raw.json> [--root-base <フォルダ>]
  --plan: 同じ構成の plan JSON（terraform show -json <plan> の出力）。--input のフォルダの .tf と合わせて読む
  --root-base: raw IR の root を、このフォルダからの相対パスで書く（既定: 作業中のフォルダ）
  --var-file: 変数の値のファイル（.tfvars か .tfvars.json）。相対パスは作業中のフォルダ、無ければ --input から
  --var: 変数の値。type が list・map・object などの変数は HCL の式として読む（Terraform の -var と同じ）
  --var-file と --var は、指定した順に後のものが優先する（Terraform と同じ）
  --redact-var: 値を伏せる変数（sensitive = true と同じく値を使わず、props では $unknown）。
    sensitive を付けていない変数の値は props（図のラベルなど）に入りうる。evaluation.vars には値を書かない

終了コード: 0 = 書けた（diagnostics に warn・error があっても）、2 = フォルダや変数のファイル・plan JSON を読めなかった
（plan JSON でない .json、state の JSON、plan JSON だけのときの --var-file・--var・--redact-var も 2）
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path

import hcl2
from lark import Token, Tree

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import ir_raw  # noqa: E402
from lib import tf_eval as E  # noqa: E402
from lib import tf_modules as M  # noqa: E402
from lib import tf_plan as P  # noqa: E402
from lib.tf_eval import Az, Concat, EvalError, Json, Pseudo, Res, Unknown, ZeroColl  # noqa: E402

# 読み飛ばす記号の字句（構文木の中で意味を持たないもの）
SKIP_TOKENS = {"LPAR", "RPAR", "LBRACE", "RBRACE", "LSQB", "RSQB", "COMMA", "DOT", "EQ", "COLON", "DBLQUOTE",
               "INTERP_START", "QMARK", "COLONS", "NL_OR_COMMENT"}
TRAVERSAL = {"index_expr_term", "get_attr_expr_term", "attr_splat_expr_term", "full_splat_expr_term"}
HEREDOC = {"heredoc_template", "heredoc_template_trim"}
# ブロックの最上位のメタ引数（props に入れない）
RESOURCE_META = {"count", "for_each", "provider", "depends_on", "lifecycle", "provisioner", "connection"}
DATA_META = {"count", "for_each", "provider", "depends_on", "lifecycle"}
MODULE_META = {"source", "version", "count", "for_each", "providers", "depends_on"}
# data.<型>.<名前>.<属性> → 擬似パラメータ（7.2。CFN と同じ名前）。引数の無い data だけ
PSEUDO_DATA = {
    ("aws_region", "name"): "AWS::Region", ("aws_region", "region"): "AWS::Region", ("aws_region", "id"): "AWS::Region",
    ("aws_caller_identity", "account_id"): "AWS::AccountId",
    ("aws_partition", "partition"): "AWS::Partition", ("aws_partition", "id"): "AWS::Partition",
    ("aws_partition", "dns_suffix"): "AWS::URLSuffix",
}
NOTCONST = object()
OPEN_HEREDOC = re.compile(r"<<-?([A-Za-z][A-Za-z0-9._-]*)([ \t]+)?$")
ESCAPE = re.compile(r"\\(u[0-9a-fA-F]{4}|U[0-9a-fA-F]{8}|.)", re.S)
SIMPLE_ESCAPES = {"n": "\n", "r": "\r", "t": "\t", '"': '"', "\\": "\\"}
CLOSERS = {"else", "endif", "endfor"}
# 作られないブロックの中で info に下げる code（値が決まらないことによるもの。参照の誤り・循環は下げない）
UNDECIDED = {"TF-UNRESOLVED-VAR", "TF-EVAL-ERROR", "TF-UNEVALUATED", "TF-UNSUPPORTED-FUNCTION"}
# 引数や要素から選ぶ関数（選ばなかったものの中の参照を pruned にする。CFN の Fn::Select と同じ）
SELECTING = {"coalesce", "coalescelist", "element", "slice", "one"}
COMPLEX_TYPES = {"list", "set", "map", "object", "tuple"}
# モジュールの入れ子の深さの上限（これより深い呼び出しは黒箱。TF-MODULE-DEPTH）
MAX_MODULE_DEPTH = 16
# count が 0・決まらないモジュールの呼び出しのインスタンスのキー（ModuleEval.child）
ZERO, STAR = "\u0000zero", "\u0000star"


def weakest(a, b):
    """enabled の弱い方（false > null > true）。モジュールの中のリソースは、呼び出しの値を引き継ぐ。"""
    if a is False or b is False:
        return False
    if a is None or b is None:
        return None
    return True


def ref_order(r: tuple) -> tuple:
    """参照 (to, attr, through) の並べ方。"""
    return (r[0], r[1] or "", r[2])


def through_refs(refs, hop: str) -> set:
    return {(to, attr, (hop,) + th) for to, attr, th in refs}


class ModObj:
    """展開したモジュールの呼び出しのインスタンス1つ（module.x、module.x[0]）。属性で引くと、子の出力の値。"""

    __slots__ = ("child",)

    def __init__(self, child: "ModuleEval"):
        self.child = child


def prepend_through(v, hop: str):
    """値の中の参照に、モジュールの出力・変数をたどった経路（hop）を先頭に足す（7.3 の through）。"""
    if isinstance(v, Res):
        return replace(v, through=(hop,) + v.through)
    if isinstance(v, Unknown):
        return Unknown(v.reason, v.code, v.level, through_refs(v.refs, hop))
    if isinstance(v, Concat):
        return Concat(tuple(prepend_through(p, hop) for p in v.parts))
    if isinstance(v, Json):
        return Json(prepend_through(v.value, hop))
    if isinstance(v, ZeroColl):
        return ZeroColl(prepend_through(v.res, hop))
    if isinstance(v, list):
        return type(v)(prepend_through(e, hop) for e in v)
    if isinstance(v, dict):
        return type(v)((k, prepend_through(e, hop)) for k, e in v.items())
    return v


# ------------------------------------------------------------------ 構文木の小さな道具

def sig(t: Tree) -> list:
    """意味のある子（改行・コメントと記号の字句を除いたもの）。"""
    out = []
    for c in t.children:
        if isinstance(c, Tree):
            if c.data != "new_line_or_comment":
                out.append(c)
        elif isinstance(c, Token) and c.type not in SKIP_TOKENS:
            out.append(c)
    return out


def unwrap(t):
    """expr_term と括弧を外す。"""
    while isinstance(t, Tree) and t.data == "expr_term":
        cs = sig(t)
        if len(cs) != 1:
            break
        t = cs[0]
    return t


def name_of(t) -> str:
    """identifier・keyword・literal_value の名前。"""
    if isinstance(t, Token):
        return str(t)
    return str(sig(t)[0])


def _unescape(s: str) -> str:
    def repl(m):
        e = m.group(1)
        if e[0] in "uU" and len(e) > 1:
            return chr(int(e[1:], 16))
        return SIMPLE_ESCAPES.get(e, "\\" + e)
    return ESCAPE.sub(repl, s)


def label_text(t) -> str:
    """ブロックのラベル（"aws_vpc" や識別子のまま書いたもの）。"""
    t = unwrap(t)
    if isinstance(t, Tree) and t.data == "string":
        v = const(t)
        return v if isinstance(v, str) else ""
    return name_of(t)


def flatten(t):
    """参照の式を (根, 手順の一覧) にする。手順は ("attr", 名前)・("index", 式か整数)・("splat", [手順])。"""
    t = unwrap(t)
    if isinstance(t, Tree) and t.data in TRAVERSAL:
        cs = sig(t)
        root, steps = flatten(cs[0])
        return root, steps + [_step(cs[1])]
    return t, []


def _step(op: Tree):
    if op.data == "get_attr":
        return ("attr", name_of(sig(op)[0]))
    if op.data == "braces_index":
        return ("index", sig(op)[0])
    if op.data == "short_index":
        return ("index", int(str(sig(op)[0])))
    return ("splat", [_step(c) for c in sig(op) if isinstance(c, Tree)])  # attr_splat・full_splat


def const(t):
    """定数の式（数・真偽値・null・式を含まない文字列・それらのリスト）の値。定数でなければ NOTCONST。"""
    t = unwrap(t)
    if not isinstance(t, Tree):
        return NOTCONST
    d = t.data
    if d == "int_lit":
        return int(str(sig(t)[0]))
    if d == "float_lit":
        return float(str(sig(t)[0]))
    if d == "literal_value":
        return {"true": True, "false": False, "null": None}[str(sig(t)[0])]
    if d == "string":
        out = []
        for part in t.children:
            if not (isinstance(part, Tree) and part.data == "string_part"):
                continue
            for c in part.children:
                if isinstance(c, Token) and c.type == "STRING_CHARS":
                    out.append(_unescape(str(c)))
                elif isinstance(c, Token) and c.type in ("ESCAPED_INTERPOLATION", "ESCAPED_DIRECTIVE"):
                    out.append(str(c)[1:])
                else:
                    return NOTCONST
        return "".join(out)
    if d == "unary_op":
        op, operand = str(t.children[0]).strip(), const(t.children[-1])
        if op == "-" and E.is_number(operand):
            return -operand
        if op == "!" and isinstance(operand, bool):
            return not operand
        return NOTCONST
    if d == "tuple":
        vals = [const(c) for c in sig(t)]
        return NOTCONST if any(v is NOTCONST for v in vals) else vals
    return NOTCONST


def identifier_name(t) -> str | None:
    """括弧の無い識別子1つだけの式なら、その名前。"""
    if isinstance(t, Tree) and t.data == "expr_term" and any(
            isinstance(c, Token) and c.type == "LPAR" for c in t.children):
        return None
    u = unwrap(t)
    if isinstance(u, Tree) and u.data == "identifier":
        return name_of(u)
    return None


# ------------------------------------------------------------------ heredoc とテンプレート

def fix_heredocs(text: str) -> tuple[str, int]:
    """heredoc の開始（<<EOF）と終端（EOF）の行の末尾の空白を取る。python-hcl2 8.1.4 は空白があると読めない（7.4）。"""
    lines = text.split("\n")
    fixed = 0
    i = 0
    while i < len(lines):
        line = lines[i]
        cr = "\r" if line.endswith("\r") else ""
        m = OPEN_HEREDOC.search(line[:len(line) - len(cr)])
        # コメントの中の <<EOF（# や // の後ろ）は開始として扱わない
        if not m or "#" in line[:m.start()] or "//" in line[:m.start()]:
            i += 1
            continue
        marker = m.group(1)
        j = i + 1
        while j < len(lines):
            body = lines[j][:-1] if lines[j].endswith("\r") else lines[j]
            if body.strip() == marker:
                break
            j += 1
        if j >= len(lines):  # 終端が無い。開始ではなかったものとして、次の行から調べ直す
            i += 1
            continue
        if m.group(2):
            lines[i] = line[:len(line) - len(cr)].rstrip(" \t") + cr
            fixed += 1
        body = lines[j][:-1] if lines[j].endswith("\r") else lines[j]
        if body != body.rstrip(" \t"):
            lines[j] = body.rstrip(" \t") + ("\r" if lines[j].endswith("\r") else "")
            fixed += 1
        i = j + 1
    return "\n".join(lines), fixed


def heredoc_body(token: str) -> str:
    """heredoc の字句から中身を取り出す（<<- は共通の字下げを除く）。"""
    text = token.replace("\r\n", "\n")
    m = re.match(r"<<(-?)([A-Za-z][A-Za-z0-9._-]*)\n", text)
    if not m:
        return ""
    lines = text[m.end():].split("\n")[:-2]  # 終端の行と、最後の改行の後ろの空文字を除く
    if m.group(1) == "-":
        indents = [len(x) - len(x.lstrip(" \t")) for x in lines if x.strip()]
        cut = min(indents) if indents else 0
        lines = [x[cut:] for x in lines]
    return "\n".join(lines) + "\n" if lines else ""


def _close_brace(text: str, i: int) -> int:
    depth = 1
    while i < len(text):
        c = text[i]
        if c == '"':
            i += 1
            while i < len(text) and text[i] != '"':
                i += 2 if text[i] == "\\" else 1
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


_EXPR_CACHE: dict[str, Tree | None] = {}


def parse_expr(src: str) -> Tree | None:
    """式の文字列（テンプレートの ${…} の中、--var の値）を読む。読めなければ None。"""
    if src not in _EXPR_CACHE:
        try:
            tree = hcl2.parses_to_tree(f"__x = {src}\n")
            attr = sig(sig(tree)[0])[0]
            _EXPR_CACHE[src] = sig(attr)[-1]
        except Exception:  # noqa: BLE001  python-hcl2 は lark の例外をそのまま投げる
            _EXPR_CACHE[src] = None
    return _EXPR_CACHE[src]


DIRECTIVE_FOR = re.compile(r"for\s+([A-Za-z_][A-Za-z0-9_-]*)\s*(?:,\s*([A-Za-z_][A-Za-z0-9_-]*)\s*)?\s+in\s+(.*)$",
                           re.S)


def text_tokens(text: str) -> list:
    """heredoc の中身を字句に分ける。字句は文字列か、("expr", 木, sl, sr)・("if", 木, sl, sr)・("else", sl, sr)・
    ("endif", sl, sr)・("for", [変数], 木, sl, sr)・("endfor", sl, sr)・("bad",)。sl・sr は ~（空白を取る）。"""
    tokens: list = []
    buf: list[str] = []
    i = 0
    while i < len(text):
        if text.startswith(("$${", "%%{"), i):
            buf.append(text[i + 1:i + 3])
            i += 3
            continue
        if text.startswith(("${", "%{"), i):
            j = _close_brace(text, i + 2)
            if j < 0:
                buf.append(text[i:])
                break
            inner = text[i + 2:j]
            sl, sr = inner.startswith("~"), len(inner) > 1 and inner.endswith("~")
            inner = inner[1 if sl else 0:len(inner) - (1 if sr else 0)].strip()
            if buf:
                tokens.append("".join(buf))
                buf = []
            if text[i] == "$":
                tokens.append(("expr", parse_expr(inner), sl, sr))
            elif inner.startswith("if ") or inner.startswith("if\t"):
                tokens.append(("if", parse_expr(inner[3:]), sl, sr))
            elif inner in ("else", "endif", "endfor"):
                tokens.append((inner, sl, sr))
            elif (m := DIRECTIVE_FOR.match(inner)) is not None:
                names = [m.group(1)] + ([m.group(2)] if m.group(2) else [])
                tokens.append(("for", names, parse_expr(m.group(3)), sl, sr))
            else:
                tokens.append(("bad",))
            i = j + 1
            continue
        buf.append(text[i])
        i += 1
    if buf:
        tokens.append("".join(buf))
    return tokens


def _strip_flags(t: Tree, keyword: str) -> tuple[bool, bool]:
    """クォートした文字列の中の %{…} の ~ が、キーワードの前（sl）か後（sr）にあるか。"""
    seen_kw = False
    sl = sr = False
    for c in t.children:
        if isinstance(c, Token):
            if c.type == "STRIP_MARKER":
                if seen_kw:
                    sr = True
                else:
                    sl = True
            elif str(c) == keyword:
                seen_kw = True
    return sl, sr


def string_tokens(t: Tree) -> list:
    """クォートした文字列を字句に分ける（text_tokens と同じ形）。"""
    tokens: list = []
    for part in t.children:
        if not (isinstance(part, Tree) and part.data == "string_part"):
            continue
        for c in part.children:
            if isinstance(c, Token):
                if c.type == "STRING_CHARS":
                    tokens.append(_unescape(str(c)))
                else:  # ESCAPED_INTERPOLATION（$${）・ESCAPED_DIRECTIVE（%%{）
                    tokens.append(str(c)[1:])
            elif c.data == "interpolation":
                tokens.append(("expr", sig(c)[0], False, False))
            elif c.data == "template_if_start":
                expr = next(x for x in c.children if isinstance(x, Tree))
                tokens.append(("if", expr, *_strip_flags(c, "if")))
            elif c.data == "template_for_start":
                trees = [x for x in c.children if isinstance(x, Tree)]
                names = [name_of(x) for x in trees if x.data == "identifier"]
                expr = next(x for x in trees if x.data != "identifier")
                tokens.append(("for", names, expr, *_strip_flags(c, "for")))
            else:
                kw = {"template_else": "else", "template_endif": "endif", "template_endfor": "endfor"}.get(c.data)
                tokens.append((kw, *_strip_flags(c, kw)) if kw else ("bad",))
    return tokens


def apply_strip(tokens: list) -> list:
    """~ の付いた字句の前後の文字列から、空白（改行を含む）を取る。"""
    out = list(tokens)
    for i, tok in enumerate(out):
        if isinstance(tok, str) or tok[0] == "bad":
            continue
        sl, sr = tok[-2], tok[-1]
        if sl and i > 0 and isinstance(out[i - 1], str):
            out[i - 1] = out[i - 1].rstrip(" \t\r\n")
        if sr and i + 1 < len(out) and isinstance(out[i + 1], str):
            out[i + 1] = out[i + 1].lstrip(" \t\r\n")
    return out


def build_template(tokens: list) -> list:
    """字句を入れ子の形にする。節は文字列・("expr", 木)・("if", 木, [then], [else])・("for", [変数], 木, [本体])。
    形が崩れていれば ValueError。"""
    pos = 0

    def parse() -> list:
        nonlocal pos
        out: list = []
        while pos < len(tokens):
            tok = tokens[pos]
            if isinstance(tok, str):
                out.append(tok)
                pos += 1
                continue
            kind = tok[0]
            if kind in CLOSERS:
                return out
            pos += 1
            if kind == "expr":
                out.append(("expr", tok[1]))
            elif kind == "if":
                then = parse()
                els: list = []
                if pos < len(tokens) and not isinstance(tokens[pos], str) and tokens[pos][0] == "else":
                    pos += 1
                    els = parse()
                if pos >= len(tokens) or isinstance(tokens[pos], str) or tokens[pos][0] != "endif":
                    raise ValueError("%{if} without %{endif}")
                pos += 1
                out.append(("if", tok[1], then, els))
            elif kind == "for":
                body = parse()
                if pos >= len(tokens) or isinstance(tokens[pos], str) or tokens[pos][0] != "endfor":
                    raise ValueError("%{for} without %{endfor}")
                pos += 1
                out.append(("for", tok[1], tok[2], body))
            else:
                raise ValueError("a template directive cannot be parsed")
        return out

    nodes = parse()
    if pos != len(tokens):
        raise ValueError(f"unexpected %{{{tokens[pos][0]}}}")
    return nodes


def token_trees(tokens: list) -> list:
    return [t for tok in tokens if not isinstance(tok, str) for t in tok if isinstance(t, Tree)]


# ------------------------------------------------------------------ ブロック

@dataclass
class Block:
    kind: str  # resource／data／module／ephemeral
    type: str  # module のときは "module"
    name: str
    file: str
    body: Tree
    attrs: dict = field(default_factory=dict)  # 最上位の属性 → 式の木

    @property
    def base(self) -> str:
        if self.kind == "data":
            return f"data.{self.type}.{self.name}"
        if self.kind == "module":
            return f"module.{self.name}"
        if self.kind == "ephemeral":
            return f"ephemeral.{self.type}.{self.name}"
        return f"{self.type}.{self.name}"

    @property
    def plain(self) -> bool:
        """引数の無い data（data.aws_region.current など）。擬似パラメータとして扱えるもの。"""
        return set(self.attrs) <= {"depends_on"} and not any(
            isinstance(c, Tree) and c.data == "block" for c in sig(self.body))


@dataclass
class Instances:
    """count・for_each を評価した結果。mode は single／count／each／zero／unknown。"""
    mode: str
    meta: str = ""  # "count"・"for_each"（single では空）
    keys: list = field(default_factory=list)  # count は番号、for_each はキー
    values: dict = field(default_factory=dict)  # for_each のキー → each.value
    unknown: Unknown | None = None  # mode が unknown のときの値


class ResList(list):
    """count のリソースのまとまり（インスタンスごとの Res のリスト）。添字で引いても他のインスタンスを pruned にしない。"""


class ResMap(dict):
    """for_each のリソースのまとまり（キー → Res）。"""


INSTANCE_KEY = re.compile(r'\[(?:\d+|\*|"(?:[^"\\]|\\.)*")\]$')


def block_address(address: str) -> str:
    """インスタンスの添字（[0]・["key"]・[*]）を除いたブロックの address。"""
    return INSTANCE_KEY.sub("", address)


def inst_address(base: str, key) -> str:
    if isinstance(key, int):
        return f"{base}[{key}]"
    return f"{base}[{json.dumps(key, ensure_ascii=False)}]"


class Context:
    """1回の読み込み全体で共有するもの（リソースと参照の集まり、診断、前提）。"""

    def __init__(self, root_dir: Path):
        self.root_dir = root_dir
        self.diagnostics: list[dict] = []
        self.resources: list[dict] = []
        self.refs: list[dict] = []
        self.assumptions: list[str] = []
        self.modules: list["ModuleEval"] = []  # 展開したモジュール（evaluation.vars を書くため）

    def rel(self, path: Path) -> str:
        # 両方を resolve してから比べる（Windows の 8.3 の短い名前 `RUNNER~1` と実際の名前が混ざると、`../..` だらけになる）
        try:
            return Path(os.path.relpath(Path(path).resolve(), Path(self.root_dir).resolve())).as_posix()
        except ValueError:  # Windows でドライブが違う
            return Path(path).resolve().as_posix()

    def assume(self, text: str) -> None:
        if text not in self.assumptions:
            self.assumptions.append(text)


class ModuleEval:
    """1つのモジュール（ルートモジュールか、モジュールの呼び出しのインスタンス1つ）のブロックを集めて評価する。

    子のモジュール（ローカルのモジュールと、A5 の要約表から作るもの）は、呼び出しのインスタンスごとに1つ作る。
    子の変数は呼び出しの引数を親の中で評価した値、親から見た module.x.y は子の出力 y の値（どちらも through に
    経路を足す。7.3）。
    """

    def __init__(self, ctx: Context, directory: Path | None, prefix: str = ""):
        self.ctx = ctx
        self.dir = directory  # 要約表から作るモジュールは None
        self.prefix = prefix  # address の前に付けるもの（モジュールの中は "module.x."）
        # 子のモジュールのとき（ルートは parent が None）
        self.parent: ModuleEval | None = None
        self.call_address = ""  # 呼び出しのインスタンスの address（module.x、module.x[0]）
        self.call_args: dict[str, Tree] = {}  # 引数の名前 → 親の中の式
        self.call_env: dict = {}  # 引数を評価するときの count.index・each（親の側）
        self.via: str | None = None  # 要約表から作るときは "module_summary"
        self.summary: M.Summary | None = None
        self.file_override: str | None = None  # 要約表のブロックの file（呼び出しのあるファイル）
        self.enabled_base = True  # 呼び出しの enabled（count が 0 なら false、決まらなければ null）
        self.multi = False  # 呼び出しが ×N（count・for_each が決まらない）
        self.chain: tuple = ()  # 呼び出しの経路のフォルダ・要約表（循環の検出）
        self.depth = 0
        self.provider_map: dict[str, str] = {}  # 子の provider の名前 → 親の provider の名前（providers 引数）
        self.explicit_providers = False  # providers 引数があるか（無ければ既定の provider を引き継ぐ）
        self.depends_from: list = []  # 呼び出しの depends_on（(書かれたモジュール, 式) の並び）
        self.outputs: dict[str, Tree] = {}  # output ブロックの本体
        self._children: dict = {}
        self._plans: dict = {}
        self._var_cache: dict = {}
        self._out_cache: dict = {}
        self._dep_cache: list | None = None
        self._uncovered: list = []  # 要約表に写していない、渡された最上位の入力
        self.blocks: dict[str, Block] = {}  # base（prefix を除いたもの）→ ブロック
        self.ephemerals: dict[str, Block] = {}
        self.locals: dict[str, Tree] = {}
        self.variables: dict[str, Tree] = {}  # 変数の名前 → variable ブロックの本体
        self.var_values: dict[str, object] = {}
        self.var_sources: dict[str, dict] = {}  # evaluation.vars に書くもの（値の出どころ。値は書かない）
        self.redact: set = set()  # --redact-var で伏せる変数の名前
        self.var_files: list[str] = []
        self.providers: dict[str, Tree] = {}  # "aws"・"aws.us_east_1" → provider ブロックの本体
        self.current = ""  # いま評価しているリソースの address
        self.current_enabled = True  # いま評価しているリソースの enabled
        self.extra_refs: list[dict] = []  # unevaluated・pruned の参照
        self.sink: set = set()  # いま評価している属性で、値に残らなかった参照（pruned）
        self.const_mode = False  # tfvars・--var の値を読むとき（参照を使えない）
        self.try_depth = 0  # try()・can() の中を評価しているとき 1 以上
        self._local_cache: dict[str, tuple] = {}
        self._inst_cache: dict[str, Instances] = {}
        self._busy: set = set()

    # --- 診断と参照
    def diag(self, level: str, code: str, path: str, message: str, address: str | None = None) -> None:
        self.ctx.diagnostics.append({"level": level, "code": code,
                                     "address": self.current if address is None else address,
                                     "path": path, "message": message})

    def add_ref(self, path: str, to: str, attr, state: str, through=()) -> None:
        ref = {"from": self.current, "path": path, "to": to, "attr": attr, "fn": "ref", "state": state}
        if through:
            ref["through"] = list(through)
        self.extra_refs.append(ref)

    # --- 読み込み
    def load(self) -> None:
        if self.summary is not None:  # 要約表（references/module-summaries.md）の HCL
            self.collect(summary_tree(self.summary), self.file_override)
            return
        if not self.dir.is_dir():
            raise ValueError(f"フォルダではありません: {self.dir}")
        for f in sorted(self.dir.glob("*.tf.json")):
            self.diag("warn", "TF-TFJSON-UNSUPPORTED", "", f"{self.ctx.rel(f)}: .tf.json is not read yet", "")
        # Terraform が読まないファイル（. で始まるもの、エディタの一時ファイル #…#・…~）は読まない
        files = sorted(p for p in self.dir.iterdir() if p.is_file() and p.suffix == ".tf"
                       and not p.name.startswith((".", "#")) and not p.name.endswith("~"))
        if not files:
            raise ValueError(f".tf がありません: {self.dir}")
        overrides = []
        for f in files:
            tree = self.read_tf(f)
            if tree is None:
                continue
            if f.stem == "override" or f.stem.endswith("_override"):
                overrides.append((tree, self.ctx.rel(f)))
            else:
                self.collect(tree, self.ctx.rel(f))
        for tree, rel in overrides:  # override のファイルは、ほかのファイルをすべて読んでから重ねる（名前順）
            self.collect(tree, rel, override=True)

    def read_tf(self, f: Path) -> Tree | None:
        rel = self.ctx.rel(f)
        try:
            text = f.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError) as e:
            self.diag("error", "TF-PARSE-ERROR", "", f"{rel}: {type(e).__name__}: {e}", "")
            return None
        text, fixed = fix_heredocs(text)
        if fixed:
            self.diag("info", "TF-HEREDOC-TRAILING-SPACE", "",
                      f"{rel}: removed trailing spaces on {fixed} heredoc marker line(s) before parsing", "")
        try:
            return hcl2.parses_to_tree(text)
        except Exception as e:  # noqa: BLE001  lark の例外（UnexpectedToken など）
            first = str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__
            self.diag("error", "TF-PARSE-ERROR", "", f"{rel}: {type(e).__name__}: {first}", "")
            return None

    @staticmethod
    def body_attrs(b: Tree) -> dict:
        return {name_of(sig(a)[0]): sig(a)[-1] for a in sig(b) if isinstance(a, Tree) and a.data == "attribute"}

    def collect(self, tree: Tree, rel: str, override: bool = False) -> None:
        body = sig(tree)[0]
        for item in sig(body):
            if not (isinstance(item, Tree) and item.data == "block"):
                continue
            cs = sig(item)
            btype = name_of(cs[0])
            labels = [label_text(x) for x in cs[1:-1]]
            b = cs[-1]
            attrs = self.body_attrs(b)
            if btype == "check":
                # check ブロックの中の data（scoped data source）。assert は読まない
                for inner in sig(b):
                    if isinstance(inner, Tree) and inner.data == "block":
                        ics = sig(inner)
                        if name_of(ics[0]) == "data" and len(ics) == 4:
                            self.add_block(Block("data", label_text(ics[1]), label_text(ics[2]), rel, ics[-1],
                                                 self.body_attrs(ics[-1])), rel, override)
                continue
            if btype in ("resource", "data", "ephemeral") and len(labels) == 2:
                self.add_block(Block(btype, labels[0], labels[1], rel, b, attrs), rel, override)
            elif btype == "module" and len(labels) == 1:
                self.add_block(Block("module", "module", labels[0], rel, b, attrs), rel, override)
            elif btype == "locals":
                for name, expr in attrs.items():
                    if name in self.locals and not override:
                        self.diag("warn", "TF-DUPLICATE-BLOCK", "", f"{rel}: local.{name} is defined twice", "")
                    self.locals[name] = expr
            elif btype == "variable" and len(labels) == 1:
                name = labels[0]
                if override and name in self.variables:
                    self.variables[name] = merge_body(self.variables[name], b)
                elif name in self.variables:
                    self.diag("warn", "TF-DUPLICATE-BLOCK", "", f"{rel}: variable {name} is defined twice", "")
                else:
                    self.variables[name] = b
            elif btype == "provider" and len(labels) == 1:
                alias = const(attrs["alias"]) if "alias" in attrs else None
                key = labels[0] + (f".{alias}" if isinstance(alias, str) else "")
                if override and key in self.providers:
                    self.providers[key] = merge_body(self.providers[key], b)
                else:
                    self.providers[key] = b
            elif btype == "output" and len(labels) == 1:
                name = labels[0]
                if override and name in self.outputs:
                    self.outputs[name] = merge_body(self.outputs[name], b)
                elif name in self.outputs:
                    self.diag("warn", "TF-DUPLICATE-BLOCK", "", f"{rel}: output {name} is defined twice", "")
                else:
                    self.outputs[name] = b
            # terraform・moved・import・removed などは使わない

    def add_block(self, blk: Block, rel: str, override: bool) -> None:
        table = self.ephemerals if blk.kind == "ephemeral" else self.blocks
        if override:
            old = table.get(blk.base)
            if old is None:
                self.diag("warn", "TF-OVERRIDE-UNMATCHED", "", f"{rel}: {blk.base} is not defined in other files", "")
                return
            body = merge_body(old.body, blk.body)
            table[blk.base] = Block(old.kind, old.type, old.name, old.file, body, self.body_attrs(body))
            self.ctx.assume(f"override file {rel} is merged into {blk.base}")
            return
        if blk.base in table:
            self.diag("warn", "TF-DUPLICATE-BLOCK", "", f"{rel}: {blk.base} is defined twice; the first one is used",
                      "")
            return
        table[blk.base] = blk

    # --- 変数
    def setup_variables(self, sources: list, redact=()) -> None:
        """変数の値を決める。sources は Terraform の読み順に並べた ("file", Path) と ("var", "K=V")。

        redact: 値を伏せる変数の名前（--redact-var）。sensitive = true と同じく、値を使わない。
        """
        given: dict = {}
        origin: dict = {}  # 変数の名前 → 値を取ったところ（変数のファイルの名前か "--var"）
        self.redact = set(redact)
        for name in sorted(self.redact - set(self.variables)):
            self.diag("warn", "TF-VAR-UNDECLARED", "", f"--redact-var: variable {name} is not declared", "")
        for kind, item in sources:
            if kind == "file":
                shown = self.var_file_name(item)
                self.var_files.append(shown)
                for name, value in self.read_var_file(item, shown).items():
                    if name not in self.variables:
                        self.diag("warn", "TF-VAR-UNDECLARED", "", f"{shown}: variable {name} is not declared", "")
                        continue
                    given[name], origin[name] = value, shown
            elif kind in ("value", "plan"):  # build_raw の vars と、plan JSON の variables（値をそのまま渡す）
                name, value = item
                if name not in self.variables:
                    self.diag("warn", "TF-VAR-UNDECLARED", "", f"variable {name} is not declared", "")
                    continue
                given[name], origin[name] = value, "--var" if kind == "value" else "plan"
            else:
                name, text = item.split("=", 1)
                name = name.strip()
                if name not in self.variables:
                    self.diag("warn", "TF-VAR-UNDECLARED", "", f"--var: variable {name} is not declared", "")
                    continue
                value = self.parse_cli_var(name, text)
                if value is not NOTCONST:
                    given[name], origin[name] = value, "--var"
        for name, body in sorted(self.variables.items()):
            attrs = self.body_attrs(body)
            spec = self.parse_type(attrs["type"]) if "type" in attrs else None
            secret = next((k for k in ("sensitive", "ephemeral") if k in attrs and const(attrs[k]) is True), None)
            if secret is None and name in self.redact:
                secret = "redact-var"
            nullable = const(attrs["nullable"]) if "nullable" in attrs else True
            value = given.get(name, NOTCONST)
            source = origin.get(name)
            if (value is NOTCONST or (value is None and nullable is False)) and "default" in attrs:
                value = self.eval_const(attrs["default"])
                source = "default"
                if value is NOTCONST:
                    source = None
                    self.diag("warn", "TF-VAR-INVALID", "", f"variable {name}: default is not a constant value", "")
            entry: dict = {"source": source if value is not NOTCONST else None}
            if secret:
                entry["hidden"] = secret
            self.var_sources[name] = entry
            if secret:  # 秘密の値として扱うと書かれた（または --redact-var で伏せた）変数の値は使わない（IR に書かない）
                why = "redacted by --redact-var" if secret == "redact-var" else secret
                self.var_values[name] = Unknown(f"variable {name} is {why}; its value is not used",
                                                "TF-SENSITIVE-VAR", "info")
                continue
            if value is NOTCONST:
                self.var_values[name] = Unknown(f"variable {name} has no value", "TF-UNRESOLVED-VAR")
                continue
            self.var_values[name] = E.convert(value, spec)

    def var_file_name(self, path: Path) -> str:
        """evaluation.var_files に書く名前（root からの相対パス。別のドライブならファイル名だけ）。"""
        try:
            return Path(os.path.relpath(Path(path).resolve(), Path(self.ctx.root_dir).resolve())).as_posix()
        except ValueError:  # Windows でドライブが違う（絶対パスにはユーザー名などが入りうるので書かない）
            self.diag("info", "TF-VARFILE-OTHER-DRIVE", "",
                      f"{Path(path).name}: the var file is on another drive; only the file name is written", "")
            return Path(path).name

    def read_var_file(self, path: Path, rel: str) -> dict:
        if path.name.endswith(".json"):
            try:
                doc = json.loads(path.read_text(encoding="utf-8-sig"))
            except (OSError, UnicodeDecodeError, ValueError) as e:
                raise ValueError(f"変数のファイルを読めません: {path}: {e}") from e
            if not isinstance(doc, dict):
                raise ValueError(f"変数のファイルがオブジェクトではありません: {path}")
            return doc
        try:
            text = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError) as e:
            raise ValueError(f"変数のファイルを読めません: {path}: {e}") from e
        try:
            tree = hcl2.parses_to_tree(fix_heredocs(text)[0])
        except Exception as e:  # noqa: BLE001
            # lark の文には値の一部（字句）が入るので、位置だけを書く（秘密の値を出さない）
            where = f"line {e.line}, column {e.column}" if getattr(e, "line", None) else type(e).__name__
            raise ValueError(f"変数のファイルを読めません: {path}: 構文の誤り（{where}）") from e
        out = {}
        for name, expr in self.body_attrs(sig(tree)[0]).items():
            v = self.eval_const(expr)
            if v is NOTCONST:
                self.diag("warn", "TF-VAR-INVALID", "", f"{rel}: the value of {name} is not a constant value", "")
                continue
            out[name] = v
        return out

    def parse_cli_var(self, name: str, text: str):
        """--var の値。type が複合の型（list・map・object など）なら HCL の式として読む。"""
        attrs = self.body_attrs(self.variables[name])
        spec = self.parse_type(attrs["type"]) if "type" in attrs else None
        if spec is not None and spec[0] in COMPLEX_TYPES:
            tree = parse_expr(text)
            v = self.eval_const(tree) if tree is not None else NOTCONST
            if v is NOTCONST:
                self.diag("warn", "TF-VAR-INVALID", "", f"--var: the value of {name} is not a valid expression", "")
            return v
        return text

    def eval_const(self, expr):
        """参照を使わない式（tfvars、default）の値。決まらなければ NOTCONST。"""
        saved, self.const_mode = self.const_mode, True
        try:
            v = self.eval(expr, {})
        except EvalError:
            return NOTCONST
        finally:
            self.const_mode = saved
        return v if E.is_concrete(v) else NOTCONST

    def parse_type(self, t):
        """variable の type の式を、tf_eval.convert の形にする。読めなければ None（変換しない）。"""
        t = unwrap(t)
        if isinstance(t, Tree) and t.data == "identifier":
            n = name_of(t)
            return (n,) if n in ("string", "number", "bool", "any") else None
        if not (isinstance(t, Tree) and t.data == "function_call"):
            return None
        cs = sig(t)
        n = name_of(cs[0])
        args_t = next((c for c in cs if isinstance(c, Tree) and c.data == "arguments"), None)
        args = [c for c in sig(args_t) if isinstance(c, Tree)] if args_t is not None else []
        if n in ("list", "set", "map") and len(args) == 1:
            return (n, self.parse_type(args[0]))
        if n == "tuple" and len(args) == 1 and isinstance(unwrap(args[0]), Tree) and unwrap(args[0]).data == "tuple":
            return ("tuple", [self.parse_type(x) for x in sig(unwrap(args[0]))])
        if n == "object" and len(args) == 1 and isinstance(unwrap(args[0]), Tree) and unwrap(args[0]).data == "object":
            attrs = {}
            for el in sig(unwrap(args[0])):
                ecs = sig(el)
                key = self.object_key_name(ecs[0])
                if not isinstance(key, str):
                    return None
                at = unwrap(ecs[-1])
                if isinstance(at, Tree) and at.data == "function_call" and name_of(sig(at)[0]) == "optional":
                    oargs_t = next((c for c in sig(at) if isinstance(c, Tree) and c.data == "arguments"), None)
                    oargs = [c for c in sig(oargs_t) if isinstance(c, Tree)] if oargs_t is not None else []
                    default = self.eval_const(oargs[1]) if len(oargs) > 1 else E.NODEFAULT
                    if default is NOTCONST:
                        default = E.NODEFAULT
                    attrs[key] = (self.parse_type(oargs[0]) if oargs else None, True, default)
                else:
                    attrs[key] = (self.parse_type(at), False, E.NODEFAULT)
            return ("object", attrs)
        return None

    @staticmethod
    def object_key_name(t):
        c = sig(t)[0]
        if isinstance(c, Tree) and c.data == "keyword":
            return name_of(c)
        n = identifier_name(c)
        if n is not None:
            return n
        v = const(c)
        return v if isinstance(v, str) else NOTCONST

    def var_value(self, name):
        if name not in self.variables:
            return Unknown(f"reference to undefined var.{name}", "TF-UNDEFINED-REF")
        if self.parent is not None:
            return self.child_var(name)
        return self.var_values.get(name, Unknown(f"variable {name} has no value", "TF-UNRESOLVED-VAR"))

    # --- 子のモジュールの変数と出力
    def setup_child(self) -> None:
        """子のモジュールの、呼び出しの引数と変数の突き合わせ（値は使うときに評価する）。"""
        undeclared = sorted(set(self.call_args) - set(self.variables))
        if self.via == "module_summary":
            plain = {u for u in self.summary.uncovered if "." not in u}
            self._uncovered = sorted(set(undeclared) | (set(self.call_args) & plain))
            if self.parent is not None and self.parent.via is None:
                s = self.summary
                self.diag("info", "TF-MODULE-SUMMARY", "",
                          f"expanded from the summary table ({s.source}, {'/'.join(f'{m}.x' for m in s.majors)}; "
                          "references/module-summaries.md); only the main resources are written",
                          self.call_address)
            return
        for name in undeclared:
            self.diag("warn", "TF-VAR-UNDECLARED", name,
                      f"variable {name} is not declared in the module {self.call_address}", self.call_address)
        for name, body in sorted(self.variables.items()):
            attrs = self.body_attrs(body)
            entry: dict = {"source": "argument" if name in self.call_args else "default" if "default" in attrs
                           else None}
            secret = next((k for k in ("sensitive", "ephemeral") if k in attrs and const(attrs[k]) is True), None)
            if secret:
                entry["hidden"] = secret
            self.var_sources[name] = entry

    def child_var(self, name):
        """子のモジュールの変数の値。呼び出しの引数を親の中で評価し、type に合わせて変換する（through に var を足す）。"""
        if name in self._var_cache:
            v, pruned = self._var_cache[name]
            self.sink |= pruned
            return v
        key = ("var", name)
        if key in self._busy:
            return Unknown(f"var.{name} of {self.call_address} refers to itself", "TF-CYCLE")
        self._busy.add(key)
        try:
            attrs = self.body_attrs(self.variables[name])
            spec = self.parse_type(attrs["type"]) if "type" in attrs else None
            secret = next((k for k in ("sensitive", "ephemeral") if k in attrs and const(attrs[k]) is True), None)
            nullable = const(attrs["nullable"]) if "nullable" in attrs else True
            pruned: set = set()
            v = NOTCONST
            if name in self.call_args:
                p = self.parent
                saved, p.sink = p.sink, set()
                saved_try, p.try_depth = p.try_depth, 0
                try:
                    v = p.eval_safe(self.call_args[name], self.call_env)
                finally:
                    pruned, p.sink = p.sink, saved
                    p.try_depth = saved_try
                if v is None and nullable is False:
                    v = NOTCONST
            if v is NOTCONST and "default" in attrs:
                v = self.eval_const(attrs["default"])
                if v is NOTCONST:
                    v = Unknown(f"variable {name} of {self.call_address}: default is not a constant value",
                                "TF-VAR-INVALID")
            if v is NOTCONST:
                v = Unknown(f"variable {name} of {self.call_address} has no value (not set by the module call)",
                            "TF-UNRESOLVED-VAR")
            if secret:  # 秘密の値として扱うと書かれた変数の値は使わない（中の参照は残す）
                v = Unknown(f"variable {name} of {self.call_address} is {secret}; its value is not used",
                            "TF-SENSITIVE-VAR", "info", E.refs_in(v))
            elif not isinstance(v, Unknown):
                v = E.convert(v, spec)
            hop = f"{self.prefix}var.{name}"
            v, pruned = prepend_through(v, hop), frozenset(through_refs(pruned, hop))
        finally:
            self._busy.discard(key)
        self._var_cache[name] = (v, pruned)
        self.sink |= pruned
        return v

    def output_value(self, name: str):
        """子のモジュールの出力の値と、値に残らなかった参照（pruned）。through に output を足す。"""
        if name in self._out_cache:
            return self._out_cache[name]
        hop = f"{self.prefix}output.{name}"
        body = self.outputs.get(name)
        if body is None:
            if self.via == "module_summary":
                u = Unknown(f"output {name} of {self.call_address} is not in the summary table",
                            "TF-MODULE-SUMMARY-OUTPUT")
            else:
                u = Unknown(f"reference to undefined output {name} of {self.call_address}", "TF-UNDEFINED-REF")
            return u, frozenset()
        key = ("output", name)
        if key in self._busy:
            return Unknown(f"output {name} of {self.call_address} refers to itself", "TF-CYCLE"), frozenset()
        attrs = self.body_attrs(body)
        self._busy.add(key)
        saved, self.sink = self.sink, set()
        saved_try, self.try_depth = self.try_depth, 0
        try:
            v = self.eval_safe(attrs["value"], {}) if "value" in attrs else \
                Unknown(f"output {name} of {self.call_address} has no value", "TF-MALFORMED-BLOCK")
        finally:
            pruned, self.sink = self.sink, saved
            self.try_depth = saved_try
            self._busy.discard(key)
        secret = next((k for k in ("sensitive", "ephemeral") if k in attrs and const(attrs[k]) is True), None)
        if secret:  # sensitive の出力の値は使わない（中の参照は unevaluated で残す）
            v = Unknown(f"output {name} of {self.call_address} is {secret}; its value is not used",
                        "TF-SENSITIVE-VAR", "info", E.refs_in(v))
        out = (prepend_through(v, hop), frozenset(through_refs(pruned, hop)))
        self._out_cache[name] = out
        return out

    def module_output(self, obj: ModObj, name: str):
        v, pruned = obj.child.output_value(name)
        self.sink |= pruned
        return v

    def resolve_mods(self, v):
        """値の中に残ったモジュールの呼び出し（module.x そのもの）を、出力の値のオブジェクトにする。"""
        if isinstance(v, ModObj):
            return {n: self.resolve_mods(self.module_output(v, n)) for n in sorted(v.child.outputs)}
        if isinstance(v, ZeroColl):
            return v
        if isinstance(v, list) and any(isinstance(e, (ModObj, list, dict)) for e in v):
            return type(v)(self.resolve_mods(e) for e in v)
        if isinstance(v, dict) and any(isinstance(e, (ModObj, list, dict)) for e in v.values()):
            return type(v)((k, self.resolve_mods(e)) for k, e in v.items())
        return v

    # --- locals と count・for_each
    def local_value(self, name):
        if name in self._local_cache:
            v, pruned = self._local_cache[name]
            self.sink |= pruned
            return v
        if name not in self.locals:
            return Unknown(f"reference to undefined local.{name}", "TF-UNDEFINED-REF")
        key = ("local", name)
        if key in self._busy:
            return Unknown(f"local.{name} refers to itself", "TF-CYCLE")
        self._busy.add(key)
        saved, self.sink = self.sink, set()
        saved_try, self.try_depth = self.try_depth, 0
        try:
            v = self.eval_safe(self.locals[name], {})
        finally:
            pruned, self.sink = self.sink, saved
            self.try_depth = saved_try
            self._busy.discard(key)
        self._local_cache[name] = (v, frozenset(pruned))
        self.sink |= pruned
        return v

    def instances(self, blk: Block) -> Instances:
        base = blk.base
        if base in self._inst_cache:
            return self._inst_cache[base]
        meta = "count" if "count" in blk.attrs else "for_each" if "for_each" in blk.attrs else ""
        if not meta:
            inst = Instances("single")
            self._inst_cache[base] = inst
            return inst
        key = ("instances", base)
        if key in self._busy:
            return Instances("unknown", meta, unknown=Unknown(f"{meta} of {base} refers to itself", "TF-CYCLE"))
        self._busy.add(key)
        saved, self.sink = self.sink, set()
        try:
            v = self.eval_safe(blk.attrs[meta], {})
            inst = self.decide_instances(meta, v)
        finally:
            self.sink = saved  # 決まった count・for_each の式の参照は残さない（CFN の Fn::ForEach と同じ）
            self._busy.discard(key)
        self._inst_cache[base] = inst
        return inst

    @staticmethod
    def decide_instances(meta: str, v) -> Instances:
        def unknown(reason, code="TF-UNEVALUATED"):
            return Instances("unknown", meta, unknown=E.unknown_from(v, reason, code) if not isinstance(v, Unknown)
                             else v)
        if meta == "count":
            if v is None:
                return unknown("count is null", "TF-EVAL-ERROR")
            if isinstance(v, str):  # "2"（型の無い変数に --var で渡した値など）は数に変換する（Terraform と同じ）
                try:
                    v = E.to_number(v)
                except EvalError as e:
                    return unknown(str(e), "TF-EVAL-ERROR")
            if not E.is_number(v):
                return unknown("count is not known before apply")
            try:
                n = E.to_int(v)
            except EvalError as e:
                return unknown(str(e), "TF-EVAL-ERROR")
            if n < 0:
                return unknown("count is negative", "TF-EVAL-ERROR")
            return Instances("count", meta, keys=list(range(n))) if n else Instances("zero", meta)
        if isinstance(v, dict):
            keys = sorted(v)
            return Instances("each", meta, keys=keys, values={k: v[k] for k in keys}) if keys else \
                Instances("zero", meta)
        if isinstance(v, list):
            if not all(isinstance(x, str) for x in v):
                if all(E.is_concrete(x) for x in v):
                    return unknown("for_each must be a map or a set of strings", "TF-EVAL-ERROR")
                return unknown("for_each is not known before apply")
            keys = sorted(set(v))
            return Instances("each", meta, keys=keys, values={k: k for k in keys}) if keys else \
                Instances("zero", meta)
        if v is None:
            return unknown("for_each is null", "TF-EVAL-ERROR")
        return unknown("for_each is not known before apply")

    def all_addresses(self, blk: Block) -> list[str]:
        """ブロックのすべてのインスタンスの address（0 個なら作られないブロック、決まらなければ [*]）。"""
        base = self.prefix + blk.base
        inst = self.instances(blk)
        if self.via == "module_summary" and (blk.kind == "data" or inst.mode == "zero"):
            return []  # 要約表の中の data と、作られないリソースは載せない
        if inst.mode in ("count", "each"):
            return [inst_address(base, k) for k in inst.keys]
        if inst.mode == "unknown":
            return [base + "[*]"]
        return [base]

    def block_value(self, blk: Block):
        """リソース・data・module の参照の値（インスタンスごとの Res のまとまり）。展開するモジュールは ModObj。"""
        base = self.prefix + blk.base
        inst = self.instances(blk)
        if blk.kind == "module" and self.expanded(blk):
            if inst.mode == "single":
                return ModObj(self.child(blk, None))
            if inst.mode == "count":
                return ResList(ModObj(self.child(blk, k)) for k in inst.keys)
            if inst.mode == "each":
                return ResMap((k, ModObj(self.child(blk, k))) for k in inst.keys)
            if inst.mode == "zero":  # 要約表の中の作られない呼び出しは載せない（リソースと同じ）
                return ResList() if self.via == "module_summary" else ZeroColl(ModObj(self.child(blk, ZERO)))
            return ModObj(self.child(blk, STAR))
        if inst.mode == "single":
            return Res(base)
        if inst.mode == "count":
            return ResList(Res(inst_address(base, k)) for k in inst.keys)
        if inst.mode == "each":
            return ResMap((k, Res(inst_address(base, k))) for k in inst.keys)
        if inst.mode == "zero":
            # 要約表の中の作られないリソースは載せないので、Terraform と同じく空のまとまり（[0] は誤り。try で null）
            return ResList() if self.via == "module_summary" else ZeroColl(Res(base))
        return Res(base + "[*]", None, True)

    # --- モジュールの呼び出し
    def module_plan(self, blk: Block) -> tuple:
        """モジュールの呼び出しの読み方。("local", フォルダ)・("summary", Summary, 前提)・
        ("blackbox", level, code, 理由)。"""
        if blk.base in self._plans:
            return self._plans[blk.base]
        source = const(blk.attrs["source"]) if "source" in blk.attrs else NOTCONST
        version = const(blk.attrs["version"]) if "version" in blk.attrs else NOTCONST
        version = version if isinstance(version, str) and version else None
        plan: tuple
        if not (isinstance(source, str) and source):
            plan = ("blackbox", "warn", "TF-MALFORMED-BLOCK", "module has no constant source")
        elif self.via == "module_summary" and M.is_local(source):
            # 要約表の中のサブモジュール（"./modules/x"）は、同じ版の要約表の "<source>//modules/x"
            key = M.join_summary_source(self.summary.source, source)
            cands = [s for s in M.load()[0].get(key or "", []) if set(s.majors) & set(self.summary.majors)]
            plan = ("summary", cands[0], None) if cands else \
                ("blackbox", "info", "TF-MODULE-BLACKBOX", f"submodule {key} is not in the summary table")
        elif M.is_local(source):
            d = (self.dir / source).resolve() if self.dir is not None else None
            if d is None or not d.is_dir() or not any(p.suffix == ".tf" for p in d.iterdir() if p.is_file()):
                where = self.ctx.rel(d) if d is not None else source
                plan = ("blackbox", "warn", "TF-MODULE-UNREADABLE",
                        f"local module {source} cannot be read (no .tf files in {where})")
            else:
                plan = ("local", d)
        else:
            summary, why, note = M.choose(source, version)
            if summary is None:
                iam = " (it makes IAM resources only: H-IAM)" if M.iam_only(source) else ""
                plan = ("blackbox", "info", "TF-MODULE-BLACKBOX", f"module {source} is not read: {why}{iam}")
            else:
                plan = ("summary", summary, note)
        if plan[0] != "blackbox":
            key = plan[1] if plan[0] == "local" else f"summary:{plan[1].source}"
            if key in self.chain:
                plan = ("blackbox", "warn", "TF-MODULE-CYCLE", f"module {source} calls itself")
            elif self.depth + 1 > MAX_MODULE_DEPTH:
                plan = ("blackbox", "warn", "TF-MODULE-DEPTH",
                        f"module {source} is nested deeper than {MAX_MODULE_DEPTH} levels")
        self._plans[blk.base] = plan
        return plan

    def expanded(self, blk: Block) -> bool:
        return blk.kind == "module" and self.module_plan(blk)[0] != "blackbox"

    def child(self, blk: Block, key) -> "ModuleEval":
        """展開するモジュールの呼び出しのインスタンス（key は count の番号・for_each のキー・None・ZERO・STAR）。"""
        ck = (blk.base, key)
        if ck in self._children:
            return self._children[ck]
        base = self.prefix + blk.base
        plan = self.module_plan(blk)
        enabled = True
        meta = "count" if "count" in blk.attrs else "for_each"
        if key is None:
            addr, env = base, {}
        elif key in (ZERO, STAR):
            why = ("count is 0" if meta == "count" else "for_each is empty") if key == ZERO else f"{meta} is not known"
            u = Unknown(f"{'count.index' if meta == 'count' else 'each'} is not known ({why})", "TF-COUNT-INDEX", "info")
            env = {"count": {"index": u}} if meta == "count" else {"each": {"key": u, "value": u}}
            addr = base if key == ZERO else base + "[*]"
            enabled = False if key == ZERO else None
        else:
            addr = inst_address(base, key)
            inst = self.instances(blk)
            env = {"count": {"index": key}} if inst.mode == "count" else \
                {"each": {"key": key, "value": inst.values[key]}}
        c = ModuleEval(self.ctx, plan[1] if plan[0] == "local" else None, addr + ".")
        c.parent = self
        c.call_address = addr
        c.call_args = {k: v for k, v in blk.attrs.items() if k not in MODULE_META}
        c.call_env = env
        if plan[0] == "summary":
            c.via, c.summary = "module_summary", plan[1]
            c.file_override = blk.file
            if plan[2]:
                self.ctx.assume(f"{addr}: {plan[2]}")
        c.enabled_base = weakest(self.enabled_base, enabled)
        c.multi = self.multi or key == STAR
        c.chain = self.chain + ((plan[1] if plan[0] == "local" else f"summary:{plan[1].source}"),)
        c.depth = self.depth + 1
        if "providers" in blk.attrs:
            c.explicit_providers = True
            c.provider_map = self.providers_arg(blk.attrs["providers"], addr)
        c.depends_from = self.depends_from + ([(self, blk.attrs["depends_on"])] if "depends_on" in blk.attrs else [])
        self._children[ck] = c
        c.load()
        c.setup_child()
        self.ctx.modules.append(c)
        return c

    def child_keys(self, blk: Block) -> list:
        inst = self.instances(blk)
        if inst.mode == "single":
            return [None]
        if inst.mode in ("count", "each"):
            return list(inst.keys)
        if inst.mode == "zero":
            return [] if self.via == "module_summary" else [ZERO]
        return [STAR]

    def providers_arg(self, expr, addr: str) -> dict:
        """モジュールの providers 引数（{ aws = aws.use1, aws.east = aws }）を、子の名前 → 親の名前にする。"""
        out: dict = {}
        t = unwrap(expr)
        if not (isinstance(t, Tree) and t.data == "object"):
            self.diag("warn", "TF-MALFORMED-BLOCK", "providers", "providers is not an object", addr)
            return out
        for el in sig(t):
            cs = sig(el)
            k, v = self.provider_name(sig(cs[0])[0]), self.provider_name(cs[-1])
            if k is None or v is None:
                self.diag("warn", "TF-MALFORMED-BLOCK", "providers", "providers has an entry that is not a provider",
                          addr)
                continue
            out[k] = v
        return out

    def resolve_provider(self, name: str):
        """provider の名前（aws・aws.east）を、設定のあるモジュールとその中の名前にする。無ければ None。"""
        if name in self.providers:
            return self, name
        if self.parent is None:
            return None
        if name in self.provider_map:
            return self.parent.resolve_provider(self.provider_map[name])
        if "." not in name and not self.explicit_providers:  # 既定の provider は呼び出し側から引き継ぐ
            return self.parent.resolve_provider(name)
        return None

    def resource_addresses(self) -> list[str]:
        """このモジュールの中（入れ子のモジュールを含む）のすべてのリソース・data の address（depends_on に使う）。"""
        out: list[str] = []
        for base, blk in sorted(self.blocks.items()):
            if blk.kind == "data" and self.via == "module_summary":
                continue
            if self.expanded(blk):
                for k in self.child_keys(blk):
                    out += self.child(blk, k).resource_addresses()
            elif blk.kind == "module" or blk.kind in ("resource", "data"):
                out += self.all_addresses(blk)
        return out

    # --- 評価
    def eval_safe(self, t, env: dict):
        """eval の誤り（EvalError）を、評価できなかった値（Unknown）にする。"""
        try:
            return self.eval(t, env)
        except EvalError as e:
            return Unknown(str(e) or "evaluation error", "TF-EVAL-ERROR", "warn", self.static_refs(t))
        except RecursionError:
            return Unknown("the expression is too deeply nested", "TF-UNEVALUATED", "warn", self.static_refs(t))

    def spec_refs(self, trees, env: dict) -> set:
        """評価で使わなかった式（条件式の選ばれなかった側など）の中の参照。評価してみて、だめなら式から探す。"""
        trees = trees if isinstance(trees, list) else [trees]
        saved, self.sink = self.sink, set()
        out: set = set()
        try:
            for t in trees:
                try:
                    out |= E.refs_in(self.eval(t, env))
                except (EvalError, RecursionError):
                    out |= set(self.static_refs(t))
            out |= self.sink
        finally:
            self.sink = saved
        return out

    def lose(self, before, after) -> None:
        """評価で値に残らなかった参照を pruned にする。"""
        if isinstance(after, Unknown):
            return
        self.prune(E.refs_in(before), after)

    def prune(self, refs: set, after) -> None:
        """refs のうち、after に同じリソースへの参照が無いものを pruned にする（属性が違うだけなら捨てていない）。"""
        kept = {block_address(r[0]) for r in E.refs_in(after)}
        self.sink |= {r for r in refs if block_address(r[0]) not in kept}

    def eval(self, t, env: dict):
        t = unwrap(t)
        if not isinstance(t, Tree):
            raise EvalError(f"unexpected token {getattr(t, 'type', t)}")
        d = t.data
        if d in ("int_lit", "float_lit", "literal_value"):
            return const(t)
        if d == "string":
            return self.template(string_tokens(t), env)
        if d in HEREDOC:
            return self.template(text_tokens(heredoc_body(str(t.children[0]))), env)
        if d == "template_string":  # %{…} の中の \"…\"
            return _unescape(str(t.children[0])[2:-2])
        if d == "tuple":
            return [self.eval(c, env) for c in sig(t)]
        if d == "object":
            return self.object(t, env)
        if d == "function_call":
            return self.call(t, env)
        if d in TRAVERSAL or d == "identifier":
            return self.reference(t, env)
        if d == "unary_op":
            return self.unary(t, env)
        if d == "binary_op":
            return self.binary(t, env)
        if d == "conditional":
            return self.conditional(t, env)
        if d in ("for_tuple_expr", "for_object_expr"):
            return self.for_expr(t, env)
        return Unknown(f"{d} is not supported", "TF-UNEVALUATED", "warn", self.static_refs(t))

    # テンプレート
    def template(self, tokens: list, env: dict):
        """"${…}" と heredoc。${…} が1つだけなら、その値のまま（HCL と同じ）。"""
        trees = token_trees(tokens)
        bad = any(not isinstance(tok, str) and (tok[0] == "bad" or None in tok) for tok in tokens)
        try:
            nodes = None if bad else build_template(apply_strip(tokens))
        except ValueError:
            nodes = None
        if nodes is None:
            return Unknown("a template cannot be parsed", "TF-UNEVALUATED", "warn",
                           set().union(*[self.static_refs(x) for x in trees]) if trees else set())
        if len(tokens) == 1 and not isinstance(tokens[0], str) and tokens[0][0] == "expr":
            return self.eval(tokens[0][1], env)
        return E.concat_parts(self.template_nodes(nodes, env))

    def template_nodes(self, nodes: list, env: dict) -> list:
        parts: list = []
        for n in nodes:
            if isinstance(n, str):
                parts.append(n)
            elif n[0] == "expr":
                parts.append(E.template_part(self.eval(n[1], env)))
            elif n[0] == "if":
                c = self.eval(n[1], env)
                if isinstance(c, bool) or c in ("true", "false"):
                    chosen, other = (n[2], n[3]) if E.to_bool(c) else (n[3], n[2])
                    got = self.template_nodes(chosen, env)
                    self.prune(self.spec_node_refs(other, env), got)
                    parts += got
                else:
                    parts.append(E.unknown_from(c, "%{if} with a condition that is not known before apply",
                                                extra_refs=self.spec_node_refs(n[2] + n[3], env)))
            else:  # for
                names, coll = n[1], self.eval(n[2], env)
                items = self.iter_items(coll)
                if items is None:
                    parts.append(E.unknown_from(coll, "%{for} over a value that is not known before apply",
                                                extra_refs=self.spec_node_refs(n[3], env)))
                    continue
                for k, v in items:
                    env2 = dict(env)
                    if len(names) == 2:
                        env2[names[0]], env2[names[1]] = k, v
                    else:
                        env2[names[0]] = v
                    parts += self.template_nodes(n[3], env2)
        return parts

    def spec_node_refs(self, nodes: list, env: dict) -> set:
        saved, self.sink = self.sink, set()
        try:
            try:
                out = E.refs_in(self.template_nodes(nodes, env))
            except (EvalError, RecursionError):
                out = set()
                for t in self.node_trees(nodes):
                    out |= set(self.static_refs(t))
            return out | self.sink
        finally:
            self.sink = saved

    def node_trees(self, nodes: list) -> list:
        out = []
        for n in nodes:
            if isinstance(n, str):
                continue
            if n[0] == "expr":
                out.append(n[1])
            elif n[0] == "if":
                out += [n[1]] + self.node_trees(n[2]) + self.node_trees(n[3])
            else:
                out += [n[2]] + self.node_trees(n[3])
        return out

    @staticmethod
    def iter_items(coll):
        """for 式・%{for}・dynamic で回す (キー, 値) の並び。回せない値なら None。"""
        if isinstance(coll, dict):
            return [(k, coll[k]) for k in sorted(coll)]
        if isinstance(coll, list):
            return list(enumerate(coll))
        return None

    # 演算と条件式
    def unary(self, t: Tree, env: dict):
        op = str(t.children[0]).strip()
        v = self.eval(t.children[-1], env)
        if not E.is_concrete(v):
            return E.unknown_from(v, f"operator {op} on a value that is not known before apply")
        if op == "-":
            return E.norm_number(-E.to_number(v))
        return not E.to_bool(v)

    def binary(self, t: Tree, env: dict):
        cs = sig(t)
        term = sig(cs[1])
        op = name_of(term[0])
        a = self.eval(cs[0], env)
        b = self.eval(term[1], env)
        if op in ("&&", "||"):
            for x in (a, b):  # 片方で決まるときは決める（false && …、true || …）
                if isinstance(x, bool) and x == (op == "||"):
                    return x
        if op in ("==", "!=") and (a is None) != (b is None):
            # null との比較は、もう一方が null になりえない値（マップ・リスト・文字列のテンプレート・擬似パラメータ・AZ）
            # なら、中に決まらない値があっても決まる（リソースの属性 $res と $unknown は null かもしれない）
            other = b if a is None else a
            whole = isinstance(other, Res) and other.attr is None  # リソース・モジュールの呼び出しそのもの
            if isinstance(other, (dict, list, Concat, Json, Pseudo, Az, ModObj)) or whole or E.is_concrete(other):
                return op == "!="
        if not (E.is_concrete(a) and E.is_concrete(b)):
            return E.unknown_from([a, b], f"operator {op} on a value that is not known before apply")
        if op == "==":
            return E.same(a, b)
        if op == "!=":
            return not E.same(a, b)
        if op == "&&":
            return E.to_bool(a) and E.to_bool(b)
        if op == "||":
            return E.to_bool(a) or E.to_bool(b)
        x, y = E.to_number(a), E.to_number(b)
        if op in ("+", "-", "*", "/", "%"):
            return E.arith(op, x, y)
        if op == "<":
            return x < y
        if op == ">":
            return x > y
        if op == "<=":
            return x <= y
        if op == ">=":
            return x >= y
        raise EvalError(f"unknown operator {op}")

    def conditional(self, t: Tree, env: dict):
        cond_t, a_t, b_t = sig(t)[:3]
        c = self.eval(cond_t, env)
        if isinstance(c, bool) or c in ("true", "false"):
            chosen, other = (a_t, b_t) if E.to_bool(c) else (b_t, a_t)
            v = self.eval(chosen, env)
            self.prune(self.spec_refs(other, env), v)
            return v
        if E.is_concrete(c):
            raise EvalError(f"the condition is {E.type_name(c)}, not bool")
        return E.unknown_from(c, "the condition is not known before apply", extra_refs=self.spec_refs([a_t, b_t], env))

    def for_expr(self, t: Tree, env: dict):
        intro = next(c for c in t.children if isinstance(c, Tree) and c.data == "for_intro")
        names = [name_of(c) for c in intro.children if isinstance(c, Tree) and c.data == "identifier"]
        coll_t = next(c for c in intro.children if isinstance(c, Tree) and c.data not in ("identifier",
                                                                                         "new_line_or_comment"))
        cond_t = next((sig(c)[-1] for c in t.children if isinstance(c, Tree) and c.data == "for_cond"), None)
        body = [c for c in t.children if isinstance(c, Tree) and c.data not in ("for_intro", "for_cond",
                                                                                 "new_line_or_comment")]
        grouping = any(isinstance(c, Token) and c.type == "ELLIPSIS" for c in t.children)
        is_obj = t.data == "for_object_expr"
        coll = self.eval(coll_t, env)
        items = self.iter_items(coll)
        rest = body + ([cond_t] if cond_t is not None else [])
        if items is None:
            if coll is None:
                raise EvalError("for expression over null")
            return E.unknown_from(coll, "for expression over a value that is not known before apply",
                                  extra_refs=self.spec_refs_static(rest))
        out_list: list = []
        out_map: dict = {}
        excluded: set = set()  # if で除いた要素の参照（pruned）
        for k, v in items:
            env2 = dict(env)
            if len(names) == 2:
                env2[names[0]], env2[names[1]] = k, v
            else:
                env2[names[0]] = v
            if cond_t is not None:
                c = self.eval(cond_t, env2)
                if not (isinstance(c, bool) or c in ("true", "false")):
                    if E.is_concrete(c):
                        raise EvalError("the for condition is not bool")
                    return E.unknown_from([coll, c], "the for condition is not known before apply",
                                          extra_refs=self.spec_refs_static(rest))
                if not E.to_bool(c):
                    excluded |= E.refs_in(v) | (E.refs_in(k) if len(names) == 2 else set())
                    continue
            if is_obj:
                key = self.eval(body[0], env2)
                if isinstance(key, bool) or E.is_number(key):
                    key = E.to_string(key)
                if not isinstance(key, str):
                    if E.is_concrete(key):
                        raise EvalError("the key of a for expression must be a string")
                    return E.unknown_from([coll, key], "the key of a for expression is not known before apply",
                                          extra_refs=self.spec_refs_static(rest))
                val = self.eval(body[1], env2)
                if grouping:
                    out_map.setdefault(key, []).append(val)
                elif key in out_map:
                    raise EvalError(f"duplicate key {key!r} in a for expression")
                else:
                    out_map[key] = val
            else:
                out_list.append(self.eval(body[0], env2))
        result = out_map if is_obj else out_list
        self.prune(excluded, result)
        return result

    def spec_refs_static(self, trees: list) -> set:
        out: set = set()
        for t in trees:
            out |= set(self.static_refs(t))
        return out

    def object(self, t: Tree, env: dict):
        out: dict = {}
        unknown_key = None
        for el in sig(t):
            cs = sig(el)
            key_t = cs[0]
            c = sig(key_t)[0]
            if isinstance(c, Tree) and c.data == "keyword":
                key = name_of(c)
            elif (n := identifier_name(c)) is not None:
                key = n
            else:
                key = self.eval(c, env)
                if isinstance(key, bool) or E.is_number(key):
                    key = E.to_string(key)
            val = self.eval(cs[-1], env)
            if not isinstance(key, str):
                unknown_key = unknown_key or (key, val)
                out[f"\u0000{len(out)}"] = [key, val]  # 決まらないキー（下で Unknown にする）
                continue
            out[key] = val
        if unknown_key is not None:
            if E.is_concrete(unknown_key[0]):
                raise EvalError("an object key must be a string")
            return E.unknown_from(list(out.values()), "an object key is not known before apply")
        return out

    def call(self, t: Tree, env: dict):
        cs = sig(t)
        name = "::".join(name_of(c) for c in cs if isinstance(c, Tree) and c.data == "identifier")
        args_t = next((c for c in cs if isinstance(c, Tree) and c.data == "arguments"), None)
        arg_trees = [c for c in sig(args_t) if isinstance(c, Tree)] if args_t is not None else []
        expand = args_t is not None and any(isinstance(c, Token) and c.type == "ELLIPSIS" for c in args_t.children)
        if name == "try":
            return self.call_try(arg_trees, env)
        if name == "can":
            return self.call_can(arg_trees, env)
        args = [self.eval(a, env) for a in arg_trees]
        if expand and args:
            last = args[-1]
            if not isinstance(last, list):
                return E.unknown_from(args, f"{name}(...) with an argument that is not known before apply")
            args = args[:-1] + list(last)
        result = E.call_function(name, args)
        if name in SELECTING:
            self.lose(args, result)
        return result

    def call_try(self, arg_trees: list, env: dict):
        failed: set = set()  # 誤りになった式の中の参照（値に残らないので pruned）
        for i, a in enumerate(arg_trees):
            saved, self.sink = self.sink, set()
            self.try_depth += 1
            try:
                v = self.eval(a, env)
            except EvalError:
                self.sink = saved
                failed |= self.static_refs(a)
                continue
            finally:
                self.try_depth -= 1
            sub, self.sink = self.sink, saved
            self.sink |= sub
            rest = self.spec_refs(arg_trees[i + 1:], env) if i + 1 < len(arg_trees) else set()
            if isinstance(v, Unknown):
                return Unknown(v.reason, v.code, v.level, v.refs | rest | failed)
            self.prune(rest | failed, v)
            return v
        raise EvalError("try(): no expression succeeded")

    def call_can(self, arg_trees: list, env: dict):
        if len(arg_trees) != 1:
            raise EvalError("can() takes one argument")
        self.try_depth += 1
        try:
            v = self.eval(arg_trees[0], env)
        except EvalError:
            return False
        finally:
            self.try_depth -= 1
        if not E.is_concrete(v):  # 値の全体が決まらなければ、誤りになるかも決まらない（Terraform と同じ）
            return E.unknown_from(v, "can() of a value that is not known before apply")
        return True

    # 参照
    def reference(self, t: Tree, env: dict):
        root, steps = flatten(t)
        if not (isinstance(root, Tree) and root.data == "identifier"):
            return self.traverse(self.eval(root, env), steps, env)
        name = name_of(root)
        if name in env:
            return self.traverse(env[name], steps, env)
        first = steps[0][1] if steps and steps[0][0] == "attr" else None
        if self.const_mode:
            raise EvalError(f"a reference ({name}) is not allowed here")
        if name == "var":
            return self.traverse(self.var_value(first), steps[1:], env)
        if name == "local":
            return self.traverse(self.local_value(first), steps[1:], env)
        if name in ("count", "each"):
            return Unknown(f"{name}.{first} is used outside a block with {'count' if name == 'count' else 'for_each'}",
                           "TF-UNDEFINED-REF")
        if name == "self":
            return Unknown("self is only known in provisioners and connections", "TF-UNEVALUATED", "info")
        if name == "path":
            if first == "module" and self.dir is None:
                return Unknown("path.module of a module expanded from the summary table", "TF-UNEVALUATED", "info")
            if first in ("module", "root", "cwd"):
                return self.ctx.rel(self.dir) if first == "module" else "."
            return Unknown(f"path.{first} is not supported", "TF-UNEVALUATED")
        if name == "terraform":
            if first == "workspace":
                self.ctx.assume('terraform.workspace is evaluated as "default"')
                return "default"
            return Unknown(f"terraform.{first} is not supported", "TF-UNEVALUATED")
        if name == "ephemeral":
            base = f"ephemeral.{first}.{steps[1][1] if len(steps) > 1 and steps[1][0] == 'attr' else ''}"
            blk = self.ephemerals.get(base)
            if blk is None:
                return Unknown(f"reference to undefined {base}", "TF-UNDEFINED-REF")
            return Unknown(f"{base} is an ephemeral value; it is not known", "TF-EPHEMERAL", "info",
                           self.static_refs(blk.body))
        if name == "data":
            base, rest = f"data.{first}.{steps[1][1] if len(steps) > 1 and steps[1][0] == 'attr' else ''}", steps[2:]
        elif name == "module":
            base, rest = f"module.{first}", steps[1:]
        else:
            base, rest = f"{name}.{first}", steps[1:]
        blk = self.blocks.get(base) if first else None
        if blk is None:
            return Unknown(f"reference to undefined {base if first else name}", "TF-UNDEFINED-REF")
        if blk.kind == "data" and "provider" not in blk.attrs and self.instances(blk).mode == "single":
            a = rest[0][1] if rest and rest[0][0] == "attr" else None
            if blk.plain and (blk.type, a) in PSEUDO_DATA:
                return self.traverse(Pseudo(PSEUDO_DATA[(blk.type, a)]), rest[1:], env)
            # AZ は state などの引数があってもよい（別のリージョンを指す provider だけ除く）
            if blk.type == "aws_availability_zones" and a == "names":
                return self.traverse(Az("*"), rest[1:], env)
            # 別の state の出力（terraform_remote_state）は読まない。attr は outputs.<出力の名前>（7.2）
            if blk.type == "terraform_remote_state" and a == "outputs" and len(rest) > 1:
                st = rest[1]
                out = st[1] if st[0] == "attr" else const(st[1]) if st[0] == "index" and isinstance(st[1], Tree) \
                    else None
                if isinstance(out, str):
                    return self.traverse(Res(self.prefix + blk.base, f"outputs.{out}"), rest[2:], env)
        if blk.kind == "module" and self.expanded(blk):
            return self.resolve_mods(self.traverse(self.block_value(blk), rest, env))
        if blk.kind == "data" and self.via == "module_summary":
            return Unknown(f"{base} in the summary table is not read", "TF-UNEVALUATED", "info")
        return self.traverse(self.block_value(blk), rest, env)

    def traverse(self, v, steps: list, env: dict):
        for st in steps:
            v = self.step(v, st, env)
        return v

    def step(self, v, st, env: dict):
        kind = st[0]
        if isinstance(v, Unknown):
            return v
        if isinstance(v, ModObj):  # 展開したモジュールの呼び出し: 属性は出力
            if kind == "attr":
                return self.module_output(v, st[1])
            if kind == "index":
                if v.child.multi:  # ×N のモジュールは、どの添字でも同じ1つ（Res の [*] と同じ）
                    return v
                key = st[1] if isinstance(st[1], int) else self.eval(st[1], env)
                if isinstance(key, str):
                    return self.module_output(v, key)
                if not E.is_concrete(key):
                    return E.unknown_from(key, "an index that is not known before apply")
                raise EvalError("a module call is not a list")
            return self.traverse(v, st[1], env) if v.child.multi else [self.traverse(v, st[1], env)]
        if kind == "attr":
            name = st[1]
            if isinstance(v, Res):
                return v if v.attr is not None else replace(v, attr=name)
            if isinstance(v, dict):
                if name not in v:
                    raise EvalError(f"unsupported attribute {name!r}")
                return v[name]  # マップ・オブジェクトの引かなかった値の参照は pruned にしない（each.value.x などで多くなる）
            if v is None:
                raise EvalError(f"attribute {name!r} of null")
            if isinstance(v, (Pseudo, Az, Concat, Json)):
                return E.unknown_from(v, f"attribute {name} of a value that is not known before apply")
            raise EvalError(f"attribute {name!r} of a {E.type_name(v)}")
        if kind == "index":
            key = st[1] if isinstance(st[1], int) else self.eval(st[1], env)
            if isinstance(v, Res):
                return replace(v, attr=None, multi=False) if v.multi else v
            if isinstance(v, ZeroColl):
                if self.try_depth:  # try()・can() の中では Terraform と同じく誤り（次の式に進む）
                    raise EvalError("index into a block whose count is 0")
                return v.res
            if isinstance(v, Az) and v.index == "*" and E.is_number(key):
                i = E.to_int(key)
                if i < 0:
                    raise EvalError("negative index")
                return Az(i)
            if not E.is_concrete(key):
                return E.unknown_from([v, key], "an index that is not known before apply")
            if isinstance(v, list):
                if isinstance(key, bool):
                    raise EvalError("a bool cannot be a list index")
                i = E.to_int(key)
                if not (0 <= i < len(v)):
                    raise EvalError(f"index {i} is out of range (length {len(v)})")
                out = v[i]
                if not isinstance(v, ResList):  # リストの選ばなかった要素の参照は pruned（CFN の Fn::Select と同じ）
                    self.lose(v, out)
                return out
            if isinstance(v, dict):
                k = key if isinstance(key, str) else E.to_string(key)
                if k not in v:
                    raise EvalError(f"no key {k!r}")
                return v[k]
            if v is None:
                raise EvalError("index of null")
            if isinstance(v, (Pseudo, Az, Concat, Json)):
                return E.unknown_from([v, key], "an index into a value that is not known before apply")
            raise EvalError(f"index into a {E.type_name(v)}")
        # splat
        sub = st[1]
        if v is None:
            return []
        if isinstance(v, Res):
            if v.multi:  # ×N のまとまりのスプラットは、[*] への1つの $res（7.2）
                return self.traverse(replace(v, attr=None, multi=False), sub, env)
            if v.attr is not None:
                return self.traverse(v, sub, env)
            return [self.traverse(v, sub, env)]
        if isinstance(v, list):
            return [self.traverse(e, sub, env) for e in v]
        if isinstance(v, Az) and v.index == "*":
            return v
        return [self.traverse(v, sub, env)]

    def static_refs(self, node) -> set:
        """式を評価せずに、中のリソース・data・module への参照を探す（local はその式をたどる）。"""
        out: set = set()
        seen: set = set()

        def walk_step(st):
            if st[0] == "index" and isinstance(st[1], Tree):
                walk(st[1])
            elif st[0] == "splat":
                for s in st[1]:
                    walk_step(s)

        def walk(t):
            if isinstance(t, list):
                for x in t:
                    walk(x)
                return
            if not isinstance(t, Tree):
                return
            if t.data in HEREDOC:
                for tree in token_trees(text_tokens(heredoc_body(str(t.children[0])))):
                    walk(tree)
                return
            if t.data == "expr_term" or t.data in TRAVERSAL:
                root, steps = flatten(t)
                if isinstance(root, Tree) and root.data == "identifier":
                    self.static_ref(name_of(root), steps, out, seen, walk)
                    for st in steps:
                        walk_step(st)
                    return
                if root is not t:
                    walk(root)
                    for st in steps:
                        walk_step(st)
                    return
            for c in t.children:
                walk(c)

        walk(node)
        return out

    def static_ref(self, name: str, steps: list, out: set, seen: set, walk) -> None:
        first = steps[0][1] if steps and steps[0][0] == "attr" else None
        if name == "local":
            if first in self.locals and first not in seen:
                seen.add(first)
                walk(self.locals[first])
            return
        if name == "data":
            base, rest = f"data.{first}.{steps[1][1] if len(steps) > 1 and steps[1][0] == 'attr' else ''}", steps[2:]
        elif name == "module":
            base, rest = f"module.{first}", steps[1:]
        else:
            base, rest = f"{name}.{first}", steps[1:]
        blk = self.blocks.get(base) if first else None
        if blk is None:
            return
        if blk.kind == "data" and "provider" not in blk.attrs and self.instances(blk).mode == "single":
            a = rest[0][1] if rest and rest[0][0] == "attr" else None
            if (blk.plain and (blk.type, a) in PSEUDO_DATA) or (blk.type == "aws_availability_zones" and a == "names"):
                return
        if self.expanded(blk):  # 展開するモジュール: 出力の式の中の参照（through に output を足す）
            keys = self.child_keys(blk)
            if rest and rest[0][0] == "index":
                key = rest[0][1] if isinstance(rest[0][1], int) else const(rest[0][1])
                keys = [key] if key in keys else keys
                rest = rest[1:]
            elif rest and rest[0][0] == "splat":
                rest = rest[0][1] + rest[1:]
            name = rest[0][1] if rest and rest[0][0] == "attr" else None
            for k in keys:
                out |= self.child(blk, k).static_output_refs(name)
            return
        addrs = self.all_addresses(blk)
        if rest and rest[0][0] == "index":
            key = rest[0][1] if isinstance(rest[0][1], int) else const(rest[0][1])
            inst = self.instances(blk)
            if inst.mode in ("count", "each") and key in inst.keys:
                addrs = [inst_address(self.prefix + blk.base, key)]
            rest = rest[1:]
        elif rest and rest[0][0] == "splat":
            rest = rest[0][1] + rest[1:]
        attr = rest[0][1] if rest and rest[0][0] == "attr" else None
        for a in addrs:
            out.add((a, attr, ()))

    def static_output_refs(self, name: str | None) -> set:
        """出力（name が None ならすべての出力）の式の中の参照。式を評価せずに探す。"""
        names = [name] if name is not None else sorted(self.outputs)
        out: set = set()
        for n in names:
            body = self.outputs.get(n)
            key = ("static-output", n)
            if body is None or key in self._busy:
                continue
            attrs = self.body_attrs(body)
            if "value" not in attrs:
                continue
            self._busy.add(key)
            try:
                out |= through_refs(self.static_refs(attrs["value"]), f"{self.prefix}output.{n}")
            finally:
                self._busy.discard(key)
        return out

    # --- 書き出し（印への変換）
    def materialize(self, v, path: str):
        """評価した値を raw IR の値にする。Unknown は $unknown にし、中の参照を unevaluated で残して診断を書く。"""
        if isinstance(v, Unknown):
            for to, attr, through in sorted(v.refs, key=ref_order):
                self.add_ref(path, to, attr, "unevaluated", through)
            reason = v.reason or "the value is not known"
            # 作られないリソース（count が 0 など）は Terraform も評価しないので、図に影響しない（info にする）
            level = "info" if self.current_enabled is False and v.level == "warn" and v.code in UNDECIDED else v.level
            self.diag(level, v.code, path, reason)
            return {"$unknown": reason}
        if isinstance(v, Res):  # through は一時的な __through で運び、emit で references に移す
            return {"$res": v.to, "attr": v.attr, **({"__through": list(v.through)} if v.through else {})}
        if isinstance(v, Pseudo):
            return {"$pseudo": v.name}
        if isinstance(v, Az):
            return {"$az": v.index}
        if isinstance(v, Concat):
            parts = [p if isinstance(p, str) else self.materialize(p, path) for p in v.parts]
            return ir_raw.maybe_json(ir_raw.normalize_concat(parts))
        if isinstance(v, Json):
            inner = self.materialize(v.value, path)
            return inner if isinstance(inner, dict) and "$unknown" in inner else {"$json": inner}
        if isinstance(v, str):
            return ir_raw.maybe_json(v)
        if isinstance(v, float):
            return E.norm_number(v)
        if isinstance(v, list):
            return [self.materialize(e, ir_raw.join_path(path, i)) for i, e in enumerate(v)]
        if isinstance(v, dict):
            return {("$" + k if k.startswith("$") else k): self.materialize(e, ir_raw.join_path(path, k))
                    for k, e in v.items()}
        return v

    def value_at(self, expr, path: str, env: dict):
        """属性1つを評価して書き出す。値に残らなかった参照は、この位置に pruned で残す。"""
        saved, self.sink = self.sink, set()
        try:
            v = self.eval_safe(expr, env)
            out = self.materialize(v, path)
        finally:
            pruned, self.sink = self.sink, saved
        for to, attr, through in sorted(pruned, key=ref_order):
            self.add_ref(path, to, attr, "pruned", through)
        return v, out

    def body_props(self, body: Tree, path: str, env: dict, meta: set = frozenset()) -> dict:
        """属性とブロックを props にする。ブロックは同じ名前のものをリストにする（plan JSON と同じ形）。"""
        out: dict = {}
        for item in sig(body):
            if not isinstance(item, Tree):
                continue
            if item.data == "attribute":
                cs = sig(item)
                name = name_of(cs[0])
                if name in meta:
                    continue
                v, m = self.value_at(cs[-1], ir_raw.join_path(path, name), env)
                if v is not None:  # null は書かないのと同じ
                    out[name] = m
            elif item.data == "block":
                cs = sig(item)
                btype = name_of(cs[0])
                if btype in meta:
                    continue
                if btype == "dynamic" and len(cs) >= 3:
                    self.dynamic_block(label_text(cs[1]), cs[-1], path, env, out)
                    continue
                lst = out.setdefault(btype, [])
                if not isinstance(lst, list):
                    self.diag("warn", "TF-MALFORMED-BLOCK", ir_raw.join_path(path, btype),
                              f"block {btype} has the same name as an attribute")
                    continue
                lst.append(self.body_props(cs[-1], ir_raw.join_path(ir_raw.join_path(path, btype), len(lst)), env))
        return out

    def dynamic_block(self, label: str, body: Tree, path: str, env: dict, out: dict) -> None:
        """dynamic ブロックを展開する。for_each が決まらなければ、$unknown の要素1つ（中の参照は unevaluated）。"""
        lst = out.setdefault(label, [])
        if not isinstance(lst, list):
            self.diag("warn", "TF-MALFORMED-BLOCK", ir_raw.join_path(path, label),
                      f"block {label} has the same name as an attribute")
            return
        attrs = self.body_attrs(body)
        content = next((sig(b)[-1] for b in sig(body) if isinstance(b, Tree) and b.data == "block"
                        and name_of(sig(b)[0]) == "content"), None)
        iterator = identifier_name(attrs["iterator"]) if "iterator" in attrs else label
        block_path = ir_raw.join_path(path, label)
        if "for_each" not in attrs or content is None:
            self.diag("warn", "TF-MALFORMED-BLOCK", block_path, f"dynamic block {label} has no for_each or content")
            return
        saved, self.sink = self.sink, set()
        try:
            fe = self.eval_safe(attrs["for_each"], env)
        finally:
            pruned, self.sink = self.sink, saved
        items = self.iter_items(fe)
        if items is None:
            if fe is None:
                return
            p = ir_raw.join_path(block_path, len(lst))
            u = E.unknown_from(fe, f"for_each of dynamic block {label} is not known before apply",
                               extra_refs=self.static_refs(content))
            lst.append(self.materialize(u, p))
            return
        for to, attr, through in sorted(pruned, key=ref_order):
            self.add_ref(block_path, to, attr, "pruned", through)
        for k, v in items:
            env2 = dict(env)
            env2[iterator or label] = {"key": k, "value": v}
            lst.append(self.body_props(content, ir_raw.join_path(block_path, len(lst)), env2))

    # --- 本体
    def report_uncovered(self) -> None:
        """要約表に写していない入力（最上位の名前と、# not-covered: の入れ子の経路 listeners.*.rules など）を、
        渡された値に当たれば TF-MODULE-SUMMARY-INPUT に書く。"""
        hits = list(self._uncovered)
        unknown: list = []
        for path in self.summary.uncovered:
            parts = path.split(".")
            if len(parts) < 2 or parts[0] not in self.call_args or parts[0] not in self.variables:
                continue
            saved, self.sink = self.sink, set()
            try:
                value = self.child_var(parts[0])
            finally:
                self.sink = saved
            got = path_present(value, parts[1:])
            if got:
                hits.append(path)
            elif got is None:
                unknown.append(path)
        if unknown:
            self.diag("info", "TF-MODULE-SUMMARY-INPUT", "unknown",
                      f"inputs that the summary table does not cover could not be checked (the value is not known): "
                      f"{', '.join(sorted(unknown))}", self.call_address)
        if hits:
            self.diag("info", "TF-MODULE-SUMMARY-INPUT", "",
                      f"inputs that the summary table does not cover (resources they make are not written): "
                      f"{', '.join(sorted(set(hits)))}", self.call_address)

    def run(self) -> None:
        if self.via == "module_summary":
            self.report_uncovered()
        for base, blk in sorted(self.blocks.items()):
            if blk.kind == "data" and self.via == "module_summary":
                continue  # 要約表の中の data は載せない（4章の module_summary）
            inst = self.instances(blk)
            addr = self.prefix + base
            if inst.mode == "zero" and self.via == "module_summary":
                continue  # 要約表から展開するのは、作られるリソースだけ（4章の module_summary）
            if self.expanded(blk):
                if inst.mode == "unknown":
                    u = inst.unknown
                    self.diag("warn", "TF-COUNT-UNRESOLVED", inst.meta,
                              f"{inst.meta} is not known ({u.reason}); the module is written once with "
                              "multiplicity N", addr + "[*]")
                for k in self.child_keys(blk):
                    self.child(blk, k).run()
                continue
            if inst.mode == "single":
                self.emit(blk, inst, addr, True, {})
            elif inst.mode == "count":
                for k in inst.keys:
                    self.emit(blk, inst, inst_address(addr, k), True, {"count": {"index": k}})
            elif inst.mode == "each":
                for k in inst.keys:
                    self.emit(blk, inst, inst_address(addr, k), True,
                              {"each": {"key": k, "value": inst.values[k]}})
            else:
                why = ("count is 0" if inst.meta == "count" else "for_each is empty") if inst.mode == "zero" else \
                    f"{inst.meta} is not known"
                u = Unknown(f"{'count.index' if inst.meta == 'count' else 'each'} is not known ({why})",
                            "TF-COUNT-INDEX", "info")
                env = {"count": {"index": u}} if inst.meta == "count" else {"each": {"key": u, "value": u}}
                if inst.mode == "zero":
                    self.emit(blk, inst, addr, False, env)
                else:
                    self.emit(blk, inst, addr + "[*]", None, env)
        self.ctx.refs += self.extra_refs
        self.extra_refs = []

    def emit(self, blk: Block, inst: Instances, address: str, enabled, env: dict) -> None:
        ctx = self.ctx
        enabled = weakest(enabled, self.enabled_base)
        if blk.kind == "module" and "create" in blk.attrs and self.create_convention(blk):
            # 黒箱の呼び出しで、create 引数（terraform-aws-modules の慣習。false なら何も作らない）が false と決まる
            # ものは作られない。決まらなければ、count が決まらないときと同じく null（7.2）
            c = self.quiet_eval(blk.attrs["create"], env)
            if c is False or c == "false":
                enabled = weakest(enabled, False)
                self.diag("info", "TF-MODULE-NOT-CREATED", "create",
                          "create is false; the module call makes nothing (terraform-aws-modules convention)", address)
            elif not (c is True or c == "true"):
                enabled = weakest(enabled, None)
                self.diag("info", "TF-MODULE-NOT-CREATED", "create",
                          "create is not known; whether the module makes anything is not known", address)
        self.current = address
        self.current_enabled = enabled
        entry: dict = {"address": address, "type": blk.type, "file": blk.file, "enabled": enabled}
        if self.via:
            entry["via"] = self.via
        if self.prefix:
            entry["module"] = self.prefix[:-1]
        if inst.mode == "unknown" or self.multi:
            entry["multiplicity"] = "N"
        if inst.mode == "unknown":
            u = inst.unknown
            for to, attr, through in sorted(u.refs, key=ref_order):
                self.add_ref(inst.meta, to, attr, "unevaluated", through)
            self.diag("warn", "TF-COUNT-UNRESOLVED", inst.meta,
                      f"{inst.meta} is not known ({u.reason}); written as one block with multiplicity N")
        region = None
        if blk.kind == "module":  # 黒箱のモジュールの呼び出し（2章）
            meta = MODULE_META
            entry["via"] = "module_blackbox"
            source = const(blk.attrs["source"]) if "source" in blk.attrs else NOTCONST
            version = const(blk.attrs["version"]) if "version" in blk.attrs else NOTCONST
            if isinstance(source, str) and source:
                entry["source"] = source
                if isinstance(version, str) and version:
                    entry["version"] = version
            plan = self.module_plan(blk)
            self.diag(plan[1], plan[2], "source" if plan[2] == "TF-MALFORMED-BLOCK" else "", plan[3])
            if "providers" in blk.attrs:  # 中身の既定の provider（aws）を別の provider にした呼び出し
                target = self.providers_arg(blk.attrs["providers"], address).get("aws")
                if target and "." in target:
                    entry["provider"] = target
                    region = self.provider_region(self.resolve_provider(target))
        else:
            meta = RESOURCE_META if blk.kind == "resource" else DATA_META
            explicit = self.provider_name(blk.attrs["provider"]) if "provider" in blk.attrs else None
            if "provider" in blk.attrs and explicit is None:
                self.diag("warn", "TF-MALFORMED-BLOCK", "provider", "provider is not a provider reference")
            name = explicit or blk.type.split("_", 1)[0]
            found = self.resolve_provider(name)
            if found is not None:
                pmod, pname = found
                # 既定の provider（alias の無いもの）は書かない。リージョンはルートの既定の provider 以外なら書く
                if "." in pname:
                    entry["provider"] = pname
                if "." in pname or pmod.parent is not None:
                    region = self.provider_region(found)
            elif explicit and "." in explicit:
                entry["provider"] = explicit
                self.diag("info", "TF-PROVIDER-UNCONFIGURED", "provider",
                          f"provider {explicit} has no configuration in this module or its callers; "
                          "region is not known")
            # AWS provider v6 のリソースの引数 region は、provider の region より優先する（Terraform と同じ）
            if blk.type.startswith("aws_") and "region" in blk.attrs:
                r = self.quiet_eval(blk.attrs["region"], env)
                if isinstance(r, str):
                    region = r
        if isinstance(region, str) and region:
            entry["region"] = region
        props = self.body_props(blk.body, "", env, meta)
        entry["props"] = collect_active(props, address, ctx.refs)
        if "depends_on" in blk.attrs:
            for a in self.depends_targets(blk.attrs["depends_on"], self):
                ctx.refs.append({"from": address, "path": "depends_on", "to": a, "attr": None,
                                 "fn": "depends_on", "state": "active"})
        for a in self.inherited_depends():
            ctx.refs.append({"from": address, "path": "depends_on", "to": a, "attr": None,
                             "fn": "depends_on", "state": "active"})
        ctx.resources.append(entry)

    def create_convention(self, blk: Block) -> bool:
        """create 引数を「false なら何も作らない」と読んでよい呼び出しか（terraform-aws-modules と、要約表の中）。"""
        if self.via == "module_summary":
            return True
        source = const(blk.attrs["source"]) if "source" in blk.attrs else NOTCONST
        key = M.registry_key(source) if isinstance(source, str) else None
        return bool(key and key.startswith("terraform-aws-modules/"))

    def provider_region(self, found) -> str | None:
        """provider の設定（resolve_provider の結果）の region。文字列で決まらなければ None。"""
        if found is None:
            return None
        pmod, pname = found
        conf_attrs = pmod.body_attrs(pmod.providers[pname])
        if "region" not in conf_attrs:
            return None
        r = pmod.quiet_eval(conf_attrs["region"], {})
        return r if isinstance(r, str) else None

    def inherited_depends(self) -> list[str]:
        """モジュールの呼び出しの depends_on（入れ子の呼び出しのものも）の先の address。中のすべてのリソースに付ける。"""
        if self._dep_cache is None:
            out: list[str] = []
            for mod, expr in self.depends_from:
                out += mod.depends_targets(expr, self)
            self._dep_cache = sorted(set(out))
        return self._dep_cache
    def quiet_eval(self, expr, env: dict):
        """参照や診断を残さずに値だけを見る（provider・region）。"""
        saved, self.sink = self.sink, set()
        try:
            return self.eval_safe(expr, env)
        finally:
            self.sink = saved

    @staticmethod
    def provider_name(expr) -> str | None:
        """メタ引数 provider の値（aws.us_east_1）。古い書き方の文字列（"aws.us_east_1"）も読む。読めなければ None。"""
        root, steps = flatten(expr)
        if isinstance(root, Tree) and root.data == "identifier" and all(s[0] == "attr" for s in steps) \
                and len(steps) <= 1:
            return ".".join([name_of(root)] + [s[1] for s in steps])
        v = const(expr)
        if isinstance(v, str) and re.fullmatch(r"[a-z0-9_-]+(\.[A-Za-z0-9_-]+)?", v):
            return v
        return None

    def depends_targets(self, expr, where: "ModuleEval") -> list[str]:
        """depends_on の先の address。展開するモジュールなら、その中のすべてのリソース。where は診断を書くモジュール。"""
        items = sig(unwrap(expr)) if isinstance(unwrap(expr), Tree) and unwrap(expr).data == "tuple" else []
        out: list[str] = []
        for el in items:
            root, steps = flatten(el)
            name = name_of(root) if isinstance(root, Tree) and root.data == "identifier" else None
            first = steps[0][1] if steps and steps[0][0] == "attr" else None
            if name == "data":
                base = f"data.{first}.{steps[1][1] if len(steps) > 1 and steps[1][0] == 'attr' else ''}"
            elif name == "module":
                base = f"module.{first}"
            else:
                base = f"{name}.{first}"
            blk = self.blocks.get(base) if name and first else None
            if blk is not None:
                if self.expanded(blk):
                    for k in self.child_keys(blk):
                        out += self.child(blk, k).resource_addresses()
                else:
                    out += self.all_addresses(blk)
            elif name == "ephemeral":
                continue
            else:
                text = name or "an expression"
                if first:
                    text += f".{first}"
                where.diag("warn", "TF-UNDEFINED-REF", "depends_on",
                           f"depends_on to {text} is not a resource, a data source or a module in this module")
        return out


def path_present(value, parts: list):
    """value の中に、経路 parts（"*" はどのキー・要素でもよい）の値（null・空の {}・[] 以外）があるか。
    True／False と、途中や葉の値が決まらず調べられなかったときは None（ほかに当たるものが無いとき）。"""
    if isinstance(value, Unknown):
        return None
    if not parts:
        return value is not None and value != {} and value != []
    head, rest = parts[0], parts[1:]
    if head == "*":
        if isinstance(value, dict):
            items = list(value.values())
        elif isinstance(value, list):
            items = value
        else:
            return None if not (value is None or E.is_concrete(value)) else False
        got = [path_present(v, rest) for v in items]
        return True if True in got else None if None in got else False
    if isinstance(value, dict):
        return path_present(value[head], rest) if head in value else False
    return None if not (value is None or E.is_concrete(value)) else False


def merge_body(base: Tree, over: Tree) -> Tree:
    """override のファイルの規則で、ブロックの本体を重ねる（属性は置き換え、入れ子のブロックは同じ種類のものを
    すべて置き換える。dynamic "x" は x の種類として扱う）。"""
    def key(item):
        cs = sig(item)
        if item.data == "attribute":
            return ("attr", name_of(cs[0]))
        btype = name_of(cs[0])
        if btype == "dynamic" and len(cs) >= 3:
            btype = label_text(cs[1])
        return ("block", btype)

    over_items = [c for c in sig(over) if isinstance(c, Tree) and c.data in ("attribute", "block")]
    over_keys = {key(c) for c in over_items}
    kept = [c for c in sig(base) if isinstance(c, Tree) and c.data in ("attribute", "block")
            and key(c) not in over_keys]
    return Tree("body", kept + over_items)


# ------------------------------------------------------------------ raw IR の組み立て

_SUMMARY_TREES: dict = {}


def summary_tree(summary: M.Summary) -> Tree:
    """要約表の HCL の構文木（1回だけ読む）。"""
    key = (summary.source, summary.majors, summary.line)
    if key not in _SUMMARY_TREES:
        _SUMMARY_TREES[key] = hcl2.parses_to_tree(summary.text)
    return _SUMMARY_TREES[key]


def collect_active(props, frm: str, out: list[dict]):
    """props の中の $res を active の参照にし、一時的な __through を references の through に移した props を返す。"""
    def strip(v, path):
        if isinstance(v, list):
            return [strip(x, ir_raw.join_path(path, i)) for i, x in enumerate(v)]
        if isinstance(v, dict):
            if "$res" in v:
                ref = {"from": frm, "path": path, "to": v["$res"], "attr": v.get("attr"), "fn": "ref",
                       "state": "active"}
                if v.get("__through"):
                    ref["through"] = list(v["__through"])
                out.append(ref)
                return {"$res": v["$res"], "attr": v.get("attr")}
            if "$concat" in v:
                return {"$concat": [strip(x, path) if isinstance(x, dict) else x for x in v["$concat"]]}
            if "$json" in v:
                return {"$json": strip(v["$json"], path)}
            if ir_raw.is_marker(v):
                return v
            return {k: strip(x, ir_raw.join_path(path, ir_raw.unescape_key(k))) for k, x in v.items()}
        return v
    return strip(props, "")


def _dedupe(refs: list[dict]) -> list[dict]:
    rank = {"active": 2, "unevaluated": 1, "pruned": 0}
    seen: dict[tuple, dict] = {}
    for r in refs:
        key = ir_raw.ref_key(r)
        if key not in seen or rank[r["state"]] > rank[seen[key]["state"]]:
            seen[key] = r
    return list(seen.values())


def auto_var_files(input_dir: Path) -> list[Path]:
    """Terraform が自動で読む変数のファイル（terraform.tfvars、terraform.tfvars.json、*.auto.tfvars(.json) の名前順）。"""
    out = [input_dir / n for n in ("terraform.tfvars", "terraform.tfvars.json") if (input_dir / n).is_file()]
    autos = sorted(p for p in input_dir.iterdir() if p.is_file()
                   and (p.name.endswith(".auto.tfvars") or p.name.endswith(".auto.tfvars.json")))
    return out + autos


def var_file_candidates(input_dir: Path) -> list[Path]:
    """自動では読まれない変数のファイル（ルートとその1つ下のフォルダの *.tfvars・*.tfvars.json）。"""
    out = []
    dirs = [input_dir] + sorted(p for p in input_dir.iterdir() if p.is_dir() and not p.name.startswith("."))
    for d in dirs:
        for p in sorted(d.iterdir()):
            name = p.name
            if not p.is_file() or name.startswith("."):
                continue
            if not (name.endswith(".tfvars") or name.endswith(".tfvars.json")):
                continue
            if d == input_dir and (name in ("terraform.tfvars", "terraform.tfvars.json")
                                   or name.endswith((".auto.tfvars", ".auto.tfvars.json"))):
                continue
            out.append(p)
    return out


def resolve_var_file(path: Path, input_dir: Path) -> Path:
    """--var-file のパス。相対パスは作業中のフォルダから、無ければ --input のフォルダから。"""
    if path.is_absolute() or path.is_file():
        return path
    alt = input_dir / path
    return alt if alt.is_file() else path


def build_raw(input_dir: Path, root_base: Path | None = None, var_files: list | None = None,
              vars: dict | None = None, var_args: list | None = None, redact_vars=(),
              plan: Path | None = None) -> dict:
    """ルートモジュールのフォルダから raw IR を作る。

    var_files・vars: 外から渡す変数の値（--var-file、--var）。この順に（vars が後で）重ねる。
    var_args: コマンドラインの順のまま渡すとき。("file", パス) と ("var", "K=V") の並び（var_files・vars より後）。
    plan: 同じ構成の plan JSON（--plan）。変数の値は plan の variables を使い（var_files・vars・var_args はその後に
    重ねる）、address と作られるかは plan に合わせる（lib/tf_plan.py の combine。ir-schema.md の 7.2）。
    """
    plan_doc = P.load_plan(plan) if plan is not None else None
    ctx = Context(input_dir)
    mod = ModuleEval(ctx, input_dir)
    mod.chain = (input_dir.resolve(),)
    mod.load()
    sources: list = [("file", p) for p in auto_var_files(input_dir)]
    if plan_doc is not None:
        sources += [("plan", (k, v)) for k, v in sorted(P.plan_variables(plan_doc).items())]
    sources += [("file", resolve_var_file(Path(p), input_dir)) for p in (var_files or [])]
    sources += [("value", (k, v)) for k, v in (vars or {}).items()]
    for kind, item in var_args or []:
        sources.append(("file", resolve_var_file(Path(item), input_dir)) if kind == "file" else ("var", item))
    for kind, item in sources:
        if kind == "file" and not Path(item).is_file():
            raise ValueError(f"変数のファイルがありません: {item}")
    mod.setup_variables(sources, redact_vars)
    missing = sorted(n for n, v in mod.var_values.items() if isinstance(v, Unknown) and v.code == "TF-UNRESOLVED-VAR")
    if missing:
        # 環境ごとの変数のファイル（env/dev.tfvars など）があれば、どれを渡すかを確かめられるように候補を書く（A4）
        read = {Path(item).resolve() for kind, item in sources if kind == "file"}
        cands = sorted(ctx.rel(p) for p in var_file_candidates(input_dir) if p.resolve() not in read)
        message = f"variables without a value: {', '.join(missing)}"
        if cands:
            message += f"; var files that are not read automatically (pass one with --var-file): {', '.join(cands)}"
        ctx.diagnostics.append({"level": "info", "code": "TF-UNRESOLVED-VARS", "address": "", "path": "",
                                "message": message})
    mod.run()
    # Windows でドライブが違うと相対パスにできない: フォルダの名前だけを書く（絶対パスは書かない。plan JSON だけの
    # ときと同じ規則）
    root, relative = P.root_text(input_dir, root_base or Path.cwd())
    if not relative:
        ctx.diagnostics.append({"level": "info", "code": "TF-ROOT-OTHER-DRIVE", "address": "", "path": "",
                                "message": P.ROOT_OTHER_DRIVE_MESSAGE})
    diagnostics = list({(d.get("address", ""), d.get("path", ""), d["code"], d["message"]): d
                        for d in ctx.diagnostics}.values())
    # 変数の値は書かない（名前と値の出どころだけ。秘密の値を IR に残さないため）。手元のモジュールの変数は
    # module.x.<名前> の形で足す（要約表の変数は書かない）
    used = dict(mod.var_sources)
    for child in ctx.modules:
        if child.via is None:
            used.update({child.prefix + n: e for n, e in child.var_sources.items()})
    used = dict(sorted(used.items()))
    raw = {
        "ir_version": "1.0",
        "stage": "raw",
        "format": "tf",
        "root": root,
        "evaluation": {"var_files": mod.var_files, "vars": used, "assumptions": ctx.assumptions},
        "resources": ctx.resources,
        "references": _dedupe(ctx.refs),
        "diagnostics": diagnostics,
    }
    if plan is not None:
        return P.combine(raw, plan, input_dir, root_base, plan_doc)
    return ir_raw.canonical_raw(raw)


def build_from_plan(plan: Path, root_base: Path | None = None) -> dict:
    """plan JSON だけから raw IR を作る（--input に plan JSON を渡したとき。lib/tf_plan.py）。"""
    return P.build_plan_raw(plan, root_base)


def dump(raw: dict) -> str:
    return json.dumps(raw, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


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
    ap.add_argument("--var", action=_OrderedVar, dest="var_args", metavar="KEY=VALUE",
                    help="変数の値（何回でも指定できる。--var-file と合わせて、後のものが優先）")
    a = ap.parse_args(argv)
    var_args = a.var_args or []
    for kind, item in var_args:
        if kind == "var" and "=" not in item:
            print(f"--var は KEY=VALUE の形で指定してください: {item}", file=sys.stderr)
            return 2
    plan_only = a.input.is_file()
    if plan_only and not P.is_plan_file(a.input):
        why = P.why_unreadable(a.input) if a.input.suffix.lower() == ".json" else None
        if why:
            print(f"plan JSON を読めませんでした: {why}", file=sys.stderr)
            return 2
        print(f"--input には、ルートモジュールのフォルダか plan JSON（terraform show -json の出力の .json）を指定して"
              f"ください: {a.input.name}", file=sys.stderr)
        return 2
    if plan_only and (a.plan is not None or var_args or a.redact_var):
        print("--input に plan JSON を渡したときは、--plan・--var-file・--var・--redact-var は使えません（変数の値は "
              "plan のものを使う。値を伏せるには .tf のフォルダを --input に、plan JSON を --plan に渡す）",
              file=sys.stderr)
        return 2
    try:
        if plan_only:
            raw = build_from_plan(a.input, a.root_base)
        else:
            raw = build_raw(a.input, a.root_base, var_args=var_args, redact_vars=a.redact_var, plan=a.plan)
        text = dump(raw)
    except P.PlanError as e:
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
