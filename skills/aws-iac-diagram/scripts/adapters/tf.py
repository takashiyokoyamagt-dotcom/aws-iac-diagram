# /// script
# requires-python = ">=3.12"
# dependencies = ["python-hcl2==8.1.4"]
# ///
"""Terraform のルートモジュール（.tf のフォルダ）を読み、アダプタの出力（raw IR。references/ir-schema.md の 7章）を作る。

いまの範囲（フェーズ2 の手順1〜2）:
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
後の手順に回したもの:
  - 手順3: module の中身は読まない。呼び出し（インスタンスごと）を type: module・via: module_blackbox の1件に
    する（source・version、props は入力。診断 TF-MODULE-DEFERRED）。module.x.out への参照は
    {"$res": "module.x", "attr": "out"}。.tf.json は読まない（TF-TFJSON-UNSUPPORTED）
  - 手順4: plan JSON
file()・templatefile() などのファイルを読む関数は、ファイルを読まずに $unknown（診断 TF-UNEVALUATED）。
引数の中の参照は unevaluated で残す。sensitive = true・ephemeral = true の変数と sensitive() の値は使わない
（$unknown。evaluation.vars にも書かない）。

使い方:
  uv run scripts/adapters/tf.py --input <ルートモジュールのフォルダ> --out <raw.json> [--root-base <フォルダ>]
      [--var-file <ファイル> ...] [--var KEY=VALUE ...] [--redact-var <名前> ...]
  --root-base: raw IR の root を、このフォルダからの相対パスで書く（既定: 作業中のフォルダ）
  --var-file: 変数の値のファイル（.tfvars か .tfvars.json）。相対パスは作業中のフォルダ、無ければ --input から
  --var: 変数の値。type が list・map・object などの変数は HCL の式として読む（Terraform の -var と同じ）
  --var-file と --var は、指定した順に後のものが優先する（Terraform と同じ）
  --redact-var: 値を伏せる変数（sensitive = true と同じく値を使わず、props では $unknown）。
    sensitive を付けていない変数の値は props（図のラベルなど）に入りうる。evaluation.vars には値を書かない

終了コード: 0 = 書けた（diagnostics に warn・error があっても）、2 = フォルダや変数のファイルを読めなかった
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import hcl2
from lark import Token, Tree

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import ir_raw  # noqa: E402
from lib import tf_eval as E  # noqa: E402
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

    def rel(self, path: Path) -> str:
        try:
            return Path(os.path.relpath(path, self.root_dir)).as_posix()
        except ValueError:  # Windows でドライブが違う
            return Path(path).resolve().as_posix()

    def assume(self, text: str) -> None:
        if text not in self.assumptions:
            self.assumptions.append(text)


class ModuleEval:
    """1つのモジュール（手順2 まではルートモジュールだけ）のブロックを集めて評価する。"""

    def __init__(self, ctx: Context, directory: Path, prefix: str = ""):
        self.ctx = ctx
        self.dir = directory
        self.prefix = prefix  # address の前に付けるもの（手順3 のモジュールの "module.x."）
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
        self._local_cache: dict[str, tuple] = {}
        self._inst_cache: dict[str, Instances] = {}
        self._busy: set = set()

    # --- 診断と参照
    def diag(self, level: str, code: str, path: str, message: str, address: str | None = None) -> None:
        self.ctx.diagnostics.append({"level": level, "code": code,
                                     "address": self.current if address is None else address,
                                     "path": path, "message": message})

    def add_ref(self, path: str, to: str, attr, state: str) -> None:
        self.extra_refs.append({"from": self.current, "path": path, "to": to, "attr": attr, "fn": "ref",
                                "state": state})

    # --- 読み込み
    def load(self) -> None:
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
            # output・terraform・moved・import・removed などは使わない

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
            elif kind == "value":  # build_raw の vars（値をそのまま渡す）
                name, value = item
                if name not in self.variables:
                    self.diag("warn", "TF-VAR-UNDECLARED", "", f"variable {name} is not declared", "")
                    continue
                given[name], origin[name] = value, "--var"
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
            return Path(os.path.relpath(path, self.ctx.root_dir)).as_posix()
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
        return self.var_values.get(name, Unknown(f"variable {name} has no value", "TF-UNRESOLVED-VAR"))

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
        try:
            v = self.eval_safe(self.locals[name], {})
        finally:
            pruned, self.sink = self.sink, saved
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
        if inst.mode in ("count", "each"):
            return [inst_address(base, k) for k in inst.keys]
        if inst.mode == "unknown":
            return [base + "[*]"]
        return [base]

    def block_value(self, blk: Block):
        """リソース・data・module の参照の値（インスタンスごとの Res のまとまり）。"""
        base = self.prefix + blk.base
        inst = self.instances(blk)
        if inst.mode == "single":
            return Res(base)
        if inst.mode == "count":
            return ResList(Res(inst_address(base, k)) for k in inst.keys)
        if inst.mode == "each":
            return ResMap((k, Res(inst_address(base, k))) for k in inst.keys)
        if inst.mode == "zero":
            return ZeroColl(Res(base))
        return Res(base + "[*]", None, True)

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
        kept = {block_address(to) for to, _ in E.refs_in(after)}
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
            try:
                v = self.eval(a, env)
            except EvalError:
                self.sink = saved
                failed |= self.static_refs(a)
                continue
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
        try:
            v = self.eval(arg_trees[0], env)
        except EvalError:
            return False
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
        return self.traverse(self.block_value(blk), rest, env)

    def traverse(self, v, steps: list, env: dict):
        for st in steps:
            v = self.step(v, st, env)
        return v

    def step(self, v, st, env: dict):
        kind = st[0]
        if isinstance(v, Unknown):
            return v
        if kind == "attr":
            name = st[1]
            if isinstance(v, Res):
                return v if v.attr is not None else Res(v.to, name)
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
                return Res(v.to, None) if v.multi else v
            if isinstance(v, ZeroColl):
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
                return self.traverse(Res(v.to, None), sub, env)
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
            out.add((a, attr))

    # --- 書き出し（印への変換）
    def materialize(self, v, path: str):
        """評価した値を raw IR の値にする。Unknown は $unknown にし、中の参照を unevaluated で残して診断を書く。"""
        if isinstance(v, Unknown):
            for to, attr in sorted(v.refs, key=lambda x: (x[0], x[1] or "")):
                self.add_ref(path, to, attr, "unevaluated")
            reason = v.reason or "the value is not known"
            # 作られないリソース（count が 0 など）は Terraform も評価しないので、図に影響しない（info にする）
            level = "info" if self.current_enabled is False and v.level == "warn" and v.code in UNDECIDED else v.level
            self.diag(level, v.code, path, reason)
            return {"$unknown": reason}
        if isinstance(v, Res):
            return {"$res": v.to, "attr": v.attr}
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
        for to, attr in sorted(pruned, key=lambda x: (x[0], x[1] or "")):
            self.add_ref(path, to, attr, "pruned")
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
        for to, attr in sorted(pruned, key=lambda x: (x[0], x[1] or "")):
            self.add_ref(block_path, to, attr, "pruned")
        for k, v in items:
            env2 = dict(env)
            env2[iterator or label] = {"key": k, "value": v}
            lst.append(self.body_props(content, ir_raw.join_path(block_path, len(lst)), env2))

    # --- 本体
    def run(self) -> None:
        for base, blk in sorted(self.blocks.items()):
            inst = self.instances(blk)
            addr = self.prefix + base
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

    def emit(self, blk: Block, inst: Instances, address: str, enabled, env: dict) -> None:
        ctx = self.ctx
        self.current = address
        self.current_enabled = enabled
        entry: dict = {"address": address, "type": blk.type, "file": blk.file, "enabled": enabled}
        if inst.mode == "unknown":
            entry["multiplicity"] = "N"
            u = inst.unknown
            for to, attr in sorted(u.refs, key=lambda x: (x[0], x[1] or "")):
                self.add_ref(inst.meta, to, attr, "unevaluated")
            self.diag("warn", "TF-COUNT-UNRESOLVED", inst.meta,
                      f"{inst.meta} is not known ({u.reason}); written as one block with multiplicity N")
        if blk.kind == "module":
            meta = MODULE_META
            entry["via"] = "module_blackbox"
            source = const(blk.attrs["source"]) if "source" in blk.attrs else NOTCONST
            version = const(blk.attrs["version"]) if "version" in blk.attrs else NOTCONST
            if isinstance(source, str) and source:
                entry["source"] = source
                if isinstance(version, str) and version:
                    entry["version"] = version
            else:
                self.diag("warn", "TF-MALFORMED-BLOCK", "source", "module has no constant source")
            self.diag("info", "TF-MODULE-DEFERRED", "",
                      "module contents are not read yet (phase 2 step 3); recorded as one module call")
        else:
            meta = RESOURCE_META if blk.kind == "resource" else DATA_META
            region = None
            if "provider" in blk.attrs:
                provider = self.provider_name(blk.attrs["provider"])
                # provider = aws は既定の provider と同じなので書かない（alias のあるものだけ）
                if provider and "." in provider:
                    entry["provider"] = provider
                    conf = self.providers.get(provider)
                    if conf is not None:
                        conf_attrs = self.body_attrs(conf)
                        if "region" in conf_attrs:
                            region = self.quiet_eval(conf_attrs["region"], {})
                    else:  # モジュールでは呼び出し側から渡される（configuration_aliases。手順3）
                        self.diag("info", "TF-PROVIDER-UNCONFIGURED", "provider",
                                  f"provider {provider} has no configuration in this module; region is not known")
                elif provider is None:
                    self.diag("warn", "TF-MALFORMED-BLOCK", "provider", "provider is not a provider reference")
            # AWS provider v6 のリソースの引数 region は、provider の region より優先する（Terraform と同じ）
            if blk.type.startswith("aws_") and "region" in blk.attrs:
                r = self.quiet_eval(blk.attrs["region"], env)
                if isinstance(r, str):
                    region = r
            if isinstance(region, str) and region:
                entry["region"] = region
        props = self.body_props(blk.body, "", env, meta)
        entry["props"] = props
        for p, to, attr in ir_raw.iter_res(props, ""):
            ctx.refs.append({"from": address, "path": p, "to": to, "attr": attr, "fn": "ref", "state": "active"})
        if "depends_on" in blk.attrs:
            self.depends_on(blk.attrs["depends_on"])
        ctx.resources.append(entry)

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

    def depends_on(self, expr) -> None:
        items = sig(unwrap(expr)) if isinstance(unwrap(expr), Tree) and unwrap(expr).data == "tuple" else []
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
                for a in self.all_addresses(blk):
                    self.ctx.refs.append({"from": self.current, "path": "depends_on", "to": a, "attr": None,
                                          "fn": "depends_on", "state": "active"})
            elif name == "ephemeral":
                continue
            else:
                text = name or "an expression"
                if first:
                    text += f".{first}"
                self.diag("warn", "TF-UNDEFINED-REF", "depends_on",
                          f"depends_on to {text} is not a resource, a data source or a module in this module")


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
              vars: dict | None = None, var_args: list | None = None, redact_vars=()) -> dict:
    """ルートモジュールのフォルダから raw IR を作る。

    var_files・vars: 外から渡す変数の値（--var-file、--var）。この順に（vars が後で）重ねる。
    var_args: コマンドラインの順のまま渡すとき。("file", パス) と ("var", "K=V") の並び（var_files・vars より後）。
    """
    ctx = Context(input_dir)
    mod = ModuleEval(ctx, input_dir)
    mod.load()
    sources: list = [("file", p) for p in auto_var_files(input_dir)]
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
    root_base = root_base or Path.cwd()
    try:
        root = Path(os.path.relpath(input_dir.resolve(), root_base.resolve())).as_posix()
    except ValueError:  # Windows でドライブが違うと相対パスにできない
        root = input_dir.resolve().as_posix()
        ctx.diagnostics.append({"level": "info", "code": "TF-ABSOLUTE-ROOT", "address": "", "path": "",
                                "message": "root is on another drive; written as an absolute path"})
    diagnostics = list({(d.get("address", ""), d.get("path", ""), d["code"], d["message"]): d
                        for d in ctx.diagnostics}.values())
    # 変数の値は書かない（名前と値の出どころだけ。秘密の値を IR に残さないため）
    used = dict(sorted(mod.var_sources.items()))
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
    return ir_raw.canonical_raw(raw)


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
    ap = argparse.ArgumentParser(description="Terraform のルートモジュールから raw IR を作る")
    ap.add_argument("--input", required=True, type=Path, help="ルートモジュールのフォルダ")
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
    try:
        raw = build_raw(a.input, a.root_base, var_args=var_args, redact_vars=a.redact_var)
    except (OSError, ValueError) as e:
        print(f"Terraform のフォルダを読めませんでした: {a.input}: {e}", file=sys.stderr)
        return 2
    except Exception as e:  # noqa: BLE001  想定外の失敗も終了コード 2 で返す
        print(f"Terraform の評価に失敗しました: {a.input}: {type(e).__name__}: {e}", file=sys.stderr)
        return 2
    try:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(dump(raw), encoding="utf-8", newline="\n")
    except OSError as e:
        print(f"raw IR を書けませんでした: {a.out}: {e}", file=sys.stderr)
        return 2
    print(f"raw: resources={len(raw['resources'])} references={len(raw['references'])} "
          f"diagnostics={len(raw['diagnostics'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
