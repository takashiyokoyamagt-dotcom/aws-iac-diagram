"""文書・CI・コメントに書いた `tests/…/*.py`（と `.json`）のパスが、実在するファイルを指すこと（フェーズ 2b の R5 のレビューの指摘）。

テストのファイルを動かしたとき、README・docs（docs/spec/ir-schema/ を含む）・PLAN・ci.yml・スクリプトのコメントに古いパスが残るのを失敗にする。
対象は、開発の経緯を書いた docs/dev-notes/（当時の名前のまま残す）以外。
"""
from __future__ import annotations

import re
import sys
import tempfile
import unittest
from pathlib import Path

# tests/ を import の道に入れる（`python tests/.../test_x.py` で直接動かすときのため。discover では要らないが害は無い）
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "support").is_dir())))
from support.paths import ROOT, SCRIPTS, TOOLS, WS  # noqa: E402

PATH_RE = re.compile(r"(?<![A-Za-z0-9_/.-])tests/[A-Za-z0-9_][A-Za-z0-9_./-]*[.](?:py|json)(?![A-Za-z0-9_])")


def documents() -> list[Path]:
    files = [ROOT / "README.md", ROOT / "PLAN.md", ROOT / ".github" / "workflows" / "ci.yml",
             WS / "fixtures" / "README.md"]
    files += [p for p in sorted((ROOT / "docs").rglob("*.md")) if "dev-notes" not in p.relative_to(ROOT / "docs").parts]
    files += [p for base in (SCRIPTS, TOOLS) for p in sorted(base.rglob("*.py")) if "__pycache__" not in p.parts]
    return files


def stale_paths(files: list[Path], root: Path) -> list[str]:
    """(ファイル: パス) のうち、root の下に実在しないもの。"""
    out = []
    for f in files:
        for m in sorted(set(PATH_RE.findall(f.read_text(encoding="utf-8")))):
            if not (root / m).is_file():
                out.append(f"{f.name}: {m}")
    return out


class DocumentedPathsTest(unittest.TestCase):
    def test_every_documented_test_path_exists(self):
        files = documents()
        self.assertGreaterEqual(len(files), 20)  # 空振りの防止
        self.assertEqual(stale_paths(files, ROOT), [])

    def test_the_check_finds_stale_paths(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            (root / "tests" / "unit").mkdir(parents=True)
            (root / "tests" / "unit" / "test_ok.py").write_text("", encoding="utf-8")
            doc = root / "doc.md"
            doc.write_text("`tests/unit/test_ok.py` は在る。`tests/test_old.py` と `tests/unit/gone.json` は無い。tests/unit/ だけは対象外。",
                           encoding="utf-8")
            self.assertEqual(stale_paths([doc], root), ["doc.md: tests/test_old.py", "doc.md: tests/unit/gone.json"])

    def test_real_documents_do_mention_test_paths(self):
        # 空振りの防止: 少なくとも architecture.md・README・07-raw-output.md（ir-schema の 7 章）・ci.yml が実際のパスを書いている
        names = {f.name for f in documents() if PATH_RE.search(f.read_text(encoding="utf-8"))}
        self.assertTrue({"architecture.md", "README.md", "07-raw-output.md", "ci.yml"} <= names, names)


if __name__ == "__main__":
    unittest.main()
