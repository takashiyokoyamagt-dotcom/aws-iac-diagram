"""Markdown の相対リンク（と、文書に書いたリポジトリ内のパス）が実在するかを調べる道具（tests/architecture/test_markdown_links.py が使う）。

- `[文字](相対パス#見出し)` と、参照形式の `[名前]: 相対パス` を読む。コードブロック（``` と ~~~）と、バッククォートで囲った所は読まない。
- `http(s):`・`mailto:` などの外部のリンクと、`#見出し` だけのリンクは、ファイルの存在は調べない（`#見出し` だけのものは同じ文書の中を調べる）。
- `#見出し` は、リンク先が .md のとき GitHub の見出しの ID の作り方（小文字にし、記号を除き、空白を `-` にする。同じ見出しは `-1`・`-2`）で調べる。
"""
from __future__ import annotations

import re
from pathlib import Path

from .paths import ROOT, WS

INLINE_LINK = re.compile(r"\[(?:[^\[\]]|\[[^\[\]]*\])*\]\(\s*(<[^>]*>|[^()\s]*(?:\([^()\s]*\)[^()\s]*)*)(?:\s+(?:\"[^\"]*\"|'[^']*'))?\s*\)")
REFERENCE_LINK = re.compile(r"^ {0,3}\[[^\]]+\]:\s*(<[^>]*>|\S+)", re.M)
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
EXTERNAL = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
HEADING = re.compile(r"^ {0,3}(#{1,6})\s+(.*?)\s*#*\s*$")


def strip_code(text: str) -> str:
    """コードブロックとインラインコードを空白にする（行数は保つ）。"""
    out: list[str] = []
    fence = ""
    for line in text.splitlines():
        m = FENCE.match(line)
        if fence:
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence) and line.strip() == m.group(1):
                fence = ""
            out.append("")
            continue
        if m:
            fence = m.group(1)
            out.append("")
            continue
        out.append(re.sub(r"(`+)[^`]*?\1", lambda mm: " " * len(mm.group(0)), line))
    return "\n".join(out)


def link_targets(text: str) -> list[str]:
    """文書の中のリンク先（コードの外）。`<…>` は外す。"""
    body = strip_code(text)
    found = [m.group(1) for m in INLINE_LINK.finditer(body)] + [m.group(1) for m in REFERENCE_LINK.finditer(body)]
    return [t[1:-1] if t.startswith("<") and t.endswith(">") else t for t in found]


def slug(heading: str) -> str:
    """GitHub の見出しの ID（重複の番号は付けない）。"""
    h = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", heading)  # リンクは文字だけ
    h = h.replace("`", "").replace("*", "")
    h = h.strip().lower()
    h = re.sub(r"[^\w\- ]", "", h)
    return h.replace(" ", "-")


def anchors(text: str) -> set[str]:
    out: set[str] = set()
    seen: dict[str, int] = {}
    for line in strip_code(text).splitlines():
        m = HEADING.match(line)
        if not m:
            continue
        base = slug(m.group(2))
        n = seen.get(base, 0)
        seen[base] = n + 1
        out.add(base if n == 0 else f"{base}-{n}")
    return out


def broken_links(files: list[Path], root: Path, contained_in: dict[Path, Path] | None = None) -> list[str]:
    """(ファイル: リンク先 理由) のうち、実在しない・見出しが無い・閉じ込めの外を指すもの。

    contained_in は {文書のあるフォルダ: そのリンクが出てはいけない外のフォルダの内側}。
    例: {skills/aws-iac-diagram: skills/aws-iac-diagram} は、その下の文書の相対リンクがその外を指すと失敗にする
    （SKILL は単独で配るので、文書の外へ行くクリックできるリンクを置かない）。
    """
    problems: list[str] = []
    for f in files:
        text = f.read_text(encoding="utf-8")
        rel = f.relative_to(root).as_posix()
        for raw in link_targets(text):
            if not raw or EXTERNAL.match(raw):
                continue
            path_part, _, frag = raw.partition("#")
            target = f if not path_part else (f.parent / path_part.replace("%20", " ")).resolve()
            if path_part and not target.exists():
                problems.append(f"{rel}: {raw} （無い）")
                continue
            if path_part:
                for base, inner in (contained_in or {}).items():
                    if base in f.parents and inner.resolve() not in target.parents and target != inner.resolve():
                        problems.append(f"{rel}: {raw} （{inner.name} の外を指している）")
                        break
            if frag and target.is_file() and target.suffix == ".md":
                if frag.lower() not in anchors(target.read_text(encoding="utf-8")):
                    problems.append(f"{rel}: {raw} （見出しが無い）")
    return problems


def repo_documents() -> list[Path]:
    """リンクを調べる文書: README・PLAN・docs（開発の経緯の dev-notes は除く）・SKILL の下・評価基準と fixture の説明。"""
    files = [ROOT / "README.md", ROOT / "PLAN.md", WS / "evals" / "CRITERIA.md", WS / "fixtures" / "README.md"]
    files += [p for p in sorted((ROOT / "docs").rglob("*.md")) if "dev-notes" not in p.relative_to(ROOT / "docs").parts]
    files += sorted((ROOT / "skills" / "aws-iac-diagram").rglob("*.md"))
    return files


# 文書・コメントに書いた docs/ の下のパス（`docs/spec/ir-schema/07-raw-output.md`、`docs/spec/ir-schema/`）。プレースホルダー（<…>）や * は対象外
DOCS_PATH = re.compile(r"(?<![A-Za-z0-9_/.<-])docs/(?:[A-Za-z0-9_][A-Za-z0-9_.-]*/)*(?:[A-Za-z0-9_][A-Za-z0-9_-]*\.md\b|(?=[ `）)、。,.;:\"']|$))")


def stale_doc_paths(files: list[Path], root: Path) -> list[str]:
    """(ファイル: パス) のうち、root の下に実在しない `docs/…` のパス。"""
    out = []
    for f in files:
        for m in sorted(set(DOCS_PATH.findall(f.read_text(encoding="utf-8")))):
            if not (root / m).exists():
                out.append(f"{f.name}: {m}")
    return out
