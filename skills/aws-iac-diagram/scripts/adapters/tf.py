# /// script
# requires-python = ">=3.12"
# dependencies = ["python-hcl2==8.1.4"]
# ///
"""Terraform のルートモジュール（.tf のフォルダ）を読み、アダプタの出力（raw IR。references/ir-schema.md の 7章）を作る。

いまの範囲（フェーズ2 の手順1: 土台）:
  - フォルダ直下の *.tf を python-hcl2 で読み（構文木をそのまま使う）、resource・data・module のブロックを集める
  - 属性とブロックを props にする（ブロックはリスト。count・for_each・provider・depends_on・lifecycle・
    provisioner・connection はメタ引数なので props に入れない）
  - 参照を印にする: resource・data・module への参照は $res（attr は最初の属性名）、data.aws_region・
    aws_caller_identity・aws_partition は $pseudo（CFN と同じ名前）、data.aws_availability_zones の names は $az、
    jsonencode(...) は $json、"${…}" と heredoc は $concat（JSON として読めれば $json）。depends_on は references にだけ
  - path.module・path.root・path.cwd はルートからの相対パス（ルートは "."）、terraform.workspace は "default"
  - provider = aws.<alias> のリソースは provider を書く。region は、リソースの引数 region（AWS provider v6）→
    その provider の region の順で、文字列で決まるときだけ書く
  - heredoc の開始・終端の行の末尾の空白を取ってから読む（python-hcl2 が読めないため。7.4。診断 info）
後の手順に回したもの（いまは「評価していない」と分かる形で出す）:
  - 手順2（A4）: var・local・count.index・each・関数（jsonencode 以外）・条件式・演算・for 式・テンプレートの
    %{…}・dynamic ブロックは $unknown（診断 TF-DEFERRED。中の参照は state: "unevaluated" で残す。local は中の式を
    たどって参照を探す）。count・for_each のあるブロックは ×N（address は [*]、multiplicity: "N"、enabled: null。
    診断 TF-COUNT-DEFERRED）。インスタンスへの参照（aws_subnet.public[0]）とスプラットも [*] への1つの $res
  - 手順3: module の中身は読まない。呼び出しを type: module・via: module_blackbox の1件にする（source・version、
    props は入力。診断 TF-MODULE-DEFERRED）。module.x.out への参照は {"$res": "module.x", "attr": "out"}
  - 手順4: plan JSON
file()・templatefile() などのファイルを読む関数は、ファイルを読まずに $unknown（診断 TF-UNEVALUATED）。
引数の中の参照は unevaluated で残す。

使い方:
  uv run scripts/adapters/tf.py --input <ルートモジュールのフォルダ> --out <raw.json> [--root-base <フォルダ>]
  --root-base: raw IR の root を、このフォルダからの相対パスで書く（既定: 作業中のフォルダ）

終了コード: 0 = 書けた（diagnostics に warn・error があっても）、2 = フォルダを読めなかった（.tf が無いなど）
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
# ファイルを読む関数（ファイルは読まない。7.2）
FILE_FUNCTIONS = {"file", "filebase64", "templatefile", "fileexists", "fileset", "filemd5", "filesha1",
                  "filesha256", "filesha512", "filebase64sha256", "filebase64sha512"}
# 評価しない式の種類（手順2 で評価する）
EXPR_KINDS = {"conditional": "conditional expression", "binary_op": "operator expression",
              "unary_op": "operator expression", "for_tuple_expr": "for expression",
              "for_object_expr": "for expression", "template_string": "template expression"}
DEFERRED = "not evaluated yet (phase 2 step 2)"
NOTCONST = object()
OPEN_HEREDOC = re.compile(r"<<-?([A-Za-z][A-Za-z0-9._-]*)([ \t]+)?$")
ESCAPE = re.compile(r"\\(u[0-9a-fA-F]{4}|U[0-9a-fA-F]{8}|.)", re.S)
SIMPLE_ESCAPES = {"n": "\n", "r": "\r", "t": "\t", '"': '"', "\\": "\\"}


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
        if op == "-" and isinstance(operand, (int, float)) and not isinstance(operand, bool):
            return -operand
        if op == "!" and isinstance(operand, bool):
            return not operand
        return NOTCONST
    if d == "tuple":
        vals = [const(c) for c in sig(t)]
        return NOTCONST if any(v is NOTCONST for v in vals) else vals
    return NOTCONST


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
    """テンプレートの ${…} の中の式を読む。読めなければ None。"""
    if src not in _EXPR_CACHE:
        try:
            tree = hcl2.parses_to_tree(f"__x = {src}\n")
            attr = sig(sig(tree)[0])[0]
            _EXPR_CACHE[src] = sig(attr)[-1]
        except Exception:  # noqa: BLE001  python-hcl2 は lark の例外をそのまま投げる
            _EXPR_CACHE[src] = None
    return _EXPR_CACHE[src]


def split_template(text: str) -> list:
    """heredoc の中身を、文字列・("expr", 式の木か None)・("directive", 式の木か None) に分ける。"""
    pieces: list = []
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
            inner = text[i + 2:j].strip().strip("~").strip()
            if buf:
                pieces.append("".join(buf))
                buf = []
            if text[i] == "$":
                pieces.append(("expr", parse_expr(inner)))
            else:  # %{ if … }・%{ for x in … } の式（参照を探すためだけに読む）
                src = ""
                if inner.startswith("if "):
                    src = inner[3:]
                elif inner.startswith("for ") and " in " in inner:
                    src = inner.split(" in ", 1)[1]
                pieces.append(("directive", parse_expr(src) if src else None))
            i = j + 1
            continue
        buf.append(text[i])
        i += 1
    if buf:
        pieces.append("".join(buf))
    return pieces


def string_pieces(t: Tree) -> list:
    """クォートした文字列を、文字列・("expr", 式の木)・("directive", 木) に分ける。"""
    pieces: list = []
    for part in t.children:
        if not (isinstance(part, Tree) and part.data == "string_part"):
            continue
        for c in part.children:
            if isinstance(c, Token):
                if c.type == "STRING_CHARS":
                    pieces.append(_unescape(str(c)))
                else:  # ESCAPED_INTERPOLATION（$${）・ESCAPED_DIRECTIVE（%%{）
                    pieces.append(str(c)[1:])
            elif c.data == "interpolation":
                pieces.append(("expr", sig(c)[0]))
            else:
                pieces.append(("directive", c))
    return pieces


# ------------------------------------------------------------------ ブロック

@dataclass
class Block:
    kind: str  # resource／data／module
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
        return f"{self.type}.{self.name}"

    @property
    def multi(self) -> bool:
        """count・for_each がある（手順1 では評価しないので ×N）。"""
        return "count" in self.attrs or "for_each" in self.attrs

    @property
    def plain(self) -> bool:
        """引数の無い data（data.aws_region.current など）。擬似パラメータとして扱えるもの。"""
        return set(self.attrs) <= {"depends_on"} and not any(
            isinstance(c, Tree) and c.data == "block" for c in sig(self.body))


@dataclass
class Resolved:
    kind: str  # res／value／unknown／undefined
    to: str = ""
    attr: str | None = None
    as_list: bool = False
    value: object = None
    reason: str = ""
    workspace: bool = False


class Context:
    """1回の読み込み全体で共有するもの（リソースと参照の集まり、診断、前提）。"""

    def __init__(self, root_dir: Path):
        self.root_dir = root_dir
        self.diagnostics: list[dict] = []
        self.resources: list[dict] = []
        self.refs: list[dict] = []
        self.assumptions: list[str] = []

    def rel(self, path: Path) -> str:
        return Path(os.path.relpath(path, self.root_dir)).as_posix()

    def assume(self, text: str) -> None:
        if text not in self.assumptions:
            self.assumptions.append(text)


class ModuleEval:
    """1つのモジュール（手順1 ではルートモジュールだけ）のブロックを集めて評価する。"""

    def __init__(self, ctx: Context, directory: Path, prefix: str = ""):
        self.ctx = ctx
        self.dir = directory
        self.prefix = prefix  # address の前に付けるもの（手順3 のモジュールの "module.x."）
        self.blocks: dict[str, Block] = {}  # base（prefix を除いたもの）→ ブロック
        self.locals: dict[str, Tree] = {}
        self.providers: dict[str, Tree] = {}  # "aws"・"aws.us_east_1" → provider ブロックの本体
        self.current = ""  # いま評価しているリソースの address
        self.extra_refs: list[dict] = []  # unevaluated の参照

    # --- 診断と参照
    def diag(self, level: str, code: str, path: str, message: str, address: str | None = None) -> None:
        self.ctx.diagnostics.append({"level": level, "code": code,
                                     "address": self.current if address is None else address,
                                     "path": path, "message": message})

    def scan(self, node, path: str) -> None:
        """評価しない式の中の参照を、state: "unevaluated" で残す。"""
        for to, attr in self.static_refs(node):
            self.extra_refs.append({"from": self.current, "path": path, "to": to, "attr": attr, "fn": "ref",
                                    "state": "unevaluated"})

    def unknown(self, node, path: str, reason: str, code: str = "TF-DEFERRED"):
        self.scan(node, path)
        self.diag("warn", code, path, reason)
        return {"$unknown": reason}

    def drop(self, value, path: str, reason: str):
        """評価した値を使えないとき（テンプレートの中のリストなど）。中の $res は unevaluated で残す。"""
        for _, to, attr in ir_raw.iter_res(value, path):
            self.extra_refs.append({"from": self.current, "path": path, "to": to, "attr": attr, "fn": "ref",
                                    "state": "unevaluated"})
        self.diag("warn", "TF-UNEVALUATED", path, reason)
        return {"$unknown": reason}

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
        for f in files:
            rel = self.ctx.rel(f)
            if f.stem == "override" or f.stem.endswith("_override"):
                self.diag("warn", "TF-OVERRIDE-UNSUPPORTED", "", f"{rel}: override files are not merged yet", "")
                continue
            try:
                text = f.read_text(encoding="utf-8-sig")
            except (OSError, UnicodeDecodeError) as e:
                self.diag("error", "TF-PARSE-ERROR", "", f"{rel}: {type(e).__name__}: {e}", "")
                continue
            text, fixed = fix_heredocs(text)
            if fixed:
                self.diag("info", "TF-HEREDOC-TRAILING-SPACE", "",
                          f"{rel}: removed trailing spaces on {fixed} heredoc marker line(s) before parsing", "")
            try:
                tree = hcl2.parses_to_tree(text)
            except Exception as e:  # noqa: BLE001  lark の例外（UnexpectedToken など）
                first = str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__
                self.diag("error", "TF-PARSE-ERROR", "", f"{rel}: {type(e).__name__}: {first}", "")
                continue
            self.collect(tree, rel)

    def collect(self, tree: Tree, rel: str) -> None:
        body = sig(tree)[0]
        for item in sig(body):
            if not (isinstance(item, Tree) and item.data == "block"):
                continue
            cs = sig(item)
            btype = name_of(cs[0])
            labels = [label_text(x) for x in cs[1:-1]]
            b = cs[-1]
            attrs = {name_of(sig(a)[0]): sig(a)[-1] for a in sig(b) if isinstance(a, Tree) and a.data == "attribute"}
            if btype in ("resource", "data") and len(labels) == 2:
                blk = Block(btype, labels[0], labels[1], rel, b, attrs)
            elif btype == "module" and len(labels) == 1:
                blk = Block("module", "module", labels[0], rel, b, attrs)
            elif btype == "locals":
                for name, expr in attrs.items():
                    if name in self.locals:
                        self.diag("warn", "TF-DUPLICATE-BLOCK", "", f"{rel}: local.{name} is defined twice", "")
                    self.locals[name] = expr
                continue
            elif btype == "provider" and len(labels) == 1:
                alias = const(attrs["alias"]) if "alias" in attrs else None
                self.providers[labels[0] + (f".{alias}" if isinstance(alias, str) else "")] = b
                continue
            else:
                continue  # variable・output・terraform・moved・import などは手順1 では使わない
            if blk.base in self.blocks:
                self.diag("warn", "TF-DUPLICATE-BLOCK", "", f"{rel}: {blk.base} is defined twice; the first one is used",
                          "")
                continue
            self.blocks[blk.base] = blk

    # --- 参照
    def address_of(self, blk: Block) -> str:
        return self.prefix + blk.base + ("[*]" if blk.multi else "")

    def resolve(self, name: str, steps: list) -> Resolved:
        """参照の式の根と手順から、何を指すかを決める（副作用なし）。"""
        def attr_at(i):
            return steps[i][1] if i < len(steps) and steps[i][0] == "attr" else None

        first = attr_at(0)
        if name in ("var", "local", "count", "each", "self"):
            return Resolved("unknown", reason=f"{name}.{first} is {DEFERRED}")
        if name == "path":
            if first in ("module", "root", "cwd"):
                return Resolved("value", value=self.ctx.rel(self.dir) if first == "module" else ".")
            return Resolved("unknown", reason=f"path.{first} is {DEFERRED}")
        if name == "terraform":
            if first == "workspace":
                return Resolved("value", value="default", workspace=True)
            return Resolved("unknown", reason=f"terraform.{first} is {DEFERRED}")
        if name == "data":
            base, rest = f"data.{first}.{attr_at(1)}", steps[2:]
        elif name == "module":
            base, rest = f"module.{first}", steps[1:]
        else:
            base, rest = f"{name}.{first}", steps[1:]
        blk = self.blocks.get(base) if first else None
        if blk is None:
            return Resolved("undefined", reason=f"reference to undefined {base if first else name}")
        if blk.kind == "data" and not blk.multi and "provider" not in blk.attrs:
            a = rest[0][1] if rest and rest[0][0] == "attr" else None
            if blk.plain and (blk.type, a) in PSEUDO_DATA:
                return Resolved("value", value={"$pseudo": PSEUDO_DATA[(blk.type, a)]})
            # AZ は state などの引数があってもよい（別のリージョンを指す provider だけ除く）
            if blk.type == "aws_availability_zones" and a == "names":
                after = rest[1:]
                if not after:
                    return Resolved("value", value={"$az": "*"})
                if after[0][0] == "index":
                    idx = after[0][1] if isinstance(after[0][1], int) else const(after[0][1])
                    if isinstance(idx, int) and not isinstance(idx, bool) and idx >= 0:
                        return Resolved("value", value={"$az": idx})
                    return Resolved("unknown", reason=f"index into {base}.names is {DEFERRED}")
        as_list = False
        if rest and rest[0][0] == "index":
            rest = rest[1:]  # 手順1 ではインスタンスを区別しない（×N の [*] にまとめる）
        elif rest and rest[0][0] == "splat":
            rest = rest[0][1] + rest[1:]
            as_list = not blk.multi  # count の無いリソースのスプラットは要素1つのリスト
        attr = rest[0][1] if rest and rest[0][0] == "attr" else None
        return Resolved("res", to=self.address_of(blk), attr=attr, as_list=as_list)

    def static_refs(self, node) -> list[tuple[str, str | None]]:
        """評価しない式の中の、リソース・data・module への参照を探す（local はその式をたどる）。"""
        out: list[tuple[str, str | None]] = []
        seen: set[str] = set()

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
                for p in split_template(heredoc_body(str(t.children[0]))):
                    if isinstance(p, tuple) and p[1] is not None:
                        walk(p[1])
                return
            if t.data == "expr_term" or t.data in TRAVERSAL:
                root, steps = flatten(t)
                if isinstance(root, Tree) and root.data == "identifier":
                    name = name_of(root)
                    first = steps[0][1] if steps and steps[0][0] == "attr" else None
                    if name == "local":
                        if first in self.locals and first not in seen:
                            seen.add(first)
                            walk(self.locals[first])
                    else:
                        r = self.resolve(name, steps)
                        if r.kind == "res":
                            out.append((r.to, r.attr))
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

    # --- 評価
    def eval(self, t, path: str):
        t = unwrap(t)
        if not isinstance(t, Tree):
            return self.unknown(None, path, f"unexpected token {getattr(t, 'type', t)}", "TF-UNEVALUATED")
        d = t.data
        if d in ("int_lit", "float_lit", "literal_value"):
            return const(t)
        if d == "string":
            return self.template(string_pieces(t), path, t)
        if d in HEREDOC:
            return self.template(split_template(heredoc_body(str(t.children[0]))), path, t)
        if d == "tuple":
            return [self.eval(c, ir_raw.join_path(path, i)) for i, c in enumerate(sig(t))]
        if d == "object":
            return self.object(t, path)
        if d == "function_call":
            return self.call(t, path)
        if d in TRAVERSAL or d == "identifier":
            return self.reference(t, path)
        if d == "unary_op":
            v = const(t)
            if v is not NOTCONST:
                return v
        kind = EXPR_KINDS.get(d, d)
        return self.unknown(t, path, f"{kind} is {DEFERRED}")

    def template(self, pieces: list, path: str, node):
        """"${…}" と heredoc。式が1つだけなら、その値のまま（HCL と同じ）。"""
        trees = [p[1] for p in pieces if isinstance(p, tuple)]
        if any(isinstance(p, tuple) and p[0] == "directive" for p in pieces):
            return self.unknown(trees, path, f"template directive is {DEFERRED}")
        if any(x is None for x in trees):
            return self.unknown(trees, path, "an interpolation in a heredoc cannot be parsed", "TF-UNEVALUATED")
        if len(pieces) == 1 and isinstance(pieces[0], tuple):
            return self.eval(pieces[0][1], path)
        out: list = []
        for p in pieces:
            out.append(p if isinstance(p, str) else self.part(self.eval(p[1], path), path))
        return ir_raw.maybe_json(ir_raw.normalize_concat(out))

    def part(self, v, path: str):
        """テンプレートの中に入れる値（文字列か、$concat の要素になれる印）。"""
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, (int, float)):
            return str(v)
        if isinstance(v, str):
            return v
        if isinstance(v, dict) and ir_raw.is_marker(v) and "$json" not in v:
            return v
        if v is None:
            return self.drop(v, path, "null in a string template")
        return self.drop(v, path, "a list, an object or a JSON value in a string template is not evaluated")

    def object(self, t: Tree, path: str):
        elems = []
        for el in sig(t):
            cs = sig(el)
            key = self.object_key(cs[0])
            if not isinstance(key, str):
                return self.unknown(t, path, f"object with a computed key is {DEFERRED}")
            elems.append((key, cs[-1]))
        return {("$" + k if k.startswith("$") else k): self.eval(v, ir_raw.join_path(path, k)) for k, v in elems}

    @staticmethod
    def object_key(t):
        c = sig(t)[0]
        if isinstance(c, Tree) and c.data == "keyword":
            return name_of(c)
        u = unwrap(c)
        if isinstance(u, Tree) and u.data == "identifier":
            return name_of(u)
        v = const(u)
        return v if isinstance(v, str) else (str(v) if isinstance(v, (int, float)) and not isinstance(v, bool)
                                             else NOTCONST)

    def call(self, t: Tree, path: str):
        cs = sig(t)
        name = "::".join(name_of(c) for c in cs if isinstance(c, Tree) and c.data == "identifier")
        args_t = next((c for c in cs if isinstance(c, Tree) and c.data == "arguments"), None)
        args = [c for c in sig(args_t) if isinstance(c, Tree)] if args_t is not None else []
        expand = args_t is not None and any(isinstance(c, Token) and c.type == "ELLIPSIS" for c in args_t.children)
        if name == "jsonencode" and len(args) == 1 and not expand:
            v = self.eval(args[0], path)
            return v if isinstance(v, dict) and "$unknown" in v else {"$json": v}
        if name in FILE_FUNCTIONS:
            return self.unknown(t, path, f"{name}() is not evaluated (the file is not read)", "TF-UNEVALUATED")
        return self.unknown(t, path, f"function {name}() is {DEFERRED}")

    def reference(self, t: Tree, path: str):
        root, steps = flatten(t)
        if not (isinstance(root, Tree) and root.data == "identifier"):
            return self.unknown(t, path, f"traversal of an expression is {DEFERRED}")
        r = self.resolve(name_of(root), steps)
        if r.kind == "value":
            if r.workspace:
                self.ctx.assume('terraform.workspace is evaluated as "default"')
            return r.value
        if r.kind == "res":
            m = {"$res": r.to, "attr": r.attr}
            return [m] if r.as_list else m
        if r.kind == "undefined":
            return self.unknown(t, path, r.reason, "TF-UNDEFINED-REF")
        return self.unknown(t, path, r.reason)

    def body_props(self, body: Tree, path: str, meta: set = frozenset()) -> dict:
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
                v = self.eval(cs[-1], ir_raw.join_path(path, name))
                if v is not None:  # null は書かないのと同じ
                    out[name] = v
            elif item.data == "block":
                cs = sig(item)
                btype = name_of(cs[0])
                if btype in meta:
                    continue
                if btype == "dynamic" and len(cs) >= 3:
                    btype = label_text(cs[1])
                    lst = out.setdefault(btype, [])
                    if isinstance(lst, list):
                        p = ir_raw.join_path(ir_raw.join_path(path, btype), len(lst))
                        lst.append(self.unknown(cs[-1], p, f"dynamic block {btype} is {DEFERRED}"))
                    continue
                lst = out.setdefault(btype, [])
                if not isinstance(lst, list):
                    self.diag("warn", "TF-MALFORMED-BLOCK", ir_raw.join_path(path, btype),
                              f"block {btype} has the same name as an attribute")
                    continue
                lst.append(self.body_props(cs[-1], ir_raw.join_path(ir_raw.join_path(path, btype), len(lst))))
        return out

    # --- 本体
    def run(self) -> None:
        ctx = self.ctx
        for base, blk in sorted(self.blocks.items()):
            address = self.address_of(blk)
            self.current = address
            entry: dict = {"address": address, "type": blk.type, "file": blk.file,
                           "enabled": None if blk.multi else True}
            if blk.multi:
                entry["multiplicity"] = "N"
                for meta in ("count", "for_each"):
                    if meta in blk.attrs:
                        self.scan(blk.attrs[meta], meta)
                        self.diag("info", "TF-COUNT-DEFERRED", meta,
                                  f"{meta} is {DEFERRED}; written as one block with multiplicity N")
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
                            region = next((const(sig(a)[-1]) for a in sig(conf) if isinstance(a, Tree)
                                           and a.data == "attribute" and name_of(sig(a)[0]) == "region"), None)
                        else:  # モジュールでは呼び出し側から渡される（configuration_aliases。手順3）
                            self.diag("info", "TF-PROVIDER-UNCONFIGURED", "provider",
                                      f"provider {provider} has no configuration in this module; region is not known")
                    elif provider is None:
                        self.diag("warn", "TF-MALFORMED-BLOCK", "provider", "provider is not a provider reference")
                # AWS provider v6 のリソースの引数 region は、provider の region より優先する（Terraform と同じ）
                if (blk.type.startswith("aws_") and "region" in blk.attrs
                        and isinstance(const(blk.attrs["region"]), str)):
                    region = const(blk.attrs["region"])
                if isinstance(region, str) and region:
                    entry["region"] = region
            props = self.body_props(blk.body, "", meta)
            entry["props"] = props
            for p, to, attr in ir_raw.iter_res(props, ""):
                ctx.refs.append({"from": address, "path": p, "to": to, "attr": attr, "fn": "ref", "state": "active"})
            if "depends_on" in blk.attrs:
                self.depends_on(blk.attrs["depends_on"])
            ctx.resources.append(entry)
        ctx.refs += self.extra_refs

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
            r = self.resolve(name_of(root), steps) if isinstance(root, Tree) and root.data == "identifier" else None
            if r is not None and r.kind == "res":
                self.ctx.refs.append({"from": self.current, "path": "depends_on", "to": r.to, "attr": None,
                                      "fn": "depends_on", "state": "active"})
            else:
                text = name_of(root) if isinstance(root, Tree) and root.data == "identifier" else "an expression"
                if steps and steps[0][0] == "attr":
                    text += f".{steps[0][1]}"
                self.diag("warn", "TF-UNDEFINED-REF", "depends_on",
                          f"depends_on to {text} is not a resource, a data source or a module in this module")


# ------------------------------------------------------------------ raw IR の組み立て

def _dedupe(refs: list[dict]) -> list[dict]:
    seen: dict[tuple, dict] = {}
    for r in refs:
        key = ir_raw.ref_key(r)
        if key not in seen or (seen[key]["state"] != "active" and r["state"] == "active"):
            seen[key] = r
    return list(seen.values())


def build_raw(input_dir: Path, root_base: Path | None = None) -> dict:
    """ルートモジュールのフォルダから raw IR を作る。"""
    ctx = Context(input_dir)
    mod = ModuleEval(ctx, input_dir)
    mod.load()
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
    raw = {
        "ir_version": "1.0",
        "stage": "raw",
        "format": "tf",
        "root": root,
        "evaluation": {"var_files": [], "vars": {}, "assumptions": ctx.assumptions},
        "resources": ctx.resources,
        "references": _dedupe(ctx.refs),
        "diagnostics": diagnostics,
    }
    return ir_raw.canonical_raw(raw)


def dump(raw: dict) -> str:
    return json.dumps(raw, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Terraform のルートモジュールから raw IR を作る")
    ap.add_argument("--input", required=True, type=Path, help="ルートモジュールのフォルダ")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--root-base", type=Path, default=None)
    a = ap.parse_args(argv)
    try:
        raw = build_raw(a.input, a.root_base)
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
