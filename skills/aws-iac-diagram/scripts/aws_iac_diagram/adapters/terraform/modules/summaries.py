"""A5 の要約表（data/module-summaries/）の読み込みと、IAM だけを作るモジュールの見分け。

モジュールの展開（module_expand.py）と、フェーズ3 の正規化（IAM だけのモジュールの H-IAM）が使う。

要約表は `data/module-summaries/<モジュール>/v<メジャー>.md`（1 モジュールの 1 major につき 1 ファイル。サブモジュールの
表は親と同じファイルに入れる）。Markdown の中の HCL のコードブロックで、直前の行に
  <!-- module-summary source="terraform-aws-modules/vpc/aws" majors="6" -->
と書く（source はレジストリの source。サブモジュールは "//modules/x" を付ける。majors は対象の版の major）。
中身は、本物のモジュールの主要なリソース（count・for_each の条件と、名前・参照の属性）と出力だけを
同じ書き方で写したもの。アダプタは、手元のモジュールと同じように評価する（ir-schema.md の 7.2）。
コードブロックの中の "# not-covered: a, b" の行に書いた変数（要約表に写していないリソースを作る入力）は、
呼び出しで渡されたら、宣言の無い入力と同じく診断（TF-MODULE-SUMMARY-INPUT）に書く。

IAM だけを作るモジュールの source は、`data/module-summaries/iam-only-sources.md` の
  <!-- iam-only-sources -->
の直後のコードブロックに1行に1つ書く（サブモジュール "//…" も含む）。

**読むファイルは名前で決まっている**: `<モジュール>/v<数字>.md`（1 階層下。大文字小文字を区別する。OS に依らない）と、
直下の `iam-only-sources.md` だけ。ほかのファイル（`NOTICE.md` など）は、中にマーカーがあっても読まない（`problems()` が、
`NOTICE.md` 以外の読まれない .md を知らせる）。順序は決まっている（モジュールのフォルダ名、major の数、パス）ので、同じ source の
表が複数あっても、選ばれる表は読む場所や OS に依らない。

**限界**: フォルダの中にレジストリモジュールの表が 1 つも無いことは `resolve.blackbox_plan` が `TF-MODULE-SUMMARY-TABLE-MISSING` にする
（`KNOWN_MODULES`）。モジュールの表はあるが、呼び出しの版の major のファイルが無いときは、これまでどおり黒箱（info の
`TF-MODULE-BLACKBOX`）で、欠けたファイルは doctor の `REQUIRED_FILES` が知らせる。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from aws_iac_diagram.adapters.terraform.modules.sources import registry_key
from aws_iac_diagram.core.paths import MODULE_SUMMARIES_DIR

# 要約表のディレクトリ（テストは、無い場所や空の場所に差し替えて、表が無いときの扱いを確かめる）
SUMMARY_DIR = MODULE_SUMMARIES_DIR

# 要約表があるはずのレジストリモジュール（サブモジュールを除く）。出荷した表と同じであることをテストが確かめる。
# 表を足したら（別のモジュールの表）ここにも足す
KNOWN_MODULES = frozenset({
    "terraform-aws-modules/vpc/aws",
    "terraform-aws-modules/alb/aws",
    "terraform-aws-modules/rds/aws",
    "terraform-aws-modules/eks/aws",
})

TABLE_FILE = re.compile(r"v([0-9]{1,9})\.md")  # <モジュール>/v6.md（大文字小文字を区別する）
IAM_FILE = "iam-only-sources.md"
DOC_FILES = frozenset({"NOTICE.md"})  # 読まない（書き手向けの表示）。problems() が「読まれない .md」から除く

_MARK = re.compile(r'<!--\s*module-summary\s+source="([^"]+)"\s+majors="([0-9, ]+)"\s*-->')
_IAM_MARK = re.compile(r"<!--\s*iam-only-sources\s*-->")
_FENCE = re.compile(r"^```[a-z]*\s*$")


@dataclass(frozen=True)
class Summary:
    source: str  # 要約表の source（レジストリの source。サブモジュールは //modules/x 付き）
    majors: tuple  # 対象の版の major
    text: str  # HCL
    line: int  # file の中の行（1 始まり。コードブロックの最初の行）
    uncovered: tuple = ()  # 要約表に写していないリソースを作る入力（# not-covered: の行）
    file: str = ""  # 読んだファイル（SUMMARY_DIR からの相対パス。/ 区切り）


_CACHE: dict = {}


def _fenced_after(lines: list[str], i: int) -> tuple[str, int] | None:
    """lines[i] の後ろの最初のコードブロックの中身と、その最初の行の番号（0 始まり）。"""
    j = i + 1
    while j < len(lines) and not lines[j].strip():
        j += 1
    if j >= len(lines) or not _FENCE.match(lines[j].strip()):
        return None
    k = j + 1
    while k < len(lines) and lines[k].strip() != "```":
        k += 1
    return "\n".join(lines[j + 1:k]) + "\n", j + 1


def _listing(path: Path) -> tuple[list[tuple[tuple, str, Path]], list[str]]:
    """フォルダの中身を (読むファイル, 読まない .md) に分ける。読むファイルは (並べ方のキー, 相対パス, 実体) を決まった順序で。

    読むのは `<モジュール>/v<数字>.md` と直下の `iam-only-sources.md` だけ（名前は大文字小文字を区別して完全一致）。
    キーは (モジュールのフォルダ名, major の数, 相対パス)。`iterdir` の順序には依らない。"""
    read: list[tuple[tuple, str, Path]] = []
    ignored: list[str] = []
    try:
        entries = sorted(path.iterdir(), key=lambda p: p.name)
        for e in entries:
            if e.is_file():
                if e.name == IAM_FILE:
                    read.append((("", 0, e.name), e.name, e))
                elif e.name.endswith(".md") and e.name not in DOC_FILES:
                    ignored.append(e.name)
            elif e.is_dir():
                for f in sorted(e.iterdir(), key=lambda p: p.name):
                    rel = f"{e.name}/{f.name}"
                    m = TABLE_FILE.fullmatch(f.name)
                    if m and f.is_file():
                        read.append(((e.name, int(m.group(1)), rel), rel, f))
                    elif f.name.lower().endswith(".md") and f.name not in DOC_FILES or f.is_dir():
                        ignored.append(rel)
    except OSError:
        return [], ignored
    return sorted(read, key=lambda x: x[0]), sorted(ignored)


def _files(path: Path) -> list[tuple[str, Path]]:
    """読むファイル（相対パスと実体）を決まった順序で。path がファイルならそれ 1 つ。無い・読めなければ空。"""
    try:
        if path.is_file():
            return [(path.name, path)]
        if not path.is_dir():
            return []
    except OSError:
        return []
    return [(rel, f) for _, rel, f in _listing(path)[0]]


def _read(f: Path, rel: str, summaries: dict, iam: list, bad: list | None = None) -> None:
    """f を読んで summaries（source -> [Summary]）と iam に足す。コードブロックの無いマーカーの行番号は bad に足す。"""
    try:
        lines = f.read_text(encoding="utf-8").replace("\r\n", "\n").split("\n")
    except OSError:
        if bad is not None:
            bad.append("読めない")
        return
    for i, line in enumerate(lines):
        m = _MARK.search(line)
        if m:
            got = _fenced_after(lines, i)
            if got is not None:
                majors = tuple(sorted({int(x) for x in m.group(2).replace(" ", "").split(",") if x}))
                uncovered = tuple(sorted({x.strip() for ln in got[0].splitlines()
                                          if ln.strip().startswith("# not-covered:")
                                          for x in ln.split(":", 1)[1].split(",") if x.strip()}))
                summaries.setdefault(m.group(1), []).append(Summary(m.group(1), majors, got[0], got[1] + 1,
                                                                    uncovered, rel))
            elif bad is not None:
                bad.append(f"{i + 1} 行目のマーカー {m.group(1)} の後にコードブロックが無い")
        elif _IAM_MARK.search(line):
            got = _fenced_after(lines, i)
            if got is not None:
                iam += [x.strip() for x in got[0].splitlines() if x.strip() and not x.strip().startswith("#")]
            elif bad is not None:
                bad.append(f"{i + 1} 行目の iam-only-sources の後にコードブロックが無い")


def load(path: Path | None = None) -> tuple[dict, tuple]:
    """要約表を読む。({source: [Summary]}, IAM だけのモジュールの source の並び)。読めなければ空。

    path は要約表のディレクトリ（省略すると SUMMARY_DIR）。ファイルを渡すと、そのファイルだけを読む。"""
    path = path or SUMMARY_DIR
    key = str(path)
    if key in _CACHE:
        return _CACHE[key]
    summaries: dict = {}
    iam: list = []
    for rel, f in _files(path):
        _read(f, rel, summaries, iam)
    _CACHE[key] = (summaries, tuple(iam))
    return _CACHE[key]


def problems(path: Path | None = None) -> list[str]:
    """フォルダの中の、置き方の誤りを文で返す（空なら問題なし）。出荷した表を調べる（テストと doctor）。

    調べること: ① 読まれない .md がある（名前の綴り・大文字小文字・深さの誤り。`NOTICE.md` は除く）、② 読まれるファイルが空・読めない・
    コードブロックの無いマーカーがある、③ ファイル名の major と `majors` が合わない、④ フォルダ名と source が合わない
    （`terraform-aws-modules/vpc/aws` は `terraform-aws-vpc/`）、⑤ 同じ (source, major) の表が複数ある、⑥ `v06.md` のような正規でない名前。
    ファイルが無いこと（欠け）は調べない（doctor の `REQUIRED_FILES` が知らせる）。"""
    path = path or SUMMARY_DIR
    out: list[str] = []
    try:
        if not path.is_dir():
            return out
    except OSError:
        return out
    read, ignored = _listing(path)
    out += [f"{rel}: ローダーが読まない名前の .md（v<数字>.md か iam-only-sources.md の綴り・大文字小文字・深さの誤り）" for rel in ignored]
    seen: dict = {}
    for key, rel, f in read:
        summaries: dict = {}
        iam: list = []
        bad: list = []
        _read(f, rel, summaries, iam, bad)
        out += [f"{rel}: {b}" for b in bad]
        if rel == IAM_FILE:
            if not iam:
                out.append(f"{rel}: source が 1 つも無い")
            continue
        mod, major, _ = key
        if rel != f"{mod}/v{major}.md":
            out.append(f"{rel}: 正規でない名前（v{major}.md）")
        if not summaries and not bad:
            out.append(f"{rel}: 要約表（<!-- module-summary … -->）が 1 つも無い")
        for source, items in summaries.items():
            parts = source.partition("//")[0].split("/")
            want = f"terraform-{parts[2]}-{parts[1]}" if len(parts) == 3 else None
            if want != mod:
                out.append(f"{rel}: source {source} はフォルダ {want} に置く")
            for s in items:
                if s.majors != (major,):
                    out.append(f"{rel}: majors {list(s.majors)}（source {source}）がファイル名の major {major} と合わない")
                for mj in s.majors:
                    seen.setdefault((source, mj), []).append(rel)
    out += [f"同じ (source, major) = {k} の表が複数ある: {', '.join(v)}" for k, v in sorted(seen.items()) if len(v) > 1]
    return out


def iam_only(source: str, path: Path | None = None) -> bool:
    """IAM のリソースだけを作るモジュールか（正規化の H-IAM。ir-schema.md の 2章）。"""
    key = registry_key(source)
    if key is None:
        return False
    for s in load(path)[1]:
        if key == s or key.startswith(s + "//") or (s.endswith("//") and key.startswith(s)):
            return True
    return False
