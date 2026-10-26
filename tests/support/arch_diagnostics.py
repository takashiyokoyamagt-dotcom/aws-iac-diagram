"""構成の検査の道具: アダプタのコードにある診断コードの文字列を `ast` で集め、core/diagnostics.py の一覧と照合する。"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from support.arch_layers import PACKAGE
from aws_iac_diagram.core import diagnostics


# --------------------------------------------------------------------------------------------------------------
# 診断コードの一覧（core/diagnostics.py）の検査（PLAN の 1.4 の 4）
# --------------------------------------------------------------------------------------------------------------

# 一覧にあって、アダプタのコードで使われていないことを許すコード（コード → 理由）。増やさない（空）。
# 古い許可は残らない（使われている・一覧に無いコードの許可は失敗する）。
UNUSED_ALLOW: dict[str, str] = {}

DIAG_LEVELS = set(diagnostics.LEVELS)

DIAG_PREFIXES = tuple(p + "-" for p in diagnostics.ALLOWED_PREFIXES)

# 診断を出す呼び出しの名前（これらの引数、辞書の "code"、level つきのタプルにある、コードの形の文字列は、接頭辞が未登録なら失敗する）
EMIT_CALLS = {"diag", "unknown", "Unknown", "unknown_from"}


@dataclass(frozen=True)
class CodeSite:
    rel: str
    line: int
    code: str
    use: bool  # 出すか渡す位置にある（比較の右辺や、コードの集合の中は False）
    levels: tuple[str, ...]  # 同じ呼び出し・タプル・辞書に、level の文字列が直接書いてあれば、それ


def diagnostic_scan_files(scripts: Path) -> list[Path]:
    """診断コードを書くコードの範囲: アダプタの入口（scripts/adapt_*.py）と aws_iac_diagram/adapters/ の下のすべて。
    正規化の NORM-…（フェーズ 3 以降）は、その層が育つとき、この範囲を広げ、接頭辞を ALLOWED_PREFIXES に足し、一覧に足す。

    **この静的な検査は最善の努力（best-effort）で、すり抜けるものがある:** ① 接頭辞が単独の文字列になっていない組み立て
    （`"TF" + "-X"`、`"-".join(...)`）、② level を変数や既定の引数で渡すところの level（呼び出しの近くに文字列で書いた level
    だけを一覧と比べる）、③ 範囲の外（adapters/ と adapt_*.py 以外）で診断を出すコード、④ 接頭辞が ALLOWED_PREFIXES に無く、
    診断を出す位置（EMIT_CALLS の引数、辞書の "code"、level つきのタプル）の外にあるコードの形の文字列。
    動的な安全網は tests/architecture/test_diagnostics.py の EmittedLevelsTest（実際に動かして出た (code, level) を一覧と比べる）と、
    旧コードとの比較（CLI と変異した入力の差分、WORKLOG の「確かめたこと」）、golden。"""
    files = sorted(scripts.glob("adapt_*.py"))
    files += sorted(p for p in (scripts / PACKAGE / "adapters").rglob("*.py") if "__pycache__" not in p.parts)
    return files


def _literal_levels(nodes) -> tuple[str, ...]:
    return tuple(n.value for n in nodes if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value in DIAG_LEVELS)


def _is_emit_position(n: ast.Constant, parent: dict) -> bool:
    """この文字列が、診断を出す位置（EMIT_CALLS の呼び出しの引数、辞書の "code" の値、level の文字列つきのタプル）にあるか。"""
    p = parent.get(n)
    if isinstance(p, ast.keyword):
        p = parent.get(p)
    if isinstance(p, ast.Call):
        f = p.func
        return (f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else "") in EMIT_CALLS
    if isinstance(p, ast.Dict):
        return any(isinstance(k, ast.Constant) and k.value == "code" and v is n for k, v in zip(p.keys, p.values))
    if isinstance(p, (ast.Tuple, ast.List)):
        return bool(_literal_levels(p.elts))
    return False


def scan_diagnostic_codes(scripts: Path) -> tuple[list[CodeSite], list[str]]:
    """範囲のコードにある診断コードの文字列（`^[A-Z][A-Z0-9]*(-[A-Z0-9]+)+$` で、接頭辞が ALLOWED_PREFIXES のもの）の位置と、
    問題の一覧: ① 接頭辞（TF-・CFN-）で始まるのにコードの形でない文字列（"TF-" + 名前、f"TF-{x}" などの組み立て、打ち間違い）、
    ② コードの形で、診断を出す位置にあるのに、接頭辞が未登録のもの。接頭辞が未登録で診断を出す位置の外にある文字列
    （"UTF-8"、"GET-OBJECT" など）は数えない。"""
    sites: list[CodeSite] = []
    problems: list[str] = []
    for path in diagnostic_scan_files(scripts):
        rel = path.relative_to(scripts).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        parent: dict[ast.AST, ast.AST] = {}
        for n in ast.walk(tree):
            for c in ast.iter_child_nodes(n):
                parent[c] = n
        for n in ast.walk(tree):
            if not (isinstance(n, ast.Constant) and isinstance(n.value, str)):
                continue
            if diagnostics.CODE_PATTERN.match(n.value) and n.value.split("-", 1)[0] not in diagnostics.ALLOWED_PREFIXES:
                if _is_emit_position(n, parent):
                    problems.append(f"{rel}:{n.lineno}: {n.value!r} は診断を出す位置にあるコードの形の文字列だが、接頭辞 "
                                    f"{n.value.split('-', 1)[0]} が core/diagnostics.py の ALLOWED_PREFIXES に無い"
                                    "（新しい接頭辞なら、そこと PREFIXES に意図して足す）")
                continue
            if not diagnostics.CODE_PATTERN.match(n.value):
                if n.value.startswith(DIAG_PREFIXES):
                    problems.append(f"{rel}:{n.lineno}: {n.value!r} は診断コードの形でないのに、コードの接頭辞で始まる"
                                    "（コードは 1 つの文字列で書く。組み立てない）")
                continue
            p = parent.get(n)
            levels: tuple[str, ...] = ()
            if isinstance(p, ast.keyword):
                p = parent.get(p)
            if isinstance(p, ast.Call):
                levels = _literal_levels([*p.args, *(k.value for k in p.keywords)])
            elif isinstance(p, (ast.Tuple, ast.List)):
                levels = _literal_levels(p.elts)
            elif isinstance(p, ast.Dict):
                levels = _literal_levels(v for k, v in zip(p.keys, p.values)
                                         if isinstance(k, ast.Constant) and k.value == "level")
            # 比較の相手（`d["code"] == "TF-X"`、`in ("TF-X", …)`）とコードの集合（{"TF-X", …}）は、コードを出す位置ではない
            holder = parent.get(p) if isinstance(p, (ast.Tuple, ast.List, ast.Set)) else p
            use = not (isinstance(p, (ast.Set, ast.Compare)) or isinstance(holder, ast.Compare))
            sites.append(CodeSite(rel, n.lineno, n.value, use, levels))
    return sites, problems


def violations_in_diagnostics(scripts: Path, registry: dict[str, tuple[str, ...]],
                              unused_allow: dict[str, str] = UNUSED_ALLOW) -> list[str]:
    """registry = コード → 出うる level。範囲のコードのコードが一覧に無い、一覧のコードが使われていない、
    コードのそばに書いた level が一覧に無い、を返す。"""
    sites, problems = scan_diagnostic_codes(scripts)
    for s in sites:
        if s.code not in registry:
            problems.append(f"{s.rel}:{s.line}: 診断コード {s.code} が core/diagnostics.py の一覧に無い（一覧と docs/spec/ir-schema/ の 7.5 に足す）")
        else:
            for lv in s.levels:
                if lv not in registry[s.code]:
                    problems.append(f"{s.rel}:{s.line}: {s.code} を level {lv} で出している（一覧の levels は {'/'.join(registry[s.code])}）")
    used = {s.code for s in sites if s.use}
    for code in sorted(registry):
        if code not in used and code not in unused_allow:
            problems.append(f"診断コード {code} は一覧にあるが、アダプタのコードのどこでも出していない（一覧から消す。残すなら UNUSED_ALLOW に理由を書く）")
    for code, why in unused_allow.items():
        if code not in registry:
            problems.append(f"UNUSED_ALLOW の {code} が一覧に無い。許可を消す")
        elif code in used:
            problems.append(f"UNUSED_ALLOW の {code} は使われている。許可を消す")
        elif not why.strip():
            problems.append(f"UNUSED_ALLOW の {code} に理由が無い")
    return problems
