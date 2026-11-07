"""正規化の中の順序のテスト（フェーズ 3 の手順 3a）。

normalize の中のファイルを、段階のグループ（view → classify・names → nodes → build）に分ける。下のグループ（前の段階）は上の
グループ（後の段階）を import しない。表（support/arch_layers.py の NORMALIZE_GROUPS・INTRA_NORMALIZE）は docs/architecture.md の
表と同じ（食い違えば失敗）。一時フォルダにコピーした構成に、わざと逆向きの import を入れて、検査が失敗することも確かめる。
"""

from __future__ import annotations

import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

# tests/ を import の道に入れる（`python tests/.../test_x.py` で直接動かすときのため。discover では要らないが害は無い）
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "support").is_dir())))
from support.arch_layers import (
    INTRA_NORMALIZE,
    NORMALIZE_GROUPS,
    PACKAGE,
    check_allowed_table,
    violations_in_normalize_order,
)
from support.paths import ARCH_DOC, SCRIPTS


class NormalizeOrderTest(unittest.TestCase):
    """normalize の中の前の段階 → 後の段階の import を禁じる決まり（docs/architecture.md の「正規化の中身」）。"""

    def copy_tree(self) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        dst = Path(tmp.name) / "scripts"
        shutil.copytree(SCRIPTS, dst, ignore=shutil.ignore_patterns("__pycache__"))
        return dst

    def inject(self, scripts: Path, relpath: str, line: str) -> list[str]:
        f = scripts / PACKAGE / "normalize" / relpath
        f.write_text(f.read_text(encoding="utf-8") + "\n" + line + "\n", encoding="utf-8", newline="\n")
        problems, _ = violations_in_normalize_order(scripts)
        return problems

    def test_real_tree_follows_the_order(self):
        problems, edges = violations_in_normalize_order(SCRIPTS)
        self.assertEqual(problems, [], "\n".join(problems))
        # 空振りの防止: 表にある辺はすべて実際に使われている（古い許可を残さない）
        self.assertEqual(edges, {(a, b) for a, bs in INTRA_NORMALIZE.items() for b in bs})

    def test_table_is_consistent(self):
        self.assertEqual(set(INTRA_NORMALIZE), set(NORMALIZE_GROUPS))
        self.assertEqual(check_allowed_table(INTRA_NORMALIZE), [])
        members = [m for ms in NORMALIZE_GROUPS.values() for m in ms]
        self.assertEqual(len(members), len(set(members)))
        base = SCRIPTS / PACKAGE / "normalize"
        tops = {p.stem if p.is_file() else p.name for p in base.iterdir()
                if (p.suffix == ".py" or p.is_dir()) and p.name not in ("__init__.py", "__pycache__")}
        self.assertEqual(sorted(tops - set(members)), [])
        self.assertEqual(sorted(set(members) - tops), [])

    def test_docs_table_matches(self):
        text = ARCH_DOC.read_text(encoding="utf-8")
        start = text.index("<!-- normalize-order:begin -->")
        end = text.index("<!-- normalize-order:end -->")
        groups, allowed = {}, {}
        for line in text[start:end].splitlines():
            m = re.match(r"^\|\s*`([a-z_]+)`\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*$", line)
            if m:
                groups[m.group(1)] = set(re.findall(r"`([a-z_]+)`", m.group(2)))
                allowed[m.group(1)] = frozenset(re.findall(r"`([a-z_]+)`", m.group(3)))
        self.assertEqual(groups, {g: set(ms) for g, ms in NORMALIZE_GROUPS.items()},
                         "docs/architecture.md のグループの表と NORMALIZE_GROUPS が食い違う")
        self.assertEqual(allowed, INTRA_NORMALIZE, "docs/architecture.md の表と INTRA_NORMALIZE が食い違う")

    def test_mutation_earlier_stages_importing_later_stages_fail(self):
        nm = "from aws_iac_diagram.normalize"
        cases = (
            ("view.py", f"{nm}.classify import Decision", "グループ view はグループ classify"),
            ("view.py", f"{nm} import build", "グループ view はグループ build"),
            ("names.py", f"{nm}.nodes import build_nodes", "グループ classify はグループ nodes"),
            ("classify.py", f"{nm}.build import normalize", "グループ classify はグループ build"),
            ("nodes.py", f"{nm}.build import normalize", "グループ nodes はグループ build"),
            ("names.py", "from . import nodes", "グループ classify はグループ nodes"),
        )
        for relpath, line, expect in cases:
            s = self.copy_tree()
            problems = self.inject(s, relpath, line)
            self.assertTrue(any(expect in p and p.startswith("aws_iac_diagram/normalize/" + relpath + ":") for p in problems),
                            (relpath, line, problems))

    def test_mutation_new_file_outside_the_groups_fails(self):
        s = self.copy_tree()
        (s / PACKAGE / "normalize" / "output.py").write_text("X = 1\n", encoding="utf-8")
        problems, _ = violations_in_normalize_order(s)
        self.assertTrue(any("output.py" in p and "normalize のグループに無い" in p for p in problems), problems)


if __name__ == "__main__":
    unittest.main()
