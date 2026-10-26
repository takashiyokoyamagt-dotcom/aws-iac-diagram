"""規則表（SKILL の data/rules/）を一時フォルダにコピーして、わざと壊して読むための道具。

読み込み（core/rules.py）の検査は、`H-IAM` の `module_sources_file` が SKILL の下にあることも調べる（`<SKILL>/data/rules/` の 2 つ上が SKILL）ので、
コピーは SKILL と同じ並び（`<一時>/skill/data/rules/` と `data/module-summaries/iam-only-sources.md`）にする。
"""
from __future__ import annotations

import shutil
from pathlib import Path

from support.paths import DATA


def copy_rules(tmp: Path) -> Path:
    """規則表のコピーを作り、そのフォルダ（`<tmp>/skill/data/rules`）を返す。"""
    skill = tmp / "skill"
    shutil.copytree(DATA / "rules", skill / "data" / "rules")
    (skill / "data" / "module-summaries").mkdir(parents=True)
    shutil.copyfile(DATA / "module-summaries" / "iam-only-sources.md", skill / "data" / "module-summaries" / "iam-only-sources.md")
    return skill / "data" / "rules"


def edit(rules_dir: Path, rel: str, old: str, new: str, count: int = 1) -> None:
    """rules_dir/rel の中の old を new に置き換える（old がちょうど count 回あること）。"""
    p = rules_dir / rel
    text = p.read_text(encoding="utf-8")
    found = text.count(old)
    if found != count:
        raise AssertionError(f"{rel}: {old!r} が {found} 回ある（{count} 回のはず）")
    p.write_text(text.replace(old, new), encoding="utf-8", newline="\n")
