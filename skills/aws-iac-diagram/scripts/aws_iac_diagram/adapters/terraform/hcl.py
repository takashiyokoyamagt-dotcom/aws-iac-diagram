"""python-hcl2 の構文木（lark の Tree・Token）を読む小さな道具と、heredoc・テンプレートの字句の処理。

評価（値を作ること）はしない。構文木から名前・文字列・定数を取り出し、式の文字列を木にし、テンプレート（${…}、%{if}・%{for}）を
部品に分ける。Terraform の評価器（module_eval.py の式の評価）が使う。
"""
from __future__ import annotations

import re

import hcl2
from lark import Token, Tree

from aws_iac_diagram.adapters.terraform.evaluator import values as V


# 読み飛ばす記号の字句（構文木の中で意味を持たないもの）
SKIP_TOKENS = {"LPAR", "RPAR", "LBRACE", "RBRACE", "LSQB", "RSQB", "COMMA", "DOT", "EQ", "COLON", "DBLQUOTE",
               "INTERP_START", "QMARK", "COLONS", "NL_OR_COMMENT"}
TRAVERSAL = {"index_expr_term", "get_attr_expr_term", "attr_splat_expr_term", "full_splat_expr_term"}
HEREDOC = {"heredoc_template", "heredoc_template_trim"}
NOTCONST = object()
OPEN_HEREDOC = re.compile(r"<<-?([A-Za-z][A-Za-z0-9._-]*)([ \t]+)?$")
ESCAPE = re.compile(r"\\(u[0-9a-fA-F]{4}|U[0-9a-fA-F]{8}|.)", re.S)
SIMPLE_ESCAPES = {"n": "\n", "r": "\r", "t": "\t", '"': '"', "\\": "\\"}
CLOSERS = {"else", "endif", "endfor"}


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


def unescape(s: str) -> str:
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
                    out.append(unescape(str(c)))
                elif isinstance(c, Token) and c.type in ("ESCAPED_INTERPOLATION", "ESCAPED_DIRECTIVE"):
                    out.append(str(c)[1:])
                else:
                    return NOTCONST
        return "".join(out)
    if d == "unary_op":
        op, operand = str(t.children[0]).strip(), const(t.children[-1])
        if op == "-" and V.is_number(operand):
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
                    tokens.append(unescape(str(c)))
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
