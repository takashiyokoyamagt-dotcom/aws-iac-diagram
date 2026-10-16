"""check_icons.py の判定ロジックの単体テスト（合成画像を使う。draw.io は不要）。

実行: uv run python -m unittest discover -s tests -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills" / "aws-iac-diagram" / "scripts"))

from PIL import Image, ImageDraw  # noqa: E402

import check_icons as ci  # noqa: E402

WHITE = (255, 255, 255)
PURPLE = (140, 79, 255)
NAVY = (30, 38, 46)


def blank(size=74, color=WHITE):
    return Image.new("RGB", (size, size), color)


def resource_icon():
    """resourceIcon 風: 色の正方形に白い線のグリフ。"""
    img = blank(color=PURPLE)
    d = ImageDraw.Draw(img)
    d.ellipse((15, 15, 58, 58), outline=WHITE, width=4)
    d.line((20, 37, 54, 37), fill=WHITE, width=4)
    return img


def gradient_square():
    """gradientColor 付きの resourceIcon でステンシルが無いときの見た目（上下のグラデーション）。"""
    img = blank()
    for y in range(74):
        t = y / 73
        c = (int(77 + (179 - 77) * t), int(39 + (93 - 39) * t), int(206 + (255 - 206) * t))
        for x in range(74):
            img.putpixel((x, y), c)
    return img


def outline_shape():
    """中が中空の線画アイコン（shape:object の丸のようなもの）。誤検出しないこと。"""
    img = blank()
    ImageDraw.Draw(img).ellipse((5, 5, 68, 68), outline=(122, 161, 22), width=3)
    return img


class ClassifyTest(unittest.TestCase):
    def judge(self, img):
        return ci.classify(ci.measure(img))

    def test_empty(self):
        self.assertEqual(self.judge(blank()), "empty")

    def test_empty_with_antialias_noise(self):
        img = blank()
        img.putpixel((0, 0), (200, 200, 200))  # 縁の数画素は空箱の判定を崩さない
        self.assertEqual(self.judge(img), "empty")

    def test_black(self):
        self.assertEqual(self.judge(blank(color=(0, 0, 0))), "black")

    def test_solid(self):
        self.assertEqual(self.judge(blank(color=PURPLE)), "solid")

    def test_dark_navy_solid_is_solid_not_black(self):
        self.assertEqual(self.judge(blank(color=NAVY)), "solid")

    def test_solid_with_slight_gradient(self):
        img = blank(color=PURPLE)
        for x in range(74):
            for y in range(74):
                img.putpixel((x, y), (140 + x % 8, 79, 255 - y % 8))
        self.assertEqual(self.judge(img), "solid")

    def test_normal_resource_icon(self):
        self.assertIsNone(self.judge(resource_icon()))

    def test_normal_outline_shape(self):
        self.assertIsNone(self.judge(outline_shape()))

    def test_normal_dark_icon_with_white_glyph(self):
        img = blank(color=NAVY)
        ImageDraw.Draw(img).rectangle((15, 15, 58, 58), outline=WHITE, width=5)
        self.assertIsNone(self.judge(img))

    def test_nearly_white_is_empty_not_solid(self):
        """白がほぼ全体を占めるのは単色ではなく空箱（白は最頻色に数えない）。"""
        img = blank()
        ImageDraw.Draw(img).rectangle((0, 0, 73, 1), fill=PURPLE)  # 非背景率 約 0.027
        self.assertEqual(self.judge(img), "empty")

    def test_gradient_square_is_not_solid(self):
        """グラデーションの正方形は単色の判定では拾えない（参照との差分で拾う）。"""
        img = gradient_square()
        self.assertIsNone(self.judge(img))
        self.assertEqual(ci.classify(ci.measure(img), ci.diff_ratio(img, gradient_square())), "stencil_missing")

    def test_icon_differs_from_reference_is_ok(self):
        icon = gradient_square()
        ImageDraw.Draw(icon).ellipse((15, 15, 58, 58), outline=WHITE, width=4)
        self.assertIsNone(ci.classify(ci.measure(icon), ci.diff_ratio(icon, gradient_square())))


class StencilTest(unittest.TestCase):
    def test_without_stencil_replaces_resicon_not_shape(self):
        st = "a=1;shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.lambda;"
        self.assertEqual(ci.without_stencil(st), f"a=1;shape=mxgraph.aws4.resourceIcon;resIcon={ci.NO_ICON};")

    def test_without_stencil_group(self):
        st = "shape=mxgraph.aws4.group;grIcon=mxgraph.aws4.group_vpc2;"
        self.assertEqual(ci.without_stencil(st), f"shape=mxgraph.aws4.group;grIcon={ci.NO_ICON};")

    def test_without_stencil_shape(self):
        st = "fillColor=#ED7100;shape=mxgraph.aws4.lambda_function;"
        self.assertEqual(ci.without_stencil(st), f"fillColor=#ED7100;shape={ci.NO_ICON};")

    def test_every_item_has_reference(self):
        cat = [
            {"id": "shape:a", "kind": "shape", "width": 78, "height": 78,
             "style": "fillColor=#ED7100;strokeColor=none;shape=mxgraph.aws4.a;"},
            {"id": "resource_icon:b", "kind": "resource_icon", "width": 78, "height": 78,
             "style": "gradientColor=none;fillColor=#ED7100;shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.b;"},
            {"id": "resource_icon:c", "kind": "resource_icon", "width": 78, "height": 78,
             "style": "gradientColor=#F78E04;fillColor=#D05C17;shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.c;"},
            {"id": "group:d", "kind": "group", "width": 130, "height": 130,
             "style": "shape=mxgraph.aws4.group;grIcon=mxgraph.aws4.d;"},
            {"id": "edge:e", "kind": "edge", "width": 100, "height": 0, "style": "edgeStyle=orthogonalEdgeStyle;"},
        ]
        items, skipped = ci.build_items(cat)
        self.assertEqual([c["id"] for c in skipped], ["edge:e"])
        for it, ref in zip(items[0::2], items[1::2]):
            self.assertEqual(ref.ref_of, it.key)
            self.assertIn(ci.NO_ICON, ref.style)
            self.assertNotIn(ci.NO_ICON, it.style)  # 対照は参照と別の名前（トートロジーにしない）
        expects = {it.key: it.expect for it in items if it.expect}
        self.assertEqual(expects["ctl:unknown_resicon_gradient"], "stencil_missing")
        self.assertEqual(expects["ctl:ok_group"], "ok")


class GroupDiffTest(unittest.TestCase):
    def frame(self, with_icon):
        img = blank(130)
        d = ImageDraw.Draw(img)
        d.rectangle((0, 0, 129, 129), outline=(35, 47, 62))
        if with_icon:
            d.rectangle((0, 0, 24, 24), fill=(35, 47, 62))
        return img

    def test_missing_icon_equals_reference(self):
        self.assertLessEqual(ci.diff_ratio(self.frame(False), self.frame(False)), ci.STENCIL_DIFF_MAX)

    def test_icon_differs_from_reference(self):
        self.assertGreater(ci.diff_ratio(self.frame(True), self.frame(False)), ci.STENCIL_DIFF_MAX)


class GeometryTest(unittest.TestCase):
    def page(self, w, h, ox, oy):
        """draw.io の出力を模す: (ox, oy) だけずれた位置にマーカーを描く。"""
        img = Image.new("RGB", (w + 2, h + 2), WHITE)
        d = ImageDraw.Draw(img)
        m = ci.MARKER
        d.rectangle((ox, oy, ox + m - 1, oy + m - 1), fill=(0, 255, 0))
        d.rectangle((ox + w - m, oy + h - m, ox + w - 1, oy + h - 1), fill=(0, 255, 0))
        return img

    def test_markers_give_scale_and_offset(self):
        sx, sy, ox, oy = ci.find_markers(self.page(400, 300, 1, 1), 400, 300)
        self.assertAlmostEqual(sx, 1.0, places=3)
        self.assertAlmostEqual(sy, 1.0, places=3)
        self.assertAlmostEqual(ox, 1.0, places=3)
        self.assertAlmostEqual(oy, 1.0, places=3)

    def test_size_mismatch_raises(self):
        with self.assertRaises(RuntimeError):
            ci.find_markers(self.page(400, 300, 1, 1), 300, 300)

    def test_missing_marker_raises(self):
        with self.assertRaises(RuntimeError):
            ci.find_markers(Image.new("RGB", (100, 100), WHITE), 100, 100)

    def test_crop_box_insets(self):
        self.assertEqual(ci.crop_box(10, 20, 48, 48, (1.0, 1.0, 0.5, 0.5), inset=2), (13, 23, 56, 66))


class LayoutTest(unittest.TestCase):
    def test_icon_and_reference_share_a_page(self):
        items = [ci.Item(f"shape:{i}", "", 48, 48) for i in range(ci.COLS * ci.ROWS - 1)]
        items += [ci.Item("group:g", "", 130, 130), ci.Item("ref:group:g", "", 130, 130, ref_of="group:g")]
        pages = ci.paginate(items)
        self.assertEqual(len(pages), 2)
        self.assertEqual([x.key for x in pages[1]], ["group:g", "ref:group:g"])

    def test_render_is_deterministic(self):
        items = [ci.Item("shape:a", "shape=mxgraph.aws4.a;fillColor=#000000;", 48, 48)]
        self.assertEqual(ci.render_drawio([items]), ci.render_drawio([items]))
        self.assertIn('id="bg"', ci.render_drawio([items]).split('id="i0"')[0])  # 背景が最背面


if __name__ == "__main__":
    unittest.main()
