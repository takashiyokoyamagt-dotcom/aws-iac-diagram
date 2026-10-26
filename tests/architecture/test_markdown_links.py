"""Markdown の相対リンクが実在すること（フェーズ 2b の R6）。

README・PLAN・docs/（開発の経緯の dev-notes を除く）・SKILL の下の .md・評価基準・fixture の説明の、相対リンク（`[文字](パス#見出し)` と参照形式）が、
実在するファイルかフォルダを指し、`#見出し` がリンク先にあること。SKILL の下の文書のリンクは SKILL のフォルダの外を指さない
（SKILL は単独で配るので、docs/ などへのクリックできるリンクは置かず、リポジトリの中のパスを文字で書く）。
あわせて、文書・コメントに文字で書いた `docs/…` のパスも実在すること。道具は tests/support/md_links.py。
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

# tests/ を import の道に入れる（`python tests/.../test_x.py` で直接動かすときのため。discover では要らないが害は無い）
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "support").is_dir())))
from support.md_links import anchors, broken_links, link_targets, repo_documents, slug, stale_doc_paths  # noqa: E402
from support.paths import ROOT, SCRIPTS, SKILL, TOOLS  # noqa: E402

# 他のリポジトリの docs/ のファイルを指している（このリポジトリのファイルではない。PLAN の 2.1）
FOREIGN_DOCS = {"docs/LEARNINGS_DRAWIO_NATIVE.md"}


def documents_with_paths() -> list[Path]:
    files = repo_documents() + [ROOT / ".github" / "workflows" / "ci.yml"]
    files += [p for base in (SCRIPTS, TOOLS, ROOT / "tests") for p in sorted(base.rglob("*.py")) if "__pycache__" not in p.parts]
    return [p for p in files if p != Path(__file__).resolve()]  # このファイルは検査の例（実在しないパス）を書いている


def write(root: Path, rel: str, text: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8", newline="\n")
    return p


class RealLinksTest(unittest.TestCase):
    def test_relative_links_resolve(self):
        files = repo_documents()
        self.assertGreaterEqual(len(files), 40)  # 空振りの防止（SKILL の下の .md を含む）
        links = [t for f in files for t in link_targets(f.read_text(encoding="utf-8"))]
        self.assertGreaterEqual(len(links), 40, len(links))  # リンクを 1 つも読めていないのに通る、を防ぐ
        self.assertEqual(broken_links(files, ROOT, {SKILL: SKILL}), [])

    def test_the_skill_documents_have_no_link_leaving_the_skill(self):
        # SKILL の下の文書のリンクが、SKILL の外（docs/ など）へ出ない。出る参照は、文字のパス（リポジトリの中の場所）で書く
        for f in sorted(SKILL.rglob("*.md")):
            for t in link_targets(f.read_text(encoding="utf-8")):
                if "://" in t or t.startswith(("#", "mailto:")):
                    continue
                target = (f.parent / t.partition("#")[0]).resolve()
                self.assertTrue(target == SKILL or SKILL in target.parents, f"{f.relative_to(ROOT).as_posix()}: {t}")

    def test_documented_docs_paths_exist(self):
        files = documents_with_paths()
        self.assertGreaterEqual(len(files), 100)  # 空振りの防止
        stale = [s for s in stale_doc_paths(files, ROOT) if s.split(": ", 1)[1] not in FOREIGN_DOCS]
        self.assertEqual(stale, [])
        # 空振りの防止: 実際に docs/ のパスを書いている文書がある
        self.assertTrue(any(stale_doc_paths([f], Path("/nonexistent-root")) for f in files))


class CheckerTest(unittest.TestCase):
    """検査そのものが、壊れたリンクを見つける（一時フォルダに作った文書で）。"""

    def test_finds_broken_links_exactly(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            a = write(root, "a.md", "[gone](nothing.md) [bad](b.md#nope) [self](#nope) [ok](b.md#b) [ok2](b.md \"t\")\n[r]: ./missing.md\n")
            write(root, "b.md", "# B\n")
            self.assertEqual(sorted(p.split(": ", 1)[1] for p in broken_links([a], root)),
                             sorted(["nothing.md （無い）", "b.md#nope （見出しが無い）", "#nope （見出しが無い）", "./missing.md （無い）"]))

    def test_ignores_code_and_external(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            a = write(root, "a.md", "`[x](nothing.md)` と\n```\n[y](nothing2.md)\n```\n~~~\n[z](nothing3.md)\n~~~\n"
                      "[web](https://example.com/none.md) [mail](mailto:a@example.com) <[w](nowhere.md)>\n")
            self.assertEqual([p.split(": ", 1)[1] for p in broken_links([a], root)], ["nowhere.md （無い）"])

    def test_skill_links_must_stay_inside(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            skill = root / "skills" / "s"
            a = write(root, "skills/s/SKILL.md", "[ok](references/r.md) [out](../../docs/x.md)\n")
            write(root, "skills/s/references/r.md", "# R\n")
            write(root, "docs/x.md", "# X\n")
            self.assertEqual([p.split(": ", 1)[1] for p in broken_links([a], root, {skill: skill})], ["../../docs/x.md （s の外を指している）"])
            self.assertEqual(broken_links([a], root), [])  # 閉じ込めを指定しなければ、実在すれば通る

    def test_anchor_rules(self):
        self.assertEqual(slug("7.5 診断"), "75-診断")
        self.assertEqual(slug("`code` の「一覧」(43 個)"), "code-の一覧43-個")
        self.assertEqual(anchors("# A\n## A\n## A\n```\n# no\n```\n"), {"a", "a-1", "a-2"})

    def test_stale_docs_paths(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            write(root, "docs/spec/x/ok.md", "")
            write(root, "docs/spec/y/.keep", "")
            doc = write(root, "d.md", "`docs/spec/x/ok.md` と docs/spec/y/ は在る。`docs/spec/x/gone.md` と docs/spec/z/ は無い。docs/<名前>.md は対象外。")
            self.assertEqual(stale_doc_paths([doc], root), ["d.md: docs/spec/x/gone.md", "d.md: docs/spec/z/"])


if __name__ == "__main__":
    unittest.main()
