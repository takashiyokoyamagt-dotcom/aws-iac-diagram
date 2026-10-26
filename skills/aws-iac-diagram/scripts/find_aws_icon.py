# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""AWS アイコン辞書（data/icons/catalog.json）を検索する。

辞書全体を LLM に読ませる代わりに、このスクリプトで必要なエントリだけを引く。
スタイル文字列は辞書にあるものをそのまま使い、手で組み立てないこと（PLAN 2.2 の 1〜3）。
退役アイコン（retired）と、check_icons.py が壊れていると判定したアイコン（broken、C2）は既定で除外する。

使い方:
  uv run scripts/find_aws_icon.py lambda
  uv run scripts/find_aws_icon.py "application load balancer" --kind shape --limit 3
  uv run scripts/find_aws_icon.py --id resource_icon:lambda --json
  uv run scripts/find_aws_icon.py dynamodb --include-broken
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from aws_iac_diagram.core import paths  # noqa: E402

CATALOG = paths.ICON_CATALOG
KINDS = ("resource_icon", "shape", "group", "plain_group", "plain", "edge")


def load() -> list[dict]:
    if not CATALOG.exists():
        sys.exit(f"{CATALOG} がありません。先に scripts/maintenance/build_icon_catalog.py を実行してください。")
    return json.loads(CATALOG.read_text(encoding="utf-8"))


def score(entry: dict, terms: list[str]) -> int:
    title = entry["title"].lower()
    name = entry["name"].lower()
    words = set(title.split()) | set(name.split("_")) | set(entry["tags"])
    s = 0
    for t in terms:
        if t == name or t == title:
            s += 100
        elif t in words:
            s += 10
        elif t in title or t in name:
            s += 3
        else:
            return 0  # すべての語を含むものだけを返す
    if " ".join(terms) == title:
        s += 100
    if entry["retired"]:
        s -= 50
    return s


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("query", nargs="*", help="検索語（AND 検索）")
    ap.add_argument("--id", help="id で完全一致検索")
    ap.add_argument("--kind", choices=KINDS)
    ap.add_argument("--include-retired", action="store_true")
    ap.add_argument("--include-broken", action="store_true", help="壊れていると判定されたアイコンも表示する")
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--json", action="store_true", help="スタイル文字列を含む JSON で出力")
    args = ap.parse_args()

    catalog = load()
    if args.id:
        hits = [c for c in catalog if c["id"] == args.id]
        for c in hits:
            if c.get("broken"):
                print(f"注意: {c['id']} は描画が壊れています（{c.get('broken_reason', '')}）。使わないでください。",
                      file=sys.stderr)
    else:
        terms = [t.lower() for t in " ".join(args.query).split()]
        if not terms:
            ap.error("検索語か --id を指定してください")
        scored = []
        for i, c in enumerate(catalog):
            if args.kind and c["kind"] != args.kind:
                continue
            if c["retired"] and not args.include_retired:
                continue
            if c.get("broken") and not args.include_broken:
                continue
            s = score(c, terms)
            if s > 0:
                scored.append((-s, i, c))
        hits = [c for _, _, c in sorted(scored)[: args.limit]]

    if args.json:
        print(json.dumps(hits, ensure_ascii=False, indent=1))
        return
    if not hits:
        print("該当なし")
        sys.exit(1)
    for c in hits:
        mark = "\tBROKEN" if c.get("broken") else ""
        print(f"{c['id']}\t{c['title']}\t{c['kind']}\t{c['width']}x{c['height']}\t[{c['category']}]{mark}")


if __name__ == "__main__":
    main()
