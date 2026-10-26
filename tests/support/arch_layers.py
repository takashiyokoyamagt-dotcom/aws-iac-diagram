"""構成の検査（tests/architecture/）の道具: 依存の向き、動的な import、アダプタの中の順序、標準ライブラリの名前の衝突。

ここは検査の「やり方」（import を `ast` で読む）と「許す向きの表」。表は docs/architecture.md の表と同じでなければならない
（食い違えば tests/architecture/ のテストが失敗する）。層を足す・向きを変えるときは、この表と docs/architecture.md を同じコミットで直す。
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path


PACKAGE = "aws_iac_diagram"

# --------------------------------------------------------------------------------------------------------------
# 設定
# --------------------------------------------------------------------------------------------------------------

# 層 → その層が import してよい層（自分の層の中は常に可）。入口（"entry"）は全層を import してよいので、表には書かない。
ALLOWED: dict[str, frozenset[str]] = {
    "core": frozenset(),
    "adapters": frozenset({"core"}),                    # registry.py（形式 → アダプタの名前の表）
    "adapters/terraform": frozenset({"core"}),
    "adapters/cloudformation": frozenset({"core"}),
    "normalize": frozenset({"core"}),
    "layout": frozenset({"core"}),
    "emit": frozenset({"core", "layout", "icons", "platform"}),
    "validate": frozenset({"core", "icons"}),
    "icons": frozenset({"core"}),
    "platform": frozenset({"core"}),
}

# 動的な import・実行に使う組み込み関数（パッケージの中では呼ばない）
DYNAMIC_CALLS = {"__import__", "exec", "eval"}

# aws_iac_diagram の下で、標準ライブラリと同じ名前を許すもの（名前 → 理由）。PLAN の 1.4 の層の名前 platform は残す。
# 危険: aws_iac_diagram/ のフォルダ自体を sys.path に入れる（その中から python を動かす、`python -m` を打つ）と、
# 標準ライブラリの platform を隠す。入口は scripts/ を sys.path に入れ、aws_iac_diagram/ の中では動かさない。
STDLIB_ALLOW: dict[str, str] = {
    "platform": "PLAN 1.4 の層の名前（draw.io の探索と呼び出し）。aws_iac_diagram/ 自体を sys.path に入れない決まり（docs/architecture.md）",
}

# 入口が入口を import してよい例外（(importする側のscripts/からの相対パス, 読まれる入口の名前) → 理由と外す時期）。
# 増やさない。ここにあるものが実際に使われていなければ失敗する（古い許可を残さない）。
ENTRY_IMPORT_ALLOW: dict[tuple[str, str], str] = {
    ("maintenance/check_icons.py", "build_icon_catalog"):
        "辞書の書き出し（write_outputs・strip_broken）を共有している保守用の 2 つ。辞書の読み書きを icons 層に移すとき（フェーズ 4 以降）に外す",
}

# サブパッケージ（フォルダ）を持ってよい層。層の表の外に新しい層が増えないように、ここに書いたものの直下だけ許す
SUBPACKAGE_PARENTS = {"adapters/terraform", "adapters/cloudformation"}

# adapters/terraform の中の順序（docs/architecture.md の表と同じ。食い違えば失敗）。下のグループは上のグループを import しない。
# 同じグループの中の import は常に可（グループの中のファイルの順序は見ない）。`if TYPE_CHECKING:` の中の import は実行されない
# ので数えない（型の注釈のためだけに module_eval を読むものがある）。表に無いファイルを足したら、失敗する（グループを決める）。
TERRAFORM_GROUPS: dict[str, tuple[str, ...]] = {
    "evaluator": ("evaluator",),
    "base": ("hcl", "model", "addresses", "refs"),
    "modules": ("modules",),
    "mixins": ("module_load", "module_vars", "module_expand", "module_expr", "module_props", "module_emit"),
    "module_eval": ("module_eval",),
    "build": ("build",),
    "plan": ("plan",),
}

# グループ → import してよい別のグループ。今の実際の import（実行時のもの）と同じ最小の辺だけ
INTRA_TERRAFORM: dict[str, frozenset[str]] = {
    "evaluator": frozenset(),
    "base": frozenset({"evaluator"}),
    "modules": frozenset(),
    "mixins": frozenset({"base", "evaluator", "modules"}),
    "module_eval": frozenset({"base", "mixins", "modules"}),
    "build": frozenset({"base", "evaluator", "module_eval", "plan"}),
    "plan": frozenset({"base"}),
}

# adapters/cloudformation の中の順序（同じ決まり。docs/architecture.md の表と同じ。食い違えば失敗）
CLOUDFORMATION_GROUPS: dict[str, tuple[str, ...]] = {
    "base": ("loader", "model", "marks", "refs", "sam", "cdk"),
    "mixins": ("params", "conditions", "intrinsics", "foreach", "outputs", "nested"),
    "evaluator": ("evaluator",),
    "stack": ("stack",),
    "build": ("build",),
}

INTRA_CLOUDFORMATION: dict[str, frozenset[str]] = {
    "base": frozenset(),
    "mixins": frozenset({"base"}),
    "evaluator": frozenset({"base", "mixins"}),
    "stack": frozenset({"base", "mixins", "evaluator"}),
    "build": frozenset({"base", "stack"}),
}

LAYER_DIRS = {"core", "normalize", "layout", "emit", "validate", "icons", "platform"}

# scripts/ の直下の入口のフォルダ（lib は R1、adapters は R3 で無くなった。戻さない。adapters という名前の import は入口の import と数える）
ENTRY_DIRS = {"adapters", "maintenance", "lib"}


# --------------------------------------------------------------------------------------------------------------
# 層の判定と import の読み取り
# --------------------------------------------------------------------------------------------------------------
def layer_of_parts(parts: tuple[str, ...]) -> str:
    """パッケージの中の位置（aws_iac_diagram の下の、拡張子を除いた名前の並び）から層の名前を返す。表に無い場所は "?<名前>"。"""
    if not parts or parts[0] == "__init__":
        return "root"  # aws_iac_diagram 自体（__init__.py）
    head = parts[0]
    if head == "adapters":
        if len(parts) >= 2 and parts[1] in ("terraform", "cloudformation"):
            return f"adapters/{parts[1]}"
        return "adapters"  # registry.py と __init__.py
    if head in LAYER_DIRS:
        return head
    return f"?{head}"


def source_layer(path: Path, scripts: Path) -> str:
    rel = path.relative_to(scripts).with_suffix("").parts
    if rel[0] == PACKAGE:
        return layer_of_parts(rel[1:])
    return "entry"


def entry_names(scripts: Path) -> set[str]:
    """入口のスクリプトの名前（scripts/ の直下と maintenance/ の .py と、入口のフォルダ）。
    アダプタの入口どうし（adapt_cfn.py が `import adapt_tf`）や保守用の入口どうしの import も、これで見つける。"""
    stems = {p.stem for p in scripts.glob("*.py")}
    stems |= {p.stem for p in (scripts / "maintenance").glob("*.py")}
    return stems | ENTRY_DIRS


def imported_targets(tree: ast.AST, path: Path, scripts: Path) -> list[tuple[int, str]]:
    """(行番号, import の対象のモジュール名) の一覧。相対 import は絶対名にする。"""
    rel = path.relative_to(scripts)
    pkg_parts = list(rel.parent.parts)  # このファイルを含むパッケージ
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out += [(node.lineno, a.name) for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = pkg_parts[: len(pkg_parts) - (node.level - 1)] if node.level > 1 else pkg_parts
                mod = ".".join(base + ([node.module] if node.module else []))
            else:
                mod = node.module or ""
            for a in node.names:
                full = f"{mod}.{a.name}" if mod else a.name
                # `from aws_iac_diagram.core import ir_raw` は ir_raw というモジュールへの import（無ければ名前の import）
                if (scripts / Path(*full.split("."))).with_suffix(".py").is_file() or (scripts / Path(*full.split("."))).is_dir():
                    out.append((node.lineno, full))
                else:
                    out.append((node.lineno, mod))
    return out


def violations_in_dependencies(scripts: Path, allowed: dict[str, frozenset[str]] = ALLOWED,
                               entry_allow: dict[tuple[str, str], str] = ENTRY_IMPORT_ALLOW) -> tuple[list[str], set[tuple[str, str]]]:
    """依存の向きの違反の一覧と、見つけた辺 (from の層, to の層) の集合。"""
    problems: list[str] = []
    edges: set[tuple[str, str]] = set()
    entries = entry_names(scripts)
    for path in sorted(scripts.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        rel = path.relative_to(scripts).as_posix()
        src = source_layer(path, scripts)
        if src.startswith("?"):
            problems.append(f"{rel}: 未知の層 {src[1:]}（ALLOWED と docs/architecture.md の表に層を足す）")
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for lineno, target in imported_targets(tree, path, scripts):
            top = target.split(".")[0]
            if top == PACKAGE:
                dst = layer_of_parts(tuple(target.split(".")[1:]))
                if dst == "root":
                    continue
                edges.add((src, dst))
                if dst.startswith("?"):
                    problems.append(f"{rel}:{lineno}: import {target} は未知の層 {dst[1:]}")
                elif src != "entry" and dst != src and dst not in allowed.get(src, frozenset()):
                    problems.append(f"{rel}:{lineno}: 層 {src} は層 {dst} を import できない（import {target}）")
            elif top in entries:
                # パッケージの中から入口を読むのも、入口が入口を読むのも不可（入口は引数の処理と呼び出しだけ）。
                # 例外は ENTRY_IMPORT_ALLOW の表にある（ファイル, 読む入口）だけ
                if src == "entry" and (rel, top) in entry_allow:
                    continue
                edges.add((src, "entry"))
                problems.append(f"{rel}:{lineno}: 入口のスクリプト {top} を import している（{src} から入口は読めない）")
    return problems, edges


def violations_in_dynamic_imports(scripts: Path) -> list[str]:
    """パッケージの中の動的な import（importlib、__import__、exec、eval）。静的な依存の検査をすり抜けるので禁止。"""
    problems: list[str] = []
    for path in sorted((scripts / PACKAGE).rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        rel = path.relative_to(scripts).as_posix()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(path))):
            if isinstance(node, ast.Import) and any(a.name.split(".")[0] == "importlib" for a in node.names):
                problems.append(f"{rel}:{node.lineno}: importlib を import している（動的な import は禁止）")
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and (node.module or "").split(".")[0] == "importlib":
                problems.append(f"{rel}:{node.lineno}: importlib から import している（動的な import は禁止）")
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in DYNAMIC_CALLS:
                problems.append(f"{rel}:{node.lineno}: {node.func.id}() を呼んでいる（動的な import・実行は禁止）")
    return problems


class _DropTypeChecking(ast.NodeTransformer):
    """`if TYPE_CHECKING:` のブロックを取り除く（実行されない import を数えないため）。"""

    def visit_If(self, node):
        t = node.test
        if (isinstance(t, ast.Name) and t.id == "TYPE_CHECKING") or (isinstance(t, ast.Attribute) and t.attr == "TYPE_CHECKING"):
            return None
        return self.generic_visit(node)


def adapter_group(groups: dict[str, tuple[str, ...]], parts: tuple[str, ...]) -> str:
    for group, members in groups.items():
        if parts[0] in members:
            return group
    return f"?{parts[0]}"


def violations_in_adapter_order(scripts: Path, adapter: str, groups: dict[str, tuple[str, ...]],
                                allowed: dict[str, frozenset[str]]) -> tuple[list[str], set[tuple[str, str]]]:
    """adapters/<adapter> の中の import の向きの違反の一覧と、見つけた辺 (from のグループ, to のグループ) の集合。"""
    base = scripts / PACKAGE / "adapters" / adapter
    prefix = f"{PACKAGE}.adapters.{adapter}"
    problems: list[str] = []
    edges: set[tuple[str, str]] = set()
    for path in sorted(base.rglob("*.py")):
        if "__pycache__" in path.parts or path.name == "__init__.py":
            continue
        rel = path.relative_to(scripts).as_posix()
        src = adapter_group(groups, path.relative_to(base).with_suffix("").parts)
        if src.startswith("?"):
            problems.append(f"{rel}: adapters/{adapter} のグループに無い（グループの表と docs/architecture.md の表に足す）")
            continue
        tree = _DropTypeChecking().visit(ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
        for lineno, target in imported_targets(tree, path, scripts):
            if not target.startswith(prefix + "."):
                continue
            dst = adapter_group(groups, tuple(target[len(prefix) + 1:].split(".")))
            if dst.startswith("?"):
                problems.append(f"{rel}:{lineno}: import {target} は adapters/{adapter} のグループに無い")
                continue
            if dst != src:
                edges.add((src, dst))
                if dst not in allowed[src]:
                    problems.append(f"{rel}:{lineno}: adapters/{adapter} のグループ {src} はグループ {dst} を import できない（import {target}）")
    return problems, edges


def violations_in_terraform_order(scripts: Path, allowed: dict[str, frozenset[str]] = INTRA_TERRAFORM) -> tuple[list[str], set[tuple[str, str]]]:
    return violations_in_adapter_order(scripts, "terraform", TERRAFORM_GROUPS, allowed)


def violations_in_cloudformation_order(scripts: Path, allowed: dict[str, frozenset[str]] = INTRA_CLOUDFORMATION) -> tuple[list[str], set[tuple[str, str]]]:
    return violations_in_adapter_order(scripts, "cloudformation", CLOUDFORMATION_GROUPS, allowed)


def stdlib_collisions(scripts: Path, allow: dict[str, str] = STDLIB_ALLOW) -> list[str]:
    """aws_iac_diagram の下のフォルダ・モジュールの名前が標準ライブラリと同じものの一覧（許可の表にあるものは除く）。

    パッケージのフォルダ自体が sys.path に入ると（その中から python を動かす、`python -m` の作業フォルダにするなど）、
    同じ名前の標準ライブラリを隠してしまう。"""
    problems: list[str] = []
    names: set[str] = set()
    for path in (scripts / PACKAGE).rglob("*"):
        if "__pycache__" in path.parts:
            continue
        if path.is_dir() or path.suffix == ".py":
            names.add(path.stem if path.is_file() else path.name)
    for n in sorted(names):
        if n in sys.stdlib_module_names and n not in allow:
            problems.append(f"{PACKAGE} の下の名前 {n} が標準ライブラリと同じ（フォルダ自体が sys.path に入ると隠す）。"
                            "名前を変えるか、理由を付けて STDLIB_ALLOW に書く")
    for n in sorted(allow):
        if n not in names:
            problems.append(f"STDLIB_ALLOW の {n} が {PACKAGE} の下に無い。許可を消す")
        elif n not in sys.stdlib_module_names:
            problems.append(f"STDLIB_ALLOW の {n} は標準ライブラリの名前ではない。許可を消す")
    return problems


def check_allowed_table(allowed: dict[str, frozenset[str]]) -> list[str]:
    problems = []
    for src, dsts in allowed.items():
        if src == "core" and dsts:
            problems.append("core はほかの層を import できない")
        for d in dsts:
            if d not in allowed:
                problems.append(f"{src} → {d}: 表に無い層")
            if src in allowed.get(d, frozenset()):
                problems.append(f"{src} ⇄ {d}: 層どうしの循環")
    return problems
