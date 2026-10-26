"""構成の検査の道具: 1ファイルの行数（800 行で注意、1,500 行で失敗。超えているファイルは EXEMPT に日付と理由を付けて書く）。"""

from __future__ import annotations

import re
from pathlib import Path


WARN_LINES = 800

MAX_LINES = 1500

# 1,500 行を超えているファイルの免除（scripts/ からの相対パス）。R2 で空にした（今は 1,500 行を超えるファイルが無い）。
# 免除を足すときは、日付（since）・上限（ceiling = 決めた日の行数。超えて増えたら失敗）・外す手順（remove_in）・理由を付け、
# 下の test_no_exemptions_remain も直す（理由をコミットメッセージに書く）。
EXEMPT: dict[str, dict] = {}


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
