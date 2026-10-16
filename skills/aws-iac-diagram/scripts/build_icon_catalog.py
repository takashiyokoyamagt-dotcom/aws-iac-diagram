# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Sidebar-AWS4.js から AWS アイコン辞書を再生成する。

アイコン名は推測せず、draw.io のサイドバー定義に実在するエントリだけを辞書に載せる（PLAN 2.2 の 1）。
JS の解析は正規表現ではなく、Node 上で Sidebar をスタブ化して実行し、登録されたエントリを記録する。

出力:
  references/icons/catalog.json   機械用の辞書（find_aws_icon.py などが読む）
  references/icons/<category>.md  人と LLM 向けのカテゴリ別一覧（スタイル文字列は載せない）

壊れたアイコンの情報は references/icons/broken.json（check_icons.py の出力、C2）から読み、
各エントリの `broken`（と `broken_reason`）としてマージする。辞書を再生成しても消えない。

使い方: uv run scripts/build_icon_catalog.py [--sidebar PATH]
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
DEFAULT_SIDEBAR = SKILL_DIR / "assets" / "vendor" / "Sidebar-AWS4.js"
HARNESS = Path(__file__).resolve().parent / "lib" / "sidebar_harness.js"
OUT_DIR = SKILL_DIR / "references" / "icons"
BROKEN_JSON = OUT_DIR / "broken.json"


def run_harness(sidebar: Path) -> list[dict]:
    node = shutil.which("node")
    if not node:
        sys.exit("node が見つかりません。Node.js をインストールしてください。")
    res = subprocess.run(
        [node, str(HARNESS), str(sidebar)],
        capture_output=True, text=True, encoding="utf-8", check=False,
    )
    if res.returncode != 0:
        sys.exit(f"sidebar_harness.js が失敗しました:\n{res.stderr}")
    return json.loads(res.stdout)


def parse_style(style: str) -> dict[str, str]:
    out = {}
    for part in style.split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k] = v
    return out


def classify(e: dict) -> tuple[str, str]:
    """(kind, name) を返す。kind は PLAN 2.2 の 2 にある3系統 + その他。"""
    if e["kind"] == "edge":
        return "edge", slug(e["title"])
    st = parse_style(e["style"])
    shape = st.get("shape", "")
    if shape == "mxgraph.aws4.resourceIcon":
        return "resource_icon", st["resIcon"].removeprefix("mxgraph.aws4.")
    if shape in ("mxgraph.aws4.group", "mxgraph.aws4.groupCenter"):
        return "group", st["grIcon"].removeprefix("mxgraph.aws4.")
    if shape.startswith("mxgraph.aws4."):
        return "shape", shape.removeprefix("mxgraph.aws4.")
    # AZ・SG・Generic group など、AWS ステンシルを使わない矩形
    return "plain_group" if "container=1" in e["style"] or e["palette"] == "aws4Groups" else "plain", slug(e["title"])


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def category_of(e: dict) -> str:
    if e["palette"] == "aws4r":
        return "retired"
    return slug(e["palette"].removeprefix("aws4"))


def build(entries: list[dict]) -> list[dict]:
    catalog = []
    seen: dict[str, int] = {}
    for e in entries:
        # Illustrations は title が null でラベルを value に持つ
        e["title"] = " ".join((e["title"] or e["value"] or "").split())
    classified = [classify(e) for e in entries]
    # Private subnet と Public subnet のように grIcon を共有するグループは、title で区別する
    gr_count: dict[str, int] = {}
    for kind, name in classified:
        if kind == "group":
            gr_count[name] = gr_count.get(name, 0) + 1
    for e, (kind, name) in zip(entries, classified):
        if kind == "group" and gr_count[name] > 1:
            name = slug(e["title"])
        base = f"{kind}:{name}"
        seen[base] = seen.get(base, 0) + 1
        icon_id = base if seen[base] == 1 else f"{base}#{seen[base]}"
        title = e["title"]
        catalog.append({
            "id": icon_id,
            "kind": kind,
            "name": name,
            "title": title,
            "category": category_of(e),
            "palette_title": e["paletteTitle"],
            "retired": e["palette"] == "aws4r",
            "width": e["w"],
            "height": e["h"],
            "value": e["value"],
            "style": e["style"],
            # サイドバー側で join(' ') 済みの文字列が渡ってくる
            "tags": sorted(set((e["tags"] or "").split()) - {"aws", "amazon", "web", "service"}),
        })
    return catalog


def write_markdown(catalog: list[dict], out_dir: Path) -> list[Path]:
    by_cat: dict[str, list[dict]] = {}
    for c in catalog:
        by_cat.setdefault(c["category"], []).append(c)
    written = []
    for cat, items in by_cat.items():
        lines = [
            f"# {items[0]['palette_title']}",
            "",
            "<!-- 生成物: scripts/build_icon_catalog.py が出力。手で編集しない -->",
            "",
            "| id | title | kind | size | note |",
            "|---|---|---|---|---|",
        ]
        for c in items:
            note = f"**broken**: {c['broken_reason']}" if c.get("broken") else ""
            lines.append(f"| `{c['id']}` | {c['title']} | {c['kind']} | {c['width']}x{c['height']} | {note} |")
        p = out_dir / f"{cat}.md"
        p.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        written.append(p)
    return written


def strip_broken(catalog: list[dict]) -> list[dict]:
    """catalog.json を読み直したときに、前回マージした broken の情報を外す。"""
    return [{k: v for k, v in c.items() if k not in ("broken", "broken_reason")} for c in catalog]


def apply_broken(catalog: list[dict], sidebar: Path | None = None, broken_path: Path | None = None) -> list[dict]:
    """broken.json（check_icons.py の出力）を辞書にマージする。無ければ全件 broken=false。"""
    broken_path = BROKEN_JSON if broken_path is None else broken_path
    data = json.loads(broken_path.read_text(encoding="utf-8")) if broken_path.exists() else {"broken": []}
    reasons = {b["id"]: b["detail"] for b in data["broken"]}
    ids = {c["id"] for c in catalog}
    unknown = sorted(set(reasons) - ids)
    if unknown:
        print(f"注意: broken.json に辞書に無い id があります（check_icons.py を再実行してください）: {unknown}",
              file=sys.stderr)
    if sidebar is not None and broken_path.exists() and data.get("sidebar_sha256"):
        import hashlib
        if hashlib.sha256(sidebar.read_bytes()).hexdigest().upper() != data["sidebar_sha256"]:
            print("注意: broken.json は別の Sidebar-AWS4.js で作られています。check_icons.py を再実行してください。",
                  file=sys.stderr)
    for c in catalog:
        c["broken"] = c["id"] in reasons
        if c["broken"]:
            c["broken_reason"] = reasons[c["id"]]
    return catalog


def write_outputs(catalog: list[dict], out_dir: Path | None = None, sidebar: Path | None = DEFAULT_SIDEBAR,
                  broken_path: Path | None = None) -> list[Path]:
    """broken.json をマージして catalog.json とカテゴリ別 .md を書く（UTF-8・LF、順序固定）。

    out_dir と broken_path の既定は references/icons/（呼び出し時に解決する）。
    """
    out_dir = OUT_DIR if out_dir is None else out_dir
    broken_path = out_dir / "broken.json" if broken_path is None else broken_path
    catalog = apply_broken(catalog, sidebar, broken_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*.md"):
        old.unlink()
    (out_dir / "catalog.json").write_text(
        json.dumps(catalog, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n",
    )
    return write_markdown(catalog, out_dir)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sidebar", type=Path, default=DEFAULT_SIDEBAR)
    args = ap.parse_args()

    catalog = build(run_harness(args.sidebar))
    mds = write_outputs(catalog, sidebar=args.sidebar)

    kinds: dict[str, int] = {}
    for c in catalog:
        kinds[c["kind"]] = kinds.get(c["kind"], 0) + 1
    print(f"{len(catalog)} entries, {len(mds)} categories -> {OUT_DIR}")
    print("  " + ", ".join(f"{k}={v}" for k, v in sorted(kinds.items())))
    print(f"  broken={sum(c['broken'] for c in catalog)}" + ("" if BROKEN_JSON.exists() else "（broken.json なし。check_icons.py で作る）"))


if __name__ == "__main__":
    main()
