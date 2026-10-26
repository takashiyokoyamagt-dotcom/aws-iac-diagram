"""リポジトリの場所の定数と、import の道（sys.path）の設定。

import すると、SKILL の `scripts/`（入口のスクリプトとパッケージ aws_iac_diagram）と、開発用の `tools/` が sys.path の先頭に入る。
テストが SKILL を使う側と同じ入口の置き方で読むための、この 1 か所だけが sys.path をいじる（PLAN の 1.4。
docs/architecture.md の「テストの置き場」）。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]            # tests/support/paths.py → リポジトリのルート
SKILL = ROOT / "skills" / "aws-iac-diagram"
SCRIPTS = SKILL / "scripts"
DATA = SKILL / "data"
WS = ROOT / "aws-iac-diagram-workspace"
TOOLS = WS / "tools"
EXPECTED = WS / "expected"
FIXTURES_TF = WS / "fixtures" / "tf"
FIXTURES_CFN = WS / "fixtures" / "cfn"
PLANS = WS / "fixtures" / "tf-plan"
PUBLIC = WS / "fixtures" / "public"
ARCH_DOC = ROOT / "docs" / "architecture.md"


def add_to_sys_path(*dirs: Path) -> None:
    """各フォルダを sys.path の先頭に入れる（すでにあれば何もしない）。"""
    for d in dirs:
        s = str(d)
        if s not in sys.path:
            sys.path.insert(0, s)


add_to_sys_path(SCRIPTS, TOOLS)
