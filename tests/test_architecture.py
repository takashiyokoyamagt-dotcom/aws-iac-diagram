"""構成を守る決まりのテスト（フェーズ 2b。PLAN の 1.4 の 4）。

1. 依存の向き: `skills/aws-iac-diagram/scripts/aws_iac_diagram/` の各層が、どの層を import してよいか。
   import を `ast` で読んで確かめる（実行はしない）。許す向きの表は ALLOWED（docs/architecture.md の表と同じ。
   食い違えば失敗）。入口のスクリプト（scripts/ の直下と scripts/maintenance/）だけが、どの層でも
   import してよい。パッケージの中から入口のスクリプトを import してはいけない。入口どうしも import し合わない。
2. 1ファイルの行数: 800 行を超えたら注意を印字するだけ、1,500 行を超えたら失敗。超えているファイルは、日付と理由を付けた
   EXEMPT に書く。EXEMPT は増やさない（行数の上限を超えて増えたら失敗）、1,500 行以内に減ったら、免除を消さないと失敗する。
3. 空振りにしない: 一時フォルダにコピーした構成に、わざと悪い import や長いファイルを入れて、検査が失敗することを確かめる。

層を足す・向きを変えるときは、この ALLOWED と docs/architecture.md の表を同じコミットで直す（理由をコミットメッセージに書く）。
"""
from __future__ import annotations

import ast
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "skills" / "aws-iac-diagram" / "scripts"
PACKAGE = "aws_iac_diagram"
ARCH_DOC = ROOT / "docs" / "architecture.md"

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

WARN_LINES = 800
MAX_LINES = 1500

# 1,500 行を超えているファイルの免除（scripts/ からの相対パス）。R2 で空にした（今は 1,500 行を超えるファイルが無い）。
# 免除を足すときは、日付（since）・上限（ceiling = 決めた日の行数。超えて増えたら失敗）・外す手順（remove_in）・理由を付け、
# 下の test_no_exemptions_remain も直す（理由をコミットメッセージに書く）。
EXEMPT: dict[str, dict] = {}

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


def terraform_group(parts: tuple[str, ...]) -> str:
    for group, members in TERRAFORM_GROUPS.items():
        if parts[0] in members:
            return group
    return f"?{parts[0]}"


def violations_in_terraform_order(scripts: Path, allowed: dict[str, frozenset[str]] = INTRA_TERRAFORM) -> tuple[list[str], set[tuple[str, str]]]:
    """adapters/terraform の中の import の向きの違反の一覧と、見つけた辺 (from のグループ, to のグループ) の集合。"""
    base = scripts / PACKAGE / "adapters" / "terraform"
    prefix = f"{PACKAGE}.adapters.terraform"
    problems: list[str] = []
    edges: set[tuple[str, str]] = set()
    for path in sorted(base.rglob("*.py")):
        if "__pycache__" in path.parts or path.name == "__init__.py":
            continue
        rel = path.relative_to(scripts).as_posix()
        src = terraform_group(path.relative_to(base).with_suffix("").parts)
        if src.startswith("?"):
            problems.append(f"{rel}: adapters/terraform のグループに無い（TERRAFORM_GROUPS と docs/architecture.md の表に足す）")
            continue
        tree = _DropTypeChecking().visit(ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
        for lineno, target in imported_targets(tree, path, scripts):
            if not target.startswith(prefix + "."):
                continue
            dst = terraform_group(tuple(target[len(prefix) + 1:].split(".")))
            if dst.startswith("?"):
                problems.append(f"{rel}:{lineno}: import {target} は adapters/terraform のグループに無い")
                continue
            if dst != src:
                edges.add((src, dst))
                if dst not in allowed[src]:
                    problems.append(f"{rel}:{lineno}: adapters/terraform のグループ {src} はグループ {dst} を import できない（import {target}）")
    return problems, edges


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


def count_lines(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def violations_in_size(scripts: Path, exempt: dict[str, dict] = EXEMPT, warn: list[str] | None = None) -> list[str]:
    problems: list[str] = []
    seen: set[str] = set()
    for path in sorted(scripts.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        rel = path.relative_to(scripts).as_posix()
        n = count_lines(path)
        seen.add(rel)
        ex = exempt.get(rel)
        if n > MAX_LINES:
            if ex is None:
                problems.append(f"{rel}: {n} 行（上限 {MAX_LINES}）。分けるか、日付と理由を付けて EXEMPT に書く")
            elif n > ex["ceiling"]:
                problems.append(f"{rel}: {n} 行。免除の上限（{ex['ceiling']} 行、{ex['since']}）を超えて増えた")
        else:
            if ex is not None:
                problems.append(f"{rel}: {n} 行で上限以内になった。EXEMPT の免除を消す（{ex.get('remove_in', '?')} の作業）")
            if n > WARN_LINES and warn is not None:
                warn.append(f"{rel}: {n} lines (over the {WARN_LINES}-line guideline; the hard limit is {MAX_LINES})")  # コンソールの文字コードに依らないよう ASCII
    for rel, ex in exempt.items():
        if rel not in seen:
            problems.append(f"EXEMPT の {rel} が存在しない。免除を消す")
        if not all(k in ex for k in ("since", "ceiling", "remove_in", "reason")) or not re.fullmatch(r"\d{4}-\d\d-\d\d", ex["since"]):
            problems.append(f"EXEMPT の {rel}: since（日付）・ceiling・remove_in・reason が要る")
    return problems


# --------------------------------------------------------------------------------------------------------------
# テスト
# --------------------------------------------------------------------------------------------------------------

class DependencyDirectionTest(unittest.TestCase):
    def test_real_tree_has_no_violations(self):
        problems, edges = violations_in_dependencies(SCRIPTS)
        self.assertEqual(problems, [], "\n".join(problems))
        # 空振りの防止: 実在する辺を見つけている
        self.assertIn(("adapters/terraform", "core"), edges)
        self.assertIn(("entry", "adapters/terraform"), edges)
        self.assertIn(("entry", "core"), edges)
        self.assertIn(("entry", "platform"), edges)
        self.assertEqual(violations_in_dynamic_imports(SCRIPTS), [])

    def test_real_tree_names_do_not_collide_with_the_stdlib(self):
        self.assertEqual(stdlib_collisions(SCRIPTS), [])
        self.assertEqual(list(STDLIB_ALLOW), ["platform"])  # 許可はこの 1 つだけ

    def test_mutation_new_stdlib_name_fails(self):
        for name in ("json", "types", "logging"):
            s = self.copy_tree()
            (s / PACKAGE / "core" / f"{name}.py").write_text("X = 1\n", encoding="utf-8")
            problems = stdlib_collisions(s)
            self.assertEqual(len(problems), 1, (name, problems))
            self.assertIn(name, problems[0])
        s = self.copy_tree()
        (s / PACKAGE / "enum").mkdir()
        self.assertTrue(any("enum" in p for p in stdlib_collisions(s)))
        # 許可の表が古くなったら咎める
        s = self.copy_tree()
        shutil.rmtree(s / PACKAGE / "platform")
        self.assertTrue(any("STDLIB_ALLOW の platform" in p for p in stdlib_collisions(s)))

    def test_mutation_dynamic_imports_fail(self):
        cases = {
            "import importlib": "importlib を import",
            "import importlib.util": "importlib を import",
            "from importlib import import_module": "importlib から import",
            "mod = __import__('aws_iac_diagram.emit')": "__import__()",
            "exec('import os')": "exec()",
            "x = eval('1 + 1')": "eval()",
        }
        for line, expect in cases.items():
            s = self.copy_tree()
            f = s / PACKAGE / "adapters" / "terraform" / "modules" / "summaries.py"
            f.write_text(f.read_text(encoding="utf-8") + "\n" + line + "\n", encoding="utf-8", newline="\n")
            problems = violations_in_dynamic_imports(s)
            self.assertTrue(any(expect in p for p in problems), (line, problems))
        # メソッドの eval（self.eval(...)）は動的な実行ではない
        s = self.copy_tree()
        f = s / PACKAGE / "core" / "ir_raw.py"
        f.write_text(f.read_text(encoding="utf-8") + "\nclass _X:\n    def go(self):\n        return self.eval(1)\n",
                     encoding="utf-8", newline="\n")
        self.assertEqual(violations_in_dynamic_imports(s), [])

    def test_entry_import_allowlist_is_used_and_narrow(self):
        # 許可の表を空にすると、表にあるものだけが違反として出る（古い許可が残っていない）
        problems, _ = violations_in_dependencies(SCRIPTS, entry_allow={})
        self.assertEqual(len(problems), len(ENTRY_IMPORT_ALLOW), problems)
        for (rel, top), why in ENTRY_IMPORT_ALLOW.items():
            self.assertTrue(any(p.startswith(rel + ":") and f"入口のスクリプト {top} " in p for p in problems), (rel, top))
            self.assertTrue(why.strip())
        self.assertEqual(list(ENTRY_IMPORT_ALLOW), [("maintenance/check_icons.py", "build_icon_catalog")])

    def test_mutation_sibling_entry_imports_fail(self):
        for relpath, line, expect in (("adapt_cfn.py", "import adapt_tf", "入口のスクリプト adapt_tf"),
                                      ("adapt_tf.py", "from adapt_cfn import main", "入口のスクリプト adapt_cfn"),
                                      ("maintenance/build_icon_catalog.py", "import check_icons",
                                       "入口のスクリプト check_icons"),
                                      ("maintenance/check_icons.py", "import doctor",
                                       "入口のスクリプト doctor")):
            s = self.copy_tree()
            problems = self.inject(s, relpath, line)
            self.assertTrue(any(expect in p and p.startswith(relpath) for p in problems), (relpath, problems))
        self.assertTrue({"adapt_tf", "adapt_cfn", "check_icons", "build_icon_catalog", "doctor"} <= entry_names(SCRIPTS))

    def test_every_package_directory_is_a_known_layer(self):
        pkg = SCRIPTS / PACKAGE
        dirs = {p.parent.relative_to(pkg).as_posix() for p in pkg.rglob("__init__.py") if p.parent != pkg}
        known = set(ALLOWED) | {"adapters/terraform", "adapters/cloudformation"}
        # アダプタのパッケージの下のサブパッケージ（adapters/terraform/evaluator など）は、アダプタの層の一部
        subpackages = {d for d in dirs - known if d.rsplit("/", 1)[0] in SUBPACKAGE_PARENTS}
        self.assertEqual(sorted(dirs - known - subpackages), [], "表に無い層のフォルダがある")
        self.assertEqual(sorted(known - dirs), [], "表にあるが無い層（空でも __init__.py を置く）")
        self.assertTrue({"adapters/terraform/evaluator", "adapters/terraform/modules", "adapters/terraform/plan"} <= subpackages)
        for p in pkg.rglob("*.py"):
            self.assertNotEqual(source_layer(p, SCRIPTS)[:1], "?", p)

    def test_table_is_consistent(self):
        self.assertEqual(check_allowed_table(ALLOWED), [])
        self.assertEqual(ALLOWED["core"], frozenset())
        # 決まりの要点（PLAN の 1.4 の 4）
        for a, b in (("adapters/terraform", "adapters/cloudformation"), ("adapters/cloudformation", "adapters/terraform")):
            self.assertNotIn(b, ALLOWED[a])
        for adapter in ("adapters", "adapters/terraform", "adapters/cloudformation"):
            self.assertTrue(ALLOWED[adapter] <= {"core"}, adapter)
        for lower in ("platform", "icons"):
            self.assertFalse({a for a in ALLOWED[lower] if a.startswith("adapters")}, lower)
        for layer, dsts in ALLOWED.items():
            if layer != "emit":
                self.assertNotIn("emit", dsts, layer)

    def test_docs_table_matches(self):
        text = ARCH_DOC.read_text(encoding="utf-8")
        start = text.index("<!-- allowed-edges:begin -->")
        end = text.index("<!-- allowed-edges:end -->")
        rows = {}
        for line in text[start:end].splitlines():
            m = re.match(r"^\|\s*`([a-z/]+)`\s*\|\s*(.*?)\s*\|\s*$", line)
            if m:
                cell = m.group(2)
                rows[m.group(1)] = frozenset(re.findall(r"`([a-z/]+)`", cell))
        self.assertEqual(rows, ALLOWED, "docs/architecture.md の表と ALLOWED が食い違う")

    # --- 空振りの防止: 一時フォルダにコピーして、わざと悪い import を入れる

    def copy_tree(self) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        dst = Path(tmp.name) / "scripts"
        shutil.copytree(SCRIPTS, dst, ignore=shutil.ignore_patterns("__pycache__"))
        return dst

    def inject(self, scripts: Path, relpath: str, line: str) -> list[str]:
        f = scripts / relpath
        f.write_text(f.read_text(encoding="utf-8") + "\n" + line + "\n", encoding="utf-8", newline="\n")
        problems, _ = violations_in_dependencies(scripts)
        return problems

    def test_copy_is_clean_before_mutation(self):
        problems, _ = violations_in_dependencies(self.copy_tree())
        self.assertEqual(problems, [])

    def test_mutation_core_importing_another_layer_fails(self):
        s = self.copy_tree()
        problems = self.inject(s, "aws_iac_diagram/core/ir_raw.py", "from aws_iac_diagram.platform import drawio_cli")
        self.assertTrue(any("層 core は層 platform" in p for p in problems), problems)

    def test_mutation_adapters_importing_each_other_fails(self):
        s = self.copy_tree()
        (s / "aws_iac_diagram/adapters/cloudformation/x.py").write_text("X = 1\n", encoding="utf-8")
        problems = self.inject(s, "aws_iac_diagram/adapters/terraform/evaluator/functions.py",
                               "from aws_iac_diagram.adapters.cloudformation import x")
        self.assertTrue(any("層 adapters/terraform は層 adapters/cloudformation" in p for p in problems), problems)

    def test_mutation_relative_import_is_resolved(self):
        s = self.copy_tree()
        problems = self.inject(s, "aws_iac_diagram/adapters/terraform/refs.py", "from ...emit import something")
        self.assertTrue(any("層 adapters/terraform は層 emit" in p for p in problems), problems)
        s2 = self.copy_tree()
        problems = self.inject(s2, "aws_iac_diagram/adapters/terraform/refs.py", "from .. import cloudformation")
        self.assertTrue(any("層 adapters/terraform は層 adapters/cloudformation" in p for p in problems), problems)

    def test_mutation_adapters_importing_emit_layout_normalize_validate_fails(self):
        for layer in ("emit", "layout", "normalize", "validate"):
            s = self.copy_tree()
            problems = self.inject(s, "aws_iac_diagram/adapters/terraform/evaluator/functions.py", f"import aws_iac_diagram.{layer}")
            self.assertTrue(any(f"層 adapters/terraform は層 {layer}" in p for p in problems), (layer, problems))

    def test_mutation_platform_and_icons_importing_adapters_fails(self):
        for layer in ("platform", "icons"):
            s = self.copy_tree()
            problems = self.inject(s, f"aws_iac_diagram/{layer}/__init__.py", "from aws_iac_diagram.adapters.terraform.evaluator import functions")
            self.assertTrue(any(f"層 {layer} は層 adapters/terraform" in p for p in problems), (layer, problems))

    def test_mutation_package_importing_an_entry_script_fails(self):
        s = self.copy_tree()
        problems = self.inject(s, "aws_iac_diagram/core/ir_raw.py", "import validate_ir")
        self.assertTrue(any("入口のスクリプト validate_ir" in p for p in problems), problems)
        s = self.copy_tree()
        problems = self.inject(s, "aws_iac_diagram/adapters/terraform/plan/reader.py", "from adapters import cfn")
        self.assertTrue(any("入口のスクリプト adapters" in p for p in problems), problems)
        s = self.copy_tree()
        problems = self.inject(s, "aws_iac_diagram/adapters/terraform/model.py", "import adapt_tf")
        self.assertTrue(any("入口のスクリプト adapt_tf" in p for p in problems), problems)

    def test_mutation_entry_importing_entry_fails_but_entry_importing_layers_is_fine(self):
        s = self.copy_tree()
        self.assertEqual(self.inject(s, "doctor.py", "from aws_iac_diagram.adapters.terraform.evaluator import functions"), [])
        s = self.copy_tree()
        problems = self.inject(s, "doctor.py", "import validate_ir")
        self.assertTrue(any("入口のスクリプト validate_ir" in p for p in problems), problems)

    def test_mutation_unknown_layer_fails(self):
        s = self.copy_tree()
        (s / PACKAGE / "misc").mkdir()
        (s / PACKAGE / "misc" / "__init__.py").write_text('"""x"""\n', encoding="utf-8")
        problems, _ = violations_in_dependencies(s)
        self.assertTrue(any("未知の層 misc" in p for p in problems), problems)

    def test_table_checker_rejects_bad_tables(self):
        self.assertTrue(check_allowed_table({**ALLOWED, "core": frozenset({"icons"})}))
        self.assertTrue(check_allowed_table({"core": frozenset(), "icons": frozenset({"core", "nowhere"})}))
        self.assertTrue(check_allowed_table({"core": frozenset(), "a": frozenset({"b"}), "b": frozenset({"a"})}))


class TerraformOrderTest(unittest.TestCase):
    """adapters/terraform の中の下の層 → 上の層の import を禁じる決まり（docs/architecture.md の「Terraform アダプタの中身」）。"""

    def copy_tree(self) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        dst = Path(tmp.name) / "scripts"
        shutil.copytree(SCRIPTS, dst, ignore=shutil.ignore_patterns("__pycache__"))
        return dst

    def inject(self, scripts: Path, relpath: str, line: str) -> list[str]:
        f = scripts / PACKAGE / "adapters" / "terraform" / relpath
        f.write_text(f.read_text(encoding="utf-8") + "\n" + line + "\n", encoding="utf-8", newline="\n")
        problems, _ = violations_in_terraform_order(scripts)
        return problems

    def test_real_tree_follows_the_order(self):
        problems, edges = violations_in_terraform_order(SCRIPTS)
        self.assertEqual(problems, [], "\n".join(problems))
        # 空振りの防止: 実在する辺を見つけている。表にある辺はすべて実際に使われている（古い許可を残さない）
        for edge in (("mixins", "base"), ("mixins", "evaluator"), ("mixins", "modules"), ("module_eval", "mixins"),
                     ("build", "module_eval"), ("build", "plan"), ("plan", "base"), ("base", "evaluator")):
            self.assertIn(edge, edges)
        self.assertEqual(edges, {(a, b) for a, bs in INTRA_TERRAFORM.items() for b in bs})

    def test_table_is_consistent(self):
        self.assertEqual(set(INTRA_TERRAFORM), set(TERRAFORM_GROUPS))
        self.assertEqual(check_allowed_table(INTRA_TERRAFORM), [])
        members = [m for ms in TERRAFORM_GROUPS.values() for m in ms]
        self.assertEqual(len(members), len(set(members)))
        # 実在する最上位のファイル・フォルダがすべてどこかのグループに入っている
        base = SCRIPTS / PACKAGE / "adapters" / "terraform"
        tops = {p.stem if p.is_file() else p.name for p in base.iterdir()
                if (p.suffix == ".py" or p.is_dir()) and p.name not in ("__init__.py", "__pycache__")}
        self.assertEqual(sorted(tops - set(members)), [])
        self.assertEqual(sorted(set(members) - tops), [])

    def test_docs_table_matches(self):
        text = ARCH_DOC.read_text(encoding="utf-8")
        start = text.index("<!-- terraform-order:begin -->")
        end = text.index("<!-- terraform-order:end -->")
        groups, allowed = {}, {}
        for line in text[start:end].splitlines():
            m = re.match(r"^\|\s*`([a-z_]+)`\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*$", line)
            if m:
                groups[m.group(1)] = set(re.findall(r"`([a-z_]+)/?`", m.group(2)))
                allowed[m.group(1)] = frozenset(re.findall(r"`([a-z_]+)`", m.group(3)))
        self.assertEqual(groups, {g: set(ms) for g, ms in TERRAFORM_GROUPS.items()},
                         "docs/architecture.md のグループの表と TERRAFORM_GROUPS が食い違う")
        self.assertEqual(allowed, INTRA_TERRAFORM, "docs/architecture.md の表と INTRA_TERRAFORM が食い違う")

    def test_mutation_lower_layers_importing_upper_layers_fail(self):
        tf = "from aws_iac_diagram.adapters.terraform"
        cases = (
            ("evaluator/values.py", f"{tf}.module_eval import ModuleEval", "グループ evaluator はグループ module_eval"),
            ("plan/values.py", f"{tf}.module_expr import ExpressionMixin", "グループ plan はグループ mixins"),
            ("hcl.py", f"{tf} import build", "グループ base はグループ build"),
            ("plan/reader.py", f"{tf}.evaluator import functions", "グループ plan はグループ evaluator"),
            ("modules/resolve.py", f"{tf}.hcl import sig", "グループ modules はグループ base"),
            ("module_expr.py", f"{tf}.module_eval import ModuleEval", "グループ mixins はグループ module_eval"),
            ("module_eval.py", f"{tf}.build import dump", "グループ module_eval はグループ build"),
            ("model.py", "import aws_iac_diagram.adapters.terraform.module_vars as mv", "グループ base はグループ mixins"),
        )
        for relpath, line, expect in cases:
            s = self.copy_tree()
            problems = self.inject(s, relpath, line)
            self.assertTrue(any(expect in p and p.startswith("aws_iac_diagram/adapters/terraform/" + relpath + ":") for p in problems),
                            (relpath, problems))

    def test_mutation_relative_imports_are_resolved(self):
        s = self.copy_tree()
        problems = self.inject(s, "hcl.py", "from . import build")
        self.assertTrue(any("グループ base はグループ build" in p for p in problems), problems)
        s = self.copy_tree()
        problems = self.inject(s, "plan/combine.py", "from .. import module_eval")
        self.assertTrue(any("グループ plan はグループ module_eval" in p for p in problems), problems)

    def test_type_checking_imports_are_not_counted(self):
        line = "from aws_iac_diagram.adapters.terraform.module_eval import ModuleEval"
        s = self.copy_tree()
        self.assertEqual(self.inject(s, "hcl.py", "if TYPE_CHECKING:\n    " + line), [])
        # TYPE_CHECKING の外の import は数える
        s = self.copy_tree()
        problems = self.inject(s, "hcl.py", "if True:\n    " + line)
        self.assertTrue(any("グループ base はグループ module_eval" in p for p in problems), problems)

    def test_mutation_new_file_outside_the_groups_fails(self):
        s = self.copy_tree()
        (s / PACKAGE / "adapters" / "terraform" / "newthing.py").write_text("X = 1\n", encoding="utf-8")
        problems, _ = violations_in_terraform_order(s)
        self.assertTrue(any("newthing.py" in p and "グループに無い" in p for p in problems), problems)


class FileSizeTest(unittest.TestCase):
    def test_real_tree(self):
        warn: list[str] = []
        problems = violations_in_size(SCRIPTS, warn=warn)
        for w in warn:
            print(f"\n[note] {w}", file=sys.stderr)
        self.assertEqual(problems, [], "\n".join(problems))

    def test_no_exemptions_remain(self):
        # R2 で空にした。免除を足すなら、この検査を理由付きで直す
        self.assertEqual(EXEMPT, {})

    def test_exemptions_are_dated_and_justified(self):
        for rel, ex in EXEMPT.items():
            self.assertRegex(ex["since"], r"^\d{4}-\d\d-\d\d$", rel)
            self.assertGreater(ex["ceiling"], MAX_LINES, rel)
            self.assertTrue(ex["reason"].strip(), rel)
            self.assertRegex(ex["remove_in"], r"^R\d$", rel)
            self.assertTrue((SCRIPTS / rel).is_file(), rel)

    def make(self, lines: int) -> tuple[Path, Path]:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        scripts = Path(tmp.name) / "scripts"
        (scripts / PACKAGE / "core").mkdir(parents=True)
        f = scripts / PACKAGE / "core" / "big.py"
        f.write_text("x = 1\n" * lines, encoding="utf-8", newline="\n")
        return scripts, f

    def test_mutation_long_file_fails(self):
        scripts, _ = self.make(MAX_LINES + 1)
        problems = violations_in_size(scripts, exempt={})
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("aws_iac_diagram/core/big.py", problems[0])

    def test_boundary_and_warning(self):
        scripts, _ = self.make(MAX_LINES)
        self.assertEqual(violations_in_size(scripts, exempt={}), [])
        warn: list[str] = []
        scripts, _ = self.make(WARN_LINES + 1)
        self.assertEqual(violations_in_size(scripts, exempt={}, warn=warn), [])
        self.assertEqual(len(warn), 1)
        scripts, _ = self.make(WARN_LINES)
        warn = []
        violations_in_size(scripts, exempt={}, warn=warn)
        self.assertEqual(warn, [])

    def test_exemption_must_be_removed_when_file_shrinks(self):
        scripts, _ = self.make(MAX_LINES - 10)
        ex = {"aws_iac_diagram/core/big.py": {"since": "2026-10-26", "ceiling": 1600, "remove_in": "R2", "reason": "x"}}
        problems = violations_in_size(scripts, exempt=ex)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("免除を消す", problems[0])

    def test_exempt_file_cannot_grow_past_its_ceiling(self):
        scripts, _ = self.make(1601)
        ex = {"aws_iac_diagram/core/big.py": {"since": "2026-10-26", "ceiling": 1600, "remove_in": "R2", "reason": "x"}}
        problems = violations_in_size(scripts, exempt=ex)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("超えて増えた", problems[0])
        scripts, _ = self.make(1600)
        self.assertEqual(violations_in_size(scripts, exempt=ex), [])

    def test_stale_or_malformed_exemption_fails(self):
        scripts, _ = self.make(10)
        self.assertTrue(any("存在しない" in p for p in violations_in_size(
            scripts, exempt={"nope.py": {"since": "2026-10-26", "ceiling": 2000, "remove_in": "R2", "reason": "x"}})))
        self.assertTrue(any("since" in p for p in violations_in_size(
            scripts, exempt={"aws_iac_diagram/core/big.py": {"ceiling": 2000}})))


if __name__ == "__main__":
    unittest.main()
