# /// script
# requires-python = ">=3.12"
# dependencies = ["Pillow==12.3.0"]
# ///
"""辞書の全アイコンを draw.io で実際に描画し、壊れたアイコンを検出する（PLAN 4 の C2）。

流れ:
  1. catalog.json の描画対象（shape・resource_icon・group）を、辞書のスタイルのまま
     複数ページの .drawio にグリッドで並べる。各アイコンの右隣には、ステンシル名
     （shape= / resIcon= / grIcon=）だけを存在しない名前に差し替えた「参照」を描く。
     各ページの最背面に背景矩形を置き（PLAN 2.2 の 11）、背景の左上と右下に位置合わせ用のマーカーを置く。
  2. draw.io Desktop で各ページを PNG に書き出す（`--scale` は使わない。PLAN 2.2 の 12）。
  3. マーカーの位置から .drawio 座標 → PNG 画素の倍率とオフセットを求め、セルごとに切り出して判定する。
     判定の順序は次のとおりで、最初に当てはまったものを理由とする。
       empty            空箱: ほぼ何も描かれていない（fillColor が無い等）
       black            黒塗り: ほぼ全体が黒
       solid            単色: ほぼ全体が白以外の1色（ステンシルが無く塗りの矩形になる）
       stencil_missing  ステンシル名を存在しない名前にした参照と画素がほぼ同じ
                        （グラデーションの正方形だけになる resourceIcon や、アイコンの無い group 枠）
     group は枠と隅の小さなアイコンだけで中が空なのが正常なので、stencil_missing だけで判定する。
  4. 結果を references/icons/broken.json に書き、build_icon_catalog の出力処理で
     catalog.json とカテゴリ別 .md に `broken` を反映する。build_icon_catalog.py を再実行しても
     broken.json を読んでマージするので消えない。

描画しないもの:
  edge         矢印のスタイルで、ステンシルを参照しない（壊れようがない）。頂点として描くと判定も意味をなさない
  plain_group  AZ・SG など AWS ステンシルを使わないただの矩形。何も描かれない内側が正常なので判定できない

検出できないもの（README の C2 節にも記載）:
  - 一部だけ欠ける・崩れる（参照とも違い、単色でもない）
  - 別の実在アイコンに置き換わる（描画は正常に見える）

自己検査: 壊れ方が分かっている対照と正常な対照（CONTROLS 参照。壊れ 6 種・正常 3 種）を同じ図に描き、
期待どおりに判定されなければ異常終了して辞書を更新しない。

使い方:
  uv run scripts/check_icons.py                # 描画・判定して broken.json と辞書を更新
  uv run scripts/check_icons.py --no-write     # 判定だけ（辞書は更新しない）
  uv run scripts/check_icons.py --work-dir DIR # .drawio・PNG・report.json の置き場所

辞書の保守用。開発リポジトリの中でだけ使う（既定の作業ディレクトリは SKILL のフォルダの2つ上を
リポジトリのルートとみなして決める。配布先では SKILL.md から呼ばない）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import quoteattr

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from lib.drawio_cli import DrawioError, drawio_version, export_png, find_drawio  # noqa: E402

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    sys.exit("Pillow がありません: uv run で起動してください（依存はスクリプト先頭の PEP 723 の宣言にあります）。")

SKILL_DIR = SCRIPTS_DIR.parent
REPO_DIR = SKILL_DIR.parent.parent  # skills/aws-iac-diagram の2つ上
ICONS_DIR = SKILL_DIR / "references" / "icons"
CATALOG = ICONS_DIR / "catalog.json"
BROKEN_JSON = ICONS_DIR / "broken.json"
SIDEBAR = SKILL_DIR / "assets" / "vendor" / "Sidebar-AWS4.js"
DEFAULT_WORK_DIR = REPO_DIR / "aws-iac-diagram-workspace" / "icon-check"

CHECKED_KINDS = ("shape", "resource_icon", "group")
SKIPPED_KINDS = {
    "edge": "矢印のスタイルでステンシルを参照しないため、壊れようがなく判定もできない",
    "plain_group": "AWS ステンシルを使わない枠の矩形で、内側が空なのが正常なため判定できない",
}

# --- 判定の閾値（根拠は docs/dev-notes/WORKLOG.md 2026-10-15 の C2 を参照） ---
WHITE_MIN = 240        # 全チャネルがこれ以上なら背景（白）とみなす
BLACK_MAX = 24         # 全チャネルがこれ以下なら黒とみなす（#1E262E などの濃紺の塗りは黒にしない）
COLOR_TOL = 24         # 最頻色からの L∞ 距離がこれ以下なら同じ色とみなす
INSET_PX = 2           # セルの縁のアンチエイリアスを避けるため内側に縮める画素数
EMPTY_MAX = 0.05       # 非背景率がこれ未満なら空箱（中空の線画があるので内側だけでは判定しない）
BLACK_MIN = 0.90       # 黒の画素率がこれ以上なら黒塗り
SOLID_MIN = 0.97       # 白以外の最頻色の画素率がこれ以上なら単色
STENCIL_DIFF_MAX = 0.002  # 参照（ステンシル無し）との差分画素率がこれ以下ならステンシル欠落
DIFF_TOL = 32          # 差分とみなすチャネル差

THRESHOLDS = {
    "white_min": WHITE_MIN, "black_max": BLACK_MAX, "color_tol": COLOR_TOL,
    "inset_px": INSET_PX, "empty_max": EMPTY_MAX, "black_min": BLACK_MIN, "solid_min": SOLID_MIN,
    "stencil_diff_max": STENCIL_DIFF_MAX, "diff_tol": DIFF_TOL,
}

REASONS = {
    "empty": "空箱: ほぼ何も描かれない",
    "black": "黒塗り: ほぼ全体が黒",
    "solid": "単色: ほぼ全体が白以外の1色（ステンシルが無く塗りの矩形になる）",
    "stencil_missing": "ステンシルが描かれない: 存在しない名前にした参照と同じ画素になる",
}

# --- レイアウト（.drawio 座標） ---
SLOT = 130             # アイコンを置く枠（最大の group が 130x130）
PITCH_X = 150
PITCH_Y = 170          # 下の 30px はラベル用（判定領域には入らない）
MARGIN = 20
COLS = 20              # 偶数（アイコンと参照を同じ行に並べる）
ROWS = 10
MARKER = 8
MARKER_STYLE = "rounded=0;html=1;fillColor=#00FF00;strokeColor=none;"
BG_STYLE = "rounded=0;html=1;fillColor=#FFFFFF;strokeColor=none;"
# overflow=hidden: 長い id がセルからはみ出して図の外接矩形を広げないようにする
LABEL_STYLE = ("text;html=1;align=center;verticalAlign=top;fontSize=8;whiteSpace=wrap;"
               "overflow=hidden;fontColor=#333333;")
NO_ICON = "mxgraph.aws4.c2_no_such_icon"
STENCIL_KEYS = ("resIcon", "grIcon", "shape")  # 差し替える順（resourceIcon と group は shape= を残す）


# ===================== 画像の判定（単体テストの対象） =====================

@dataclass(frozen=True)
class Metrics:
    fg: float        # 領域全体の非背景率
    black: float     # 黒の画素率
    solid: float     # 白以外の最頻色の画素率（白も含めた全画素に対して）

    def as_dict(self) -> dict:
        return {k: round(v, 4) for k, v in self.__dict__.items()}


def _is_white(p) -> bool:
    return p[0] >= WHITE_MIN and p[1] >= WHITE_MIN and p[2] >= WHITE_MIN


def _pixels(img: "Image.Image") -> list[tuple[int, int, int]]:
    b = img.convert("RGB").tobytes()
    return list(zip(b[0::3], b[1::3], b[2::3]))


def measure(img: "Image.Image") -> Metrics:
    """切り出したセル画像（RGB）の指標を求める。"""
    w, h = img.size
    if w <= 0 or h <= 0:
        raise ValueError("空の領域")
    px = _pixels(img)
    n = len(px)
    colored = [p for p in px if not _is_white(p)]
    fg = len(colored) / n
    black = sum(1 for p in px if max(p) <= BLACK_MAX) / n
    solid = 0.0
    if colored:
        # 白以外の画素を上位4ビットで量子化し、最頻ビンの平均色を代表色とする
        bins: dict[tuple, list] = {}
        for p in colored:
            k = (p[0] >> 4, p[1] >> 4, p[2] >> 4)
            b = bins.get(k)
            if b is None:
                bins[k] = [1, p[0], p[1], p[2]]
            else:
                b[0] += 1; b[1] += p[0]; b[2] += p[1]; b[3] += p[2]
        cnt, r, g, bl = max(bins.values())
        rep = (r / cnt, g / cnt, bl / cnt)
        solid = sum(1 for p in colored
                    if max(abs(p[0] - rep[0]), abs(p[1] - rep[1]), abs(p[2] - rep[2])) <= COLOR_TOL) / n
    return Metrics(fg=fg, black=black, solid=solid)


def classify(m: Metrics, diff: float | None = None, diff_only: bool = False) -> str | None:
    """壊れていれば理由コード、正常なら None。diff は参照との差分画素率（無ければ省略）。

    diff_only は group 用: 枠と隅の小さなアイコンだけで中が空なのが正常なので、画素の指標は使わない。
    """
    if diff_only:
        return "stencil_missing" if diff is not None and diff <= STENCIL_DIFF_MAX else None
    if m.fg < EMPTY_MAX:
        return "empty"
    if m.black >= BLACK_MIN:
        return "black"
    if m.solid >= SOLID_MIN:
        return "solid"
    if diff is not None and diff <= STENCIL_DIFF_MAX:
        return "stencil_missing"
    return None


def diff_ratio(a: "Image.Image", b: "Image.Image") -> float:
    """同じ大きさの2画像で、いずれかのチャネル差が DIFF_TOL を超える画素の割合。"""
    if a.size != b.size:
        raise ValueError(f"大きさが違う: {a.size} {b.size}")
    d = sum(1 for p, q in zip(_pixels(a), _pixels(b))
            if max(abs(p[0] - q[0]), abs(p[1] - q[1]), abs(p[2] - q[2])) > DIFF_TOL)
    return d / (a.size[0] * a.size[1])


def find_markers(img: "Image.Image", page_w: float, page_h: float) -> tuple[float, float, float, float]:
    """左上・右下のマーカーの重心から (scale_x, scale_y, offset_x, offset_y) を求める。

    画素 = .drawio 座標 * scale + offset。draw.io は図の外接矩形で切り出し、
    アンチエイリアスで半画素ずれることがあるため、推定せずに実測する。
    PNG の大きさが背景矩形と大きく違う（何かが背景からはみ出した）ときは RuntimeError。
    """
    img = img.convert("RGB")
    W, H = img.size
    if abs(W - page_w) > 4 or abs(H - page_h) > 4:
        raise RuntimeError(f"PNG の大きさ {W}x{H} が背景矩形 {page_w}x{page_h} と合いません"
                           "（背景からはみ出した要素があるか、倍率が 1 ではありません）")

    def centroid(x0, y0, x1, y1):
        sx = sy = sw = 0.0
        for y in range(max(0, y0), min(H, y1)):
            for x in range(max(0, x0), min(W, x1)):
                r, g, b = img.getpixel((x, y))
                wgt = max(0, g - max(r, b))  # 緑っぽさ
                if wgt > 32:
                    sx += wgt * (x + 0.5); sy += wgt * (y + 0.5); sw += wgt
        if sw == 0:
            raise RuntimeError(f"位置合わせのマーカーが見つかりません（領域 {x0},{y0}-{x1},{y1}）")
        return sx / sw, sy / sw

    win = MARKER * 3
    c1 = centroid(0, 0, win, win)
    c2 = centroid(W - win, H - win, W, H)
    span_x, span_y = page_w - MARKER, page_h - MARKER
    sx = (c2[0] - c1[0]) / span_x
    sy = (c2[1] - c1[1]) / span_y
    ox = c1[0] - (MARKER / 2) * sx
    oy = c1[1] - (MARKER / 2) * sy
    return sx, sy, ox, oy


def crop_box(x: float, y: float, w: float, h: float, tr: tuple[float, float, float, float],
             inset: int = INSET_PX) -> tuple[int, int, int, int]:
    sx, sy, ox, oy = tr
    left = math.ceil(x * sx + ox) + inset
    top = math.ceil(y * sy + oy) + inset
    right = math.floor((x + w) * sx + ox) - inset
    bottom = math.floor((y + h) * sy + oy) - inset
    return left, top, max(left + 1, right), max(top + 1, bottom)


# ===================== .drawio の生成 =====================

@dataclass
class Item:
    key: str          # catalog の id、対照の "ctl:..."、参照の "ref:..."
    style: str
    w: int
    h: int
    expect: str | None = None   # 対照で期待する判定（"ok" は正常）
    ref_of: str | None = None   # 参照なら、その元の key


def without_stencil(style: str) -> str:
    """ステンシル名（resIcon / grIcon、無ければ shape）だけを存在しない名前にしたスタイル。"""
    for key in STENCIL_KEYS:
        pat = rf"(^|;){key}=mxgraph\.aws4\.[^;]*"
        if re.search(pat, style):
            return re.sub(pat, rf"\g<1>{key}={NO_ICON}", style, count=1)
    raise ValueError(f"ステンシル名が見つかりません: {style[:80]}")


def is_group(style: str) -> bool:
    return re.search(r"(^|;)grIcon=", style) is not None


def controls(catalog: list[dict]) -> list[Item]:
    """壊れ方が分かっている対照と正常な対照。辞書から機械的に作る。

    壊れの対照は参照（NO_ICON）とは別の存在しない名前を使い、「存在しない名前なら同じ画素になる」
    ことも確かめる（参照と同じスタイルにするとトートロジーになる）。
    """
    shape = next(c for c in catalog if c["kind"] == "shape" and c["width"] == 78 and c["height"] == 78)
    res = next(c for c in catalog if c["kind"] == "resource_icon" and "gradientColor=none" in c["style"])
    grad = next(c for c in catalog if c["kind"] == "resource_icon"
                and re.search(r"gradientColor=#", c["style"]))
    grp = next(c for c in catalog if c["kind"] == "group")
    s, r, rg, g = shape["style"], res["style"], grad["style"], grp["style"]

    def rename(style: str, key: str, new: str) -> str:
        return re.sub(rf"(^|;){key}=mxgraph\.aws4\.[^;]*", rf"\g<1>{key}=mxgraph.aws4.{new}", style, count=1)

    return [
        # vidanov の知見: dynamodb_table は draw.io に無く、壊れる
        Item("ctl:unknown_shape_dynamodb_table", rename(s, "shape", "dynamodb_table"), 78, 78, "solid"),
        Item("ctl:unknown_resicon", rename(r, "resIcon", "dynamodb_table"), 78, 78, "solid"),
        # グラデーション付きの resourceIcon は、resIcon が無くてもグラデーションの正方形になり単色にならない
        Item("ctl:unknown_resicon_gradient", rename(rg, "resIcon", "dynamodb_table"), 78, 78, "stencil_missing"),
        Item("ctl:no_fillcolor_shape", re.sub(r"fillColor=[^;]*;", "", s), 78, 78, "empty"),  # PLAN 2.2 の 3
        Item("ctl:black_unknown_shape",
             re.sub(r"fillColor=[^;]*;", "fillColor=#000000;", rename(s, "shape", "dynamodb_table")), 78, 78, "black"),
        Item("ctl:unknown_gricon", rename(g, "grIcon", "group_dynamodb_table"), grp["width"], grp["height"],
             "stencil_missing"),
        Item("ctl:ok_shape", s, shape["width"], shape["height"], "ok"),
        Item("ctl:ok_resicon_gradient", rg, 78, 78, "ok"),
        Item("ctl:ok_group", g, grp["width"], grp["height"], "ok"),
    ]


def build_items(catalog: list[dict]) -> tuple[list[Item], list[dict]]:
    """描画する Item（各アイコンの直後にその参照）と、描画しない辞書エントリを返す。"""
    targets: list[Item] = []
    skipped = []
    for c in catalog:
        if c["kind"] not in CHECKED_KINDS:
            skipped.append(c)
            continue
        targets.append(Item(c["id"], c["style"], c["width"], c["height"]))
    targets += controls(catalog)
    items: list[Item] = []
    for it in targets:
        items.append(it)
        items.append(Item(f"ref:{it.key}", without_stencil(it.style), it.w, it.h, ref_of=it.key))
    return items, skipped


def page_size(n_items: int) -> tuple[int, int]:
    cols = min(COLS, n_items)
    rows = math.ceil(n_items / COLS)
    return MARGIN * 2 + cols * PITCH_X, MARGIN * 2 + rows * PITCH_Y


def place(idx: int, it: Item) -> tuple[int, int]:
    """ページ内で idx 番目の item の左上座標（スロットの中央に置く）。"""
    col, row = idx % COLS, idx // COLS
    sx = MARGIN + col * PITCH_X + (PITCH_X - SLOT) // 2
    sy = MARGIN + row * PITCH_Y
    return sx + (SLOT - it.w) // 2, sy + (SLOT - it.h) // 2


def cell(cid: str, style: str, x: float, y: float, w: float, h: float, value: str = "") -> str:
    return (f'<mxCell id={quoteattr(cid)} value={quoteattr(value)} style={quoteattr(style)} vertex="1" parent="1">'
            f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>')


def render_drawio(pages: list[list[Item]]) -> str:
    out = ["<mxfile>"]
    for p, items in enumerate(pages, 1):
        W, H = page_size(len(items))
        cells = ['<mxCell id="0"/>', '<mxCell id="1" parent="0"/>',
                 # 背景矩形を最背面に置く（PLAN 2.2 の 11）。図の外接矩形をこの矩形に固定する役目もある
                 cell("bg", BG_STYLE, 0, 0, W, H),
                 cell("m1", MARKER_STYLE, 0, 0, MARKER, MARKER),
                 cell("m2", MARKER_STYLE, W - MARKER, H - MARKER, MARKER, MARKER)]
        for i, it in enumerate(items):
            x, y = place(i, it)
            cells.append(cell(f"i{i}", it.style, x, y, it.w, it.h))
            col, row = i % COLS, i // COLS
            cells.append(cell(f"l{i}", LABEL_STYLE, MARGIN + col * PITCH_X, MARGIN + row * PITCH_Y + SLOT + 2,
                              PITCH_X, PITCH_Y - SLOT - 4, value=it.key))
        out.append(f'<diagram id="page{p}" name="page{p}"><mxGraphModel><root>')
        out += cells
        out.append("</root></mxGraphModel></diagram>")
    out.append("</mxfile>")
    return "\n".join(out) + "\n"


def paginate(items: list[Item]) -> list[list[Item]]:
    """1ページ COLS*ROWS 個まで。アイコンとその参照（ref:）は比べるので同じページに置く。"""
    per = COLS * ROWS
    units: list[list[Item]] = []
    for it in items:
        if it.ref_of is not None and units and units[-1][0].key == it.ref_of:
            units[-1].append(it)
        else:
            units.append([it])
    pages: list[list[Item]] = [[]]
    for u in units:
        if len(pages[-1]) + len(u) > per:
            pages.append([])
        pages[-1] += u
    return pages


# ===================== 実行 =====================

def analyze(pages: list[list[Item]], pngs: list[Path]) -> dict[str, dict]:
    results: dict[str, dict] = {}
    for page_no, (items, png) in enumerate(zip(pages, pngs), 1):
        img = Image.open(png).convert("RGB")
        W, H = page_size(len(items))
        tr = find_markers(img, W, H)
        crops = {}
        for i, it in enumerate(items):
            x, y = place(i, it)
            crops[it.key] = img.crop(crop_box(x, y, it.w, it.h, tr))
        for it in items:
            if it.ref_of is not None:
                continue
            m = measure(crops[it.key])
            d = diff_ratio(crops[it.key], crops[f"ref:{it.key}"])
            results[it.key] = {"reason": classify(m, d, diff_only=is_group(it.style)), "metrics": {**m.as_dict(), "diff": round(d, 4)},
                               "expect": it.expect, "page": page_no}
    return results


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest().upper()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--work-dir", type=Path, default=DEFAULT_WORK_DIR,
                    help=".drawio・PNG・report.json の置き場所（既定: aws-iac-diagram-workspace/icon-check）")
    ap.add_argument("--no-write", action="store_true", help="broken.json と辞書を更新しない")
    ap.add_argument("--timeout", type=int, default=600, help="1ページの書き出しの制限秒数")
    args = ap.parse_args()

    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    items, skipped = build_items(catalog)
    pages = paginate(items)
    work: Path = args.work_dir
    work.mkdir(parents=True, exist_ok=True)
    for old in work.glob("page*.png"):
        old.unlink()
    src = work / "icon_check.drawio"
    src.write_text(render_drawio(pages), encoding="utf-8", newline="\n")

    try:
        exe = find_drawio()
        ver = drawio_version(exe)
        pngs = []
        for p in range(1, len(pages) + 1):
            dst = work / f"page{p}.png"
            print(f"書き出し中: page {p}/{len(pages)}", file=sys.stderr)
            pngs.append(export_png(src, dst, page_index=p, timeout=args.timeout, exe=exe))
        results = analyze(pages, pngs)
    except (DrawioError, RuntimeError) as e:
        print(f"失敗: {e}", file=sys.stderr)
        return 2

    # 自己検査: 対照が期待どおりに判定されること
    bad_controls = []
    for key, r in sorted(results.items()):
        if r["expect"] is not None:
            got = r["reason"] or "ok"
            if got != r["expect"]:
                bad_controls.append(f"{key}: 期待 {r['expect']}、判定 {got} {r['metrics']}")

    checked = {c["id"] for c in catalog if c["kind"] in CHECKED_KINDS}
    broken = [
        {"id": k, "reason": r["reason"], "detail": REASONS[r["reason"]]}
        for k, r in sorted(results.items()) if k in checked and r["reason"]
    ]
    report = {"drawio_version": ver, "results": {k: results[k] for k in sorted(results)}}
    (work / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                                      encoding="utf-8", newline="\n")

    n_ctl = sum(1 for r in results.values() if r["expect"] is not None)
    print(f"draw.io {ver}: {len(checked)} 件を判定、壊れたもの {len(broken)} 件"
          f"（描画対象外 {len(skipped)} 件: " + ", ".join(sorted({c['kind'] for c in skipped})) + "）"
          f"、対照 {n_ctl} 件")
    for b in broken:
        print(f"  {b['id']}\t{b['reason']}")
    if bad_controls:
        print("自己検査に失敗しました（閾値か描画の前提が崩れています）。辞書は更新しません:", file=sys.stderr)
        for s in bad_controls:
            print("  " + s, file=sys.stderr)
        return 3

    if args.no_write:
        return 0
    doc = {
        "comment": "生成物: scripts/check_icons.py が出力する。手で編集しない。build_icon_catalog.py がこれを辞書にマージする",
        "drawio_version": ver,
        "sidebar_sha256": sha256(SIDEBAR),
        "checked": len(checked),
        "skipped_kinds": {k: SKIPPED_KINDS[k] for k in sorted({c["kind"] for c in skipped})},
        "thresholds": THRESHOLDS,
        "broken": broken,
    }
    BROKEN_JSON.write_text(json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                           encoding="utf-8", newline="\n")
    import build_icon_catalog as bic
    bic.write_outputs(bic.strip_broken(catalog), broken_path=BROKEN_JSON)
    print(f"更新: {BROKEN_JSON.relative_to(REPO_DIR).as_posix()}、catalog.json、カテゴリ別 .md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
