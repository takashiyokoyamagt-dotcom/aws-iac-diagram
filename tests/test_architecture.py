"""構成を守る決まりのテスト（フェーズ 2b。PLAN の 1.4 の 4）。

1. 依存の向き: `skills/aws-iac-diagram/scripts/aws_iac_diagram/` の各層が、どの層を import してよいか。
   import を `ast` で読んで確かめる（実行はしない）。許す向きの表は ALLOWED（docs/architecture.md の表と同じ。
   食い違えば失敗）。入口のスクリプト（scripts/ の直下、scripts/adapters/、scripts/maintenance/）だけが、どの層でも
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

WARN_LINES = 800
MAX_LINES = 1500

# 1,500 行を超えているファイルの免除（scripts/ からの相対パス）。R2 で空にする。
# ceiling = 免除を決めた日の行数。これを超えて増えたら失敗する（免除を口実に大きくしない）。
EXEMPT: dict[str, dict] = {
    "adapters/tf.py": {
        "since": "2026-10-26", "ceiling": 2613, "remove_in": "R2",
        "reason": "TF アダプタの入口と本体が 1 ファイル（2613 行）。R2 で adapt_tf.py（入口）と adapters/terraform/ の"
                  "モジュール（hcl・参照・evaluator・modules・plan）に分ける",
    },
    "aws_iac_diagram/adapters/terraform/tf_plan.py": {
        "since": "2026-10-26", "ceiling": 1558, "remove_in": "R2",
        "reason": "plan JSON の読み込みと .tf との結合が 1 ファイル（1558 行）。R2 で adapters/terraform/plan/ に分ける",
    },
}

LAYER_DIRS = {"core", "normalize", "layout", "emit", "validate", "icons", "platform"}
ENTRY_DIRS = {"adapters", "maintenance", "lib"}  # scripts/ の直下の入口のフォルダ（lib は R1 で無くなった。戻さない）


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
    return {p.stem for p in scripts.glob("*.py")} | ENTRY_DIRS


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


def violations_in_dependencies(scripts: Path, allowed: dict[str, frozenset[str]] = ALLOWED) -> tuple[list[str], set[tuple[str, str]]]:
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
                # パッケージの中から入口を読むのも、入口が入口を読むのも不可（入口は引数の処理と呼び出しだけ）
                edges.add((src, "entry"))
                problems.append(f"{rel}:{lineno}: 入口のスクリプト {top} を import している（{src} から入口は読めない）")
    return problems, edges


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

    def test_every_package_directory_is_a_known_layer(self):
        pkg = SCRIPTS / PACKAGE
        dirs = {p.parent.relative_to(pkg).as_posix() for p in pkg.rglob("__init__.py") if p.parent != pkg}
        known = set(ALLOWED) | {"adapters/terraform", "adapters/cloudformation"}
        self.assertEqual(sorted(dirs - known), [], "表に無い層のフォルダがある")
        self.assertEqual(sorted(known - dirs), [], "表にあるが無い層（空でも __init__.py を置く）")
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
        problems = self.inject(s, "aws_iac_diagram/adapters/terraform/tf_eval.py",
                               "from aws_iac_diagram.adapters.cloudformation import x")
        self.assertTrue(any("層 adapters/terraform は層 adapters/cloudformation" in p for p in problems), problems)

    def test_mutation_relative_import_is_resolved(self):
        s = self.copy_tree()
        problems = self.inject(s, "aws_iac_diagram/adapters/terraform/tf_modules.py", "from ...emit import something")
        self.assertTrue(any("層 adapters/terraform は層 emit" in p for p in problems), problems)
        s2 = self.copy_tree()
        problems = self.inject(s2, "aws_iac_diagram/adapters/terraform/tf_modules.py", "from .. import cloudformation")
        self.assertTrue(any("層 adapters/terraform は層 adapters/cloudformation" in p for p in problems), problems)

    def test_mutation_adapters_importing_emit_layout_normalize_validate_fails(self):
        for layer in ("emit", "layout", "normalize", "validate"):
            s = self.copy_tree()
            problems = self.inject(s, "aws_iac_diagram/adapters/terraform/tf_eval.py", f"import aws_iac_diagram.{layer}")
            self.assertTrue(any(f"層 adapters/terraform は層 {layer}" in p for p in problems), (layer, problems))

    def test_mutation_platform_and_icons_importing_adapters_fails(self):
        for layer in ("platform", "icons"):
            s = self.copy_tree()
            problems = self.inject(s, f"aws_iac_diagram/{layer}/__init__.py", "from aws_iac_diagram.adapters.terraform import tf_eval")
            self.assertTrue(any(f"層 {layer} は層 adapters/terraform" in p for p in problems), (layer, problems))

    def test_mutation_package_importing_an_entry_script_fails(self):
        s = self.copy_tree()
        problems = self.inject(s, "aws_iac_diagram/core/ir_raw.py", "import validate_ir")
        self.assertTrue(any("入口のスクリプト validate_ir" in p for p in problems), problems)
        s = self.copy_tree()
        problems = self.inject(s, "aws_iac_diagram/adapters/terraform/tf_plan.py", "from adapters import tf")
        self.assertTrue(any("入口のスクリプト adapters" in p for p in problems), problems)

    def test_mutation_entry_importing_entry_fails_but_entry_importing_layers_is_fine(self):
        s = self.copy_tree()
        self.assertEqual(self.inject(s, "doctor.py", "from aws_iac_diagram.adapters.terraform import tf_eval"), [])
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


class FileSizeTest(unittest.TestCase):
    def test_real_tree(self):
        warn: list[str] = []
        problems = violations_in_size(SCRIPTS, warn=warn)
        for w in warn:
            print(f"\n[note] {w}", file=sys.stderr)
        self.assertEqual(problems, [], "\n".join(problems))

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
