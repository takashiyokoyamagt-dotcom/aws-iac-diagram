"""SKILL.md（配る入口の文書）が、今の実物と食い違わないこと（フェーズ 2b の R6）。

- frontmatter は `name` と `description` だけ（PLAN の 1.3 の 1）。短い（入口だけ）。
- 書いてあるスクリプトが実在し、`scripts/` の直下の入口がすべて書いてある。辞書の保守用（maintenance/）は書かない。
- 書いてあるコマンドは `uv run "<SKILL>/scripts/…"` の 1 行で、シェルの機能（`&&`・`|`・`>`・`;`・`$`）を使わない。
- 書いてあるオプション（`--out` など）は、どれかの入口のスクリプトが実際に持っている。
- まだ無いもの（図を作る処理 `diagram.py`）を、使えるように書いていない。
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

# tests/ を import の道に入れる（`python tests/.../test_x.py` で直接動かすときのため。discover では要らないが害は無い）
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "support").is_dir())))
from support.paths import SCRIPTS, SKILL  # noqa: E402

SKILL_MD = SKILL / "SKILL.md"
MAX_LINES = 90


def entry_scripts() -> set[str]:
    return {p.name for p in SCRIPTS.glob("*.py")}


def commands(text: str) -> list[str]:
    """バッククォートで囲んだ `uv run …` のコマンド。"""
    return [c for c in re.findall(r"`(uv run [^`]+)`", text)]


def problems_in(text: str, entries: set[str], sources: dict[str, str]) -> list[str]:
    out: list[str] = []
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    if not m:
        return ["frontmatter が無い"]
    keys = re.findall(r"^([A-Za-z_-]+):", m.group(1), re.M)
    if keys != ["name", "description"]:
        out.append(f"frontmatter のキーが name と description だけでない: {keys}")
    if len(text.splitlines()) > MAX_LINES:
        out.append(f"{len(text.splitlines())} 行ある（入口だけの文書は {MAX_LINES} 行まで）")
    body = text[m.end():]
    mentioned = set(re.findall(r"<SKILL>/scripts/([A-Za-z0-9_]+\.py)", body))
    for name in sorted(mentioned - entries):
        out.append(f"書いてあるスクリプトが無い（または入口でない）: {name}")
    for name in sorted(entries - mentioned):
        out.append(f"入口のスクリプトが書いていない: {name}")
    if "maintenance" in body:
        out.append("辞書の保守用のスクリプト（maintenance/）を書いている")
    for c in commands(body):
        if not c.startswith('uv run "<SKILL>/scripts/'):
            out.append(f"コマンドが uv run \"<SKILL>/scripts/…\" の形でない: {c}")
        if re.search(r"&&|\||>|;|\$", re.sub(r"<[^<>]*>", "", c)):  # <出力先> などのプレースホルダーは除く
            out.append(f"コマンドにシェルの機能がある: {c}")
        if "\n" in c:
            out.append(f"コマンドが 1 行でない: {c}")
    all_source = "\n".join(sources.values())
    for flag in sorted(set(re.findall(r"(?<![A-Za-z0-9-])(--[a-z][a-z-]*)", body))):
        if f'"{flag}"' not in all_source:
            out.append(f"書いてあるオプションをどの入口も持っていない: {flag}")
    if "](" in body and re.search(r"\]\([^)]*(?:docs/|\.\./)", body):
        out.append("SKILL の外（docs/ や ../）へのクリックできるリンクがある（文字のパスで書く）")
    return out


class SkillEntryTest(unittest.TestCase):
    def sources(self) -> dict[str, str]:
        return {n: (SCRIPTS / n).read_text(encoding="utf-8") for n in entry_scripts()}

    def test_real_skill_md(self):
        text = SKILL_MD.read_text(encoding="utf-8")
        self.assertEqual(entry_scripts(), {"doctor.py", "adapt_tf.py", "adapt_cfn.py", "validate_ir.py", "find_aws_icon.py"})
        self.assertEqual(problems_in(text, entry_scripts(), self.sources()), [])
        self.assertGreaterEqual(len(commands(text)), 5)  # 空振りの防止

    def test_references_hold_only_the_runtime_rule_docs(self):
        # references/ は、validate_ir.py が読む規則表 3 つ（core/paths.py の RULE_DOCS）と、その説明の README.md だけ。
        # 開発者向けの仕様（ir-schema など）は SKILL の外の docs/spec/ に置く（PLAN の 1.4 の 2）
        from aws_iac_diagram.core import paths
        on_disk = {p.name for p in (SKILL / "references").iterdir()}
        self.assertEqual(on_disk, {p.name for p in paths.RULE_DOCS} | {"README.md"})

    def test_states_what_is_not_available(self):
        body = SKILL_MD.read_text(encoding="utf-8")
        self.assertIn("準備中", body)
        self.assertRegex(body, r"`diagram\.py`）と、draw\.io・Mermaid・PNG の出力はまだありません")

    def test_check_finds_problems(self):
        good = SKILL_MD.read_text(encoding="utf-8")
        entries, sources = entry_scripts(), self.sources()
        cases = {
            "入口が欠けている": good.replace("find_aws_icon.py", "find_nothing.py"),
            "シェルの機能": good.replace('--out "<出力先>/tf.raw.json"`', '--out "<出力先>/tf.raw.json" > x`'),
            "無いオプション": good.replace("--workspace <名前>", "--nosuchoption <名前>"),
            "保守用": good + "\n`uv run \"<SKILL>/scripts/maintenance/check_icons.py\"`\n",
            "docs へのリンク": good + "\n[spec](../../docs/spec/ir-schema/README.md)\n",
            "行数": good + "\n" * (MAX_LINES + 1),
            "frontmatter": good.replace("name: aws-iac-diagram\n", "name: aws-iac-diagram\nlicense: MIT\n"),
        }
        for label, text in cases.items():
            with self.subTest(label):
                self.assertNotEqual(problems_in(text, entries, sources), [], label)


if __name__ == "__main__":
    unittest.main()
