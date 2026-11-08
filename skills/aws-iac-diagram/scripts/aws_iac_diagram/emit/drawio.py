"""配置の結果と normalized IR から `.drawio` の XML を作る（設計案 phase4-design-draft の 6 章）。

レイヤは背景・図形（id=1）・辺の 3 つで、この順に描かれる。辺の親は常に辺のレイヤ。waypoint は置かない（経路は draw.io が決める）。
同じ入力からバイト単位で同じ文字列を返す（C5）。
"""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET

from aws_iac_diagram.core import paths, rules
from aws_iac_diagram.layout.grid import PAD, Layout

BACKGROUND_LAYER = "layer-background"
EDGE_LAYER = "layer-edges"
MARGIN = 40
LEGEND_ID = "legend"
LEGEND_H = 24
REVERSE_LABEL_OFFSET = 16  # 往復の辺のラベルが重ならないよう、辺から離す量（向きが逆なので、それぞれ反対の側に出る）
LEGEND_TEXT = "凡例: 破線 = 推定の関係"

_FALLBACK_ICON = "shape:internet"
_AZ_STYLE = "rounded=0;dashed=1;fillColor=none;strokeColor=#147EBA;fontColor=#147EBA;verticalAlign=top;align=left;spacingLeft=8;html=1;container=1;"
_EDGE_STYLE = "edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;endArrow=block;endFill=1;strokeColor=#545B64;fontSize=12;"
_LEGEND_STYLE = "text;html=1;align=left;verticalAlign=middle;strokeColor=none;fillColor=none;fontSize=12;"
_BACKGROUND_STYLE = "rounded=0;fillColor=#FFFFFF;strokeColor=none;"


def load_catalog() -> dict[str, dict]:
    return {e["id"]: e for e in json.loads(paths.ICON_CATALOG.read_text(encoding="utf-8"))}


def node_style(node: dict, r: rules.Rules, catalog: dict[str, dict]) -> str:
    """規則表の `icon` の候補から、辞書にあり壊れていない最初のものの style を返す。"""
    if node["type"] == "availability_zone":
        return _AZ_STYLE
    icons = list(r.row(node["type"]).get("icon") or ())
    if node["type"] == "subnet":  # 候補は public、private の順
        icons = [icons[0 if (node.get("attrs") or {}).get("access") == "public" else -1]]
    for icon in [*icons, _FALLBACK_ICON]:
        entry = catalog.get(icon)
        if entry is not None and not entry["broken"]:
            style = entry["style"]
            return style if node["category"] != "group" or "container=" in style else style + "container=1;"
    raise KeyError(f"描けるアイコンが無い: {node['type']}")


def _cell(root: ET.Element, attrs: dict[str, str], geometry: dict[str, str] | None = None) -> None:
    cell = ET.SubElement(root, "mxCell", attrs)
    if geometry is not None:
        ET.SubElement(cell, "mxGeometry", {**geometry, "as": "geometry"})


def emit(ir: dict, layout: Layout, r: rules.Rules, catalog: dict[str, dict]) -> str:
    has_inferred = any(e["confidence"] == "inferred" for e in ir["edges"])
    legend_extra = LEGEND_H + PAD if has_inferred else 0
    width, height = layout.width + 2 * MARGIN, layout.height + 2 * MARGIN + legend_extra

    mxfile = ET.Element("mxfile", {"host": "aws-iac-diagram"})
    diagram = ET.SubElement(mxfile, "diagram", {"id": ir["name"], "name": ir["name"]})
    model = ET.SubElement(diagram, "mxGraphModel", {"dx": "0", "dy": "0", "grid": "0", "page": "0"})
    root = ET.SubElement(model, "root")
    _cell(root, {"id": "0"})
    _cell(root, {"id": BACKGROUND_LAYER, "parent": "0", "value": "background"})
    _cell(root, {"id": "1", "parent": "0", "value": "shapes"})
    _cell(root, {"id": EDGE_LAYER, "parent": "0", "value": "edges"})
    _cell(root, {"id": "background", "value": "", "style": _BACKGROUND_STYLE, "vertex": "1", "parent": BACKGROUND_LAYER},
          {"x": "0", "y": "0", "width": str(width), "height": str(height)})

    by_id = {n["id"]: n for n in ir["nodes"]}
    # 親の枠を子より先に書く（draw.io は親が先にあることを前提にする）
    depth = {}
    def depth_of(i: str) -> int:
        if i not in depth:
            p = layout.placed[i].parent
            depth[i] = 0 if p is None else depth_of(p) + 1
        return depth[i]
    for nid in sorted(layout.placed, key=lambda i: (depth_of(i), i)):
        p = layout.placed[nid]
        ox, oy = (MARGIN, MARGIN) if p.parent is None else (0, 0)
        _cell(root, {"id": nid, "value": by_id[nid]["label"], "style": node_style(by_id[nid], r, catalog), "vertex": "1",
                     "parent": p.parent if p.parent is not None else "1"},
              {"x": str(p.x + ox), "y": str(p.y + oy), "width": str(p.w), "height": str(p.h)})
    if has_inferred:
        _cell(root, {"id": LEGEND_ID, "value": LEGEND_TEXT, "style": _LEGEND_STYLE, "vertex": "1", "parent": "1"},
              {"x": str(MARGIN), "y": str(layout.height + MARGIN + PAD), "width": "240", "height": str(LEGEND_H)})
    pairs = {(e["from"], e["to"]) for e in ir["edges"] if e.get("label")}
    for e in sorted(ir["edges"], key=lambda x: x["id"]):
        if e["from"] not in layout.placed or e["to"] not in layout.placed:
            continue
        style = _EDGE_STYLE + ("dashed=1;" if e["confidence"] == "inferred" else "")
        _cell(root, {"id": e["id"], "value": e.get("label") or "", "style": style, "edge": "1", "parent": EDGE_LAYER,
                     "source": e["from"], "target": e["to"]},
              {"relative": "1", "y": str(REVERSE_LABEL_OFFSET)} if e.get("label") and (e["to"], e["from"]) in pairs else {"relative": "1"})
    ET.indent(mxfile, space="  ")
    return ET.tostring(mxfile, encoding="unicode") + "\n"
