# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""規則表（`skills/aws-iac-diagram/data/rules/`）から、`docs/spec/rules/` の表を作る（フェーズ 3 の手順 1。PLAN の 1.4 の 2）。

規則表の説明の文章（なぜそうするか）は `docs/spec/rules/*.md` に手で書き、その中の表は、データ（TOML）から作った生成物にする。
表を 2 か所に手で持つと食い違うので、生成した表の位置に次のマーカーを置き、中身は直接直さない:

  <!-- rules-table: <名前> -->
  （ここが生成される）
  <!-- /rules-table -->

`--check`（既定）は、いまの文書の生成部分がデータから作った内容と同じかを調べる（食い違い・マーカーの欠け・余りは 1。
単体テスト `tests/architecture/test_rules_docs.py` も同じ関数を呼ぶ）。`--write` は生成部分を書き直す。
列の説明の表（`fields-*`）は、`core/rules.py` の列の定義から作る（読み込みの検査と説明が食い違わない。説明の文は COLUMN_DOC）。

使い方（リポジトリのルートで）:
  uv run python aws-iac-diagram-workspace/tools/render_rules.py            # --check と同じ
  uv run python aws-iac-diagram-workspace/tools/render_rules.py --check
  uv run python aws-iac-diagram-workspace/tools/render_rules.py --write
  （--rules-dir <data/rules のフォルダ> --docs-dir <docs/spec/rules のフォルダ> で場所を変えられる）

終了コード: 0 = 一致（--write は書き直した）、1 = 食い違い、2 = 規則表が読めない・文書が無い・使い方の誤り
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

WS = Path(__file__).resolve().parent.parent
ROOT = WS.parent
SCRIPTS = ROOT / "skills" / "aws-iac-diagram" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from aws_iac_diagram.core import rules as rule_data  # noqa: E402

DOCS_DIR = ROOT / "docs" / "spec" / "rules"
BEGIN = re.compile(r"^<!-- rules-table: ([a-z0-9-]+) -->$")
END = "<!-- /rules-table -->"
GENERATED_NOTE = "<!-- 生成: aws-iac-diagram-workspace/tools/render_rules.py（直接直さない。直すのはデータ data/rules/ の TOML） -->"


# ------------------------------------------------------------------ 部品

def bt(x) -> str:
    return f"`{x}`"


def btl(xs, sep: str = "、") -> str:
    return sep.join(bt(x) for x in xs)


def cell(x) -> str:
    return " ".join(str(x).split()).replace("|", "\\|")


def table(header: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    out += ["| " + " | ".join(cell(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def when_text(when) -> str:
    if not when:
        return ""
    parts = []
    if "types" in when:
        parts.append("対象の型: " + btl(when["types"]))
    if "prop" in when:
        p = when["prop"]
        names = "／".join(bt(p[k]) for k in ("tf", "cfn") if k in p)
        t = f"{names} が " + btl(when["in"], "・") + " のとき"
        if "default" in when:
            t += f"（省略時は {bt(when['default'])}）"
        parts.append(t)
    if "via" in when:
        parts.append("raw の via が " + btl(when["via"], "・") + " のとき")
    if "via_not" in when:
        parts.append("raw の via が " + btl(when["via_not"], "・") + " でないとき")
    return "条件: " + "。".join(parts)


def note(s) -> str:
    return f"（{s}）" if s else ""


def join(*parts) -> str:
    return " ".join(p for p in parts if p)


# ------------------------------------------------------------------ 表

def t_drawn(r: rule_data.Rules) -> str:
    rows = []
    for x in r.drawn:
        na = x.name_attr
        name = " ／ ".join(bt(na[k]) for k in ("tf", "cfn") if k in na) if na else "（タグのみ）"
        if x.get("name_from"):
            name = x.name_from
        tf = join(btl(x.tf), note(x.get("tf_note", "")) if x.tf else x.get("tf_note", ""))
        cfn = join(btl(x.cfn), note(x.get("cfn_note", "")) if x.cfn else x.get("cfn_note", ""))
        if x.get("synthetic"):
            tf = cfn = f"（合成: {x.synthetic}）"
        if x.get("when"):
            tf = join(tf, f"［{when_text(x.when)}］")
        icon = join("／".join(bt(i) for i in x.icon), note(x.get("icon_note", "")))
        rows.append([bt(x.id), x.file.split("/")[-1].removesuffix(".toml"), x.category, tf, cfn, name, icon, "○" if x.get("data") else ""])
    return table(["正規の型名", "ファイル", "category", "Terraform", "CloudFormation／SAM", "名前属性（B3 の2番目）", "アイコン候補（`find_aws_icon.py --id`）",
                  "既存の `data` も描く"], rows)


def t_merged(r: rule_data.Rules) -> str:
    rows = []
    for x in r.merged:
        tf = join(btl(x.tf), note(x.get("tf_note", "")) if x.tf else x.get("tf_note", ""))
        cfn = join(btl(x.cfn), note(x.get("cfn_note", "")) if x.cfn else x.get("cfn_note", ""))
        into = join(x.into["select"], "→", btl(x.into["node_types"], "・"), "（中の参照は統合先の参照）" if x.get("refs_as_target") else "")
        rows.append([bt(x.id), tf, cfn, into, x.reason])
    return table(["規則ID", "Terraform", "CloudFormation", "統合先（原文 → ノードの型）", "理由"], rows)


def t_hidden(r: rule_data.Rules) -> str:
    rows = []
    for x in r.hidden:
        m = []
        if x.tf:
            m.append("TF: " + btl(x.tf))
        if x.cfn:
            m.append("CFN: " + btl(x.cfn))
        if x.get("tf_data"):
            m.append("TF の data: " + btl(x.tf_data))
        if x.get("data_block"):
            m.append("ほかの行に当たらない TF の data ブロックすべて")
        if x.get("when"):
            m.append(when_text(x.when))
        if x.get("evidence_source"):
            m.append("E-IAM の材料にしてから非表示（モジュールは " + bt(x.module_sources_file) + " の source の前方一致）")
        rows.append([bt(x.id), x.applies, "；".join(m) if m else "（型では決まらない。辺・条件のあとで決まる）", x.reason])
    return table(["規則ID", "対象（原文）", "機械が読む型・条件", "理由・補足"], rows)


def t_relations(r: rule_data.Rules) -> str:
    rows = []
    for x in r.relations:
        def side(types, props, note):
            parts = [btl(types)] if types else []
            if props:
                parts.append("プロパティ: " + btl(props))
            return join("、".join(parts), f"（{note}）" if note else "")
        tf = side(x.tf, x.get("tf_props", ()), x.get("tf_note", ""))
        cfn = side(x.cfn, x.get("cfn_props", ()), x.get("cfn_note", ""))
        if x.get("sam"):
            cfn = join(cfn, "SAM の Events の Type: " + btl(x.sam))
        if x.get("when"):
            tf = join(tf, f"［{when_text(x.when)}］")
        kind = join(bt(x.kind) if x.kind else "", x.get("kind_note", ""))
        extra = join("確信度 " + bt(x.confidence), ("辺ができなければ " + bt(x.fallback)) if x.get("fallback") else "")
        rows.append([bt(x.id), tf, cfn, x.edge, kind, x.label, extra])
    return table(["規則ID", "Terraform", "CloudFormation／SAM", "辺（from → to）", "kind", "ラベル", "確信度・辺ができなかったとき"], rows)


def t_confidence(r: rule_data.Rules) -> str:
    return table(["確信度", "根拠", "規則", "描き方（フェーズ4 以降）"],
                 [[bt(x.level), x.basis, btl(x.rules), x.draw] for x in r.confidences])


def t_edge_rules(r: rule_data.Rules) -> str:
    rows = []
    for x in r.edges:
        kind = join(bt(x.kind) if x.kind else "", x.get("kind_note", ""))
        conf = bt(x.confidence) if x.confidence else x.get("confidence_note", "")
        rows.append([bt(x.id), x.input, x.edge, kind, conf])
    return table(["規則ID", "入力", "辺（from → to）", "kind", "確信度"], rows)


def t_kind_by_target(r: rule_data.Rules) -> str:
    return table(["参照先の型", "kind"], [[btl(x.types), bt(x.kind)] for x in r.kind_by_target])


def t_iam_action_kind(r: rule_data.Rules) -> str:
    rows = [[x.get("actions_note") or btl(x.actions), bt(x.kind)] for x in r.iam_action_kinds]
    if r.edges_options.get("iam_action_default") == "none":
        rows.append(["それ以外", "辺を作らない（v0.1）"])
    return table(["アクション", "kind"], rows)


def t_merge_priority(r: rule_data.Rules) -> str:
    return table(["優先順（上ほど強い）", "規則"], [[x.rank, btl(x.rules, "、")] for x in r.merge_priority])


def t_synthetic(r: rule_data.Rules) -> str:
    return table(["規則ID", "いつ作るか", "ノード", "辺"], [[bt(x.id), x.trigger, x.node, x.edges] for x in r.synthetic])


def t_label_format(r: rule_data.Rules) -> str:
    return table(["種類", "書式", "例"], [[x.subject, x.format, x.example] for x in r.label_formats])


def t_noedge(r: rule_data.Rules) -> str:
    rows = []
    for x in r.noedge:
        keys = btl(x.attrs) if x.attrs else ("参照する側が " + btl(x.from_class, "・") + " の規則（" + btl(x.except_rules) + " は除く）" if "from_class" in x.fields else "")
        rows.append([bt(x.id), x.match, keys, x.use_text])
    return table(["規則ID", "当たる参照（原文）", "機械が読む属性名（中立キー）", "代わりに使うところ"], rows)


def t_nonode(r: rule_data.Rules) -> str:
    return table(["規則ID", "参照先", "扱い"], [[bt(x.id), x.target, x.handling] for x in r.nonode])


def t_placement(r: rule_data.Rules) -> str:
    return table(["規則ID", "内容", "対象の型"], [[bt(x.id), x.content, btl(x.types)] for x in r.placement])


def t_attrs(r: rule_data.Rules) -> str:
    return table(["型", "attrs のキー", "値", "決め方", "材料にする規則"],
                 [[bt(x.type), bt("attrs." + x.name), btl(x.values, "・"), x.rule, bt(x.source)] for x in r.attrs])


def t_layout(r: rule_data.Rules) -> str:
    def ids(rows):
        return len(rows)
    rows = [
        [f"`types/*.toml`（{len({x.file for x in r.types})} ファイル。名前の昇順）", "`[[type]]`", f"描く型 {ids(r.drawn)}、統合 M-* {ids(r.merged)}、非表示 H-* {ids(r.hidden)}"],
        ["`relations.toml`", "`[[relation]]`", f"R-* {ids(r.relations)}"],
        ["`edges.toml`", "`[[confidence]]` `[[edge]]` `[[kind_by_target]]` `[[iam_action_kind]]` `[[merge_priority]]` `[[synthetic]]` `[[label_format]]`",
         f"確信度 {ids(r.confidences)}、辺の規則 E-* {ids(r.edges)}、kind の対応 {ids(r.kind_by_target)}、IAM のアクション {ids(r.iam_action_kinds)}、"
         f"優先順 {ids(r.merge_priority)}、合成ノード N-* {ids(r.synthetic)}、ラベルの書式 {ids(r.label_formats)}"],
        ["`refs.toml`", "`[[noedge]]` `[[nonode]]`", f"E-NOEDGE-* {ids(r.noedge)}、E-REF-NONODE {ids(r.nonode)}"],
        ["`placement.toml`", "`[[placement]]` `[[attr]]`", f"入れ子 N-AZ・P-* {ids(r.placement)}、attrs {ids(r.attrs)}"],
    ]
    total = f"規則 ID は全部で {len(r.rule_ids)}（描く型の正規の型名 {len(r.drawn)} は別）。"
    return table(["ファイル", "表", "行数"], rows) + "\n\n" + total


# ------------------------------------------------------------------ 列の説明（core/rules.py の列の定義から作る）

KIND_TEXT = {"str": "文字列（空も可）", "text": "文字列", "strs": "文字列の配列", "strs1": "文字列の配列（1 つ以上）", "bool": "真偽", "int": "整数",
             "name_attr": "表 { tf, cfn }", "into": "表 { node_types, select }", "when": "表（下の when）"}

COLUMN_DOC = {
    # [[type]]
    ("type", "id"): "規則 ID。描く型は正規の型名（ノードの id の接頭辞と同じ）。M-*・H-* は接頭辞が class を決める",
    ("type", "class"): "`drawn`（ノードになる）／`merged_into`（M-*。別のノードに統合）／`hidden`（H-*。描かない）",
    ("type", "tf"): "入力の Terraform の型の一覧（末尾が `*` なら前方一致。空もある）",
    ("type", "cfn"): "入力の CloudFormation／SAM の型の一覧",
    ("type", "tf_note"): "`tf` の一覧に書けない補足（原文の言い回し）",
    ("type", "cfn_note"): "`cfn` の一覧に書けない補足（原文の言い回し）",
    ("type", "when"): "この行を使う条件（下の「when」）",
    ("type", "category"): "ノードの category（`resource`／`group`／`external`）",
    ("type", "name_attr"): "名前の属性（B3 の 2 番目）。`{ tf = \"name\", cfn = \"Name\" }`。タグだけなら `{}`",
    ("type", "icon"): "アイコンの辞書（`find_aws_icon.py --id`）のキーの候補",
    ("type", "synthetic"): "合成ノードを作る規則 ID（N-*）。合成ノードは入力の型（`tf`・`cfn`）を持たない",
    ("type", "name_from"): "名前を属性から取らないものの取り方（合成ノードなど）",
    ("type", "icon_note"): "アイコンの選び方の補足",
    ("type", "data"): "`true` なら、TF の `data` ブロックでも描く（描くリソースから参照されたとき。それ以外は H-DATA。範囲は手順 2 で決める）",
    ("type", "into"): "統合先。`node_types` は統合先の描く型、`select` は統合先の選び方（原文）",
    ("type", "reason"): "理由",
    ("type", "refs_as_target"): "`true` なら、統合したリソースの中の参照を、統合先からの参照として扱う",
    ("type", "applies"): "対象（原文。型では決まらないものの説明を含む）",
    ("type", "tf_data"): "対象の TF の `data` ブロックの型",
    ("type", "data_block"): "`true` なら、ほかの行に当たらない TF の `data` ブロックすべて",
    ("type", "evidence_source"): "`true` なら、E-IAM（推定の辺）の材料にしてから非表示にする",
    ("type", "module_sources_file"): "モジュールの source の前方一致で同じ規則にする一覧のファイル（SKILL からの相対パス。読むのは core/module_sources.py）",
    # [[relation]]
    ("relation", "id"): "規則 ID（`R-` で始まる）",
    ("relation", "class"): "`merged_into` 固定（関係リソースは辺に統合される。網羅分類の `into` は辺）",
    ("relation", "tf"): "網羅分類に出る Terraform のリソースの型",
    ("relation", "cfn"): "網羅分類に出る CloudFormation／SAM のリソースの型",
    ("relation", "tf_props"): "親リソースのプロパティ（ブロック）で表される関係（`型.属性`）。リソースではないので網羅分類には出ない",
    ("relation", "cfn_props"): "同上（CFN）",
    ("relation", "sam"): "SAM の `Events` の Type（リソースではないので網羅分類には出ない）",
    ("relation", "tf_note"): "補足",
    ("relation", "cfn_note"): "補足",
    ("relation", "edge"): "辺（from → to）の説明（原文）",
    ("relation", "kind"): "辺の kind（`request`／`event`／`data`／`route`／`network`）。空は「既存の辺に従う」（`kind_note` が要る）",
    ("relation", "kind_note"): "kind の補足",
    ("relation", "label"): "ラベルの説明（原文）",
    ("relation", "confidence"): "確信度。関係リソースの辺は `derived`（A3）",
    ("relation", "fallback"): "辺ができなかったときの H-* の規則 ID",
    ("relation", "when"): "この行を使う条件（`types` で対象の型を絞れる）",
    # edges.toml
    ("confidence", "level"): "`confirmed`／`derived`／`inferred`",
    ("confidence", "basis"): "根拠（原文）",
    ("confidence", "rules"): "この確信度になる規則（末尾が `*` なら前方一致）。辺の規則と関係リソースの `confidence` と食い違わない",
    ("confidence", "draw"): "描き方（フェーズ 4 以降）",
    ("edge", "id"): "規則 ID（`E-` で始まる）",
    ("edge", "input"): "入力（原文）",
    ("edge", "edge"): "辺（from → to）の説明（原文）",
    ("edge", "kind"): "辺の kind。空は、`kind_by` の表で決める（または辺を作らない）",
    ("edge", "kind_by"): "kind を決める表（`kind_by_target`／`iam_action_kind`／`merge_priority`）",
    ("edge", "kind_note"): "kind の補足（原文）",
    ("edge", "confidence"): "確信度。空は、規則が決めない（E-IAM-SUPPRESS）か、強い方を取る（E-MERGE）",
    ("edge", "confidence_note"): "確信度の補足",
    ("kind_by_target", "kind"): "kind",
    ("kind_by_target", "types"): "参照先の型（描く型。`apigw_*` のような前方一致も書ける）",
    ("iam_action_kind", "kind"): "kind。行の順が優先順（1 つのステートメントに複数のアクションがあれば上の行）",
    ("iam_action_kind", "actions"): "IAM のアクション（末尾が `*` なら前方一致）",
    ("iam_action_kind", "actions_note"): "アクションの補足（原文）",
    ("merge_priority", "rank"): "優先順（1 が最も強い。1 から順に 1 つずつ）",
    ("merge_priority", "rules"): "その順位の規則（末尾が `*` なら前方一致）",
    ("synthetic", "id"): "規則 ID（`N-` で始まる）",
    ("synthetic", "trigger"): "いつ作るか（原文）",
    ("synthetic", "node"): "作るノード（原文）",
    ("synthetic", "edges"): "作る辺（原文）",
    ("label_format", "subject"): "ラベルの種類",
    ("label_format", "format"): "書式（原文）",
    ("label_format", "example"): "例",
    # refs.toml
    ("noedge", "id"): "規則 ID（`E-NOEDGE-` で始まる）。上の行から順に当てはめ、最初に当たった規則を使う",
    ("noedge", "attrs"): "参照の属性名（raw IR の path の最後の要素）。TF の書き方で書けば CFN にも当たる（中立キー）。中立キーが同じになる別名は書かない",
    ("noedge", "use"): "代わりに使う規則（`R-*` のような前方一致も書ける。空は「描かない」）",
    ("noedge", "match"): "当たる参照（原文）",
    ("noedge", "use_text"): "代わりに使うところ（原文）",
    ("noedge", "from_class"): "属性名でなく、参照する側のリソースの class（`merged_into`・`hidden`）で当てる",
    ("noedge", "except_rules"): "`from_class` で当たるうち、除く統合の規則（M-*。`refs_as_target` の行）",
    ("nonode", "id"): "規則 ID（`E-REF-NONODE`）",
    ("nonode", "target"): "参照先（原文）",
    ("nonode", "handling"): "扱い（原文）",
    # placement.toml
    ("placement", "id"): "規則 ID（`N-AZ` または `P-` で始まる）",
    ("placement", "types"): "この規則で parent が決まる（または作られる）描く型",
    ("placement", "content"): "内容（原文）",
    ("attr", "type"): "描く型",
    ("attr", "name"): "`attrs` のキー",
    ("attr", "values"): "値",
    ("attr", "source"): "材料にする規則 ID",
    ("attr", "rule"): "決め方（原文）",
}


def _fields(tables: list[tuple[str, dict]]) -> str:
    """tables: [(表の名前, 列の定義)]。同じ名前の列は 1 行にまとめ、どの class で使うかを書く。"""
    rows = []
    seen: dict[str, list] = {}
    for name, spec in tables:
        for col, (kind, required) in spec.items():
            seen.setdefault(col, []).append((name, kind, required))
    for col, uses in seen.items():
        table_name = uses[0][0].split(":")[0]
        doc = COLUMN_DOC.get((table_name, col))
        if doc is None:
            raise KeyError(f"COLUMN_DOC に ({table_name!r}, {col!r}) の説明が無い（core/rules.py に列を足したら、ここにも足す）")
        kinds = {KIND_TEXT[k] for _, k, _ in uses}
        where = "・".join(sorted({n.split(":", 1)[1] for n, _, _ in uses if ":" in n}, key=lambda s: ("drawn", "merged_into", "hidden").index(s)))
        req = "必須" if all(rq for _, _, rq in uses) else "省略可"
        if ":" in uses[0][0] and any(rq for _, _, rq in uses) and not all(rq for _, _, rq in uses):
            req = "class による"
        rows.append([bt(col), "／".join(sorted(kinds)), req, where, doc])
    if not any(r[3] for r in rows):  # class で分かれない表（class の欄を出さない）
        return table(["列", "型", "必須", "意味"], [[r[0], r[1], r[2], r[4]] for r in rows])
    return table(["列", "型", "必須", "class（空は共通）", "意味"], rows)


def f_type(r) -> str:
    # 共通の列は class によらない（class の欄が空）。class ごとの列は、使う class を書く
    common = [("type", rule_data.TYPE_COMMON), ("type", {"when": ("when", False)})]
    return _fields(common + [("type:" + c, d) for c, d in rule_data.TYPE_BY_CLASS.items()])


def f_relation(r) -> str:
    return _fields([("relation", {**rule_data.RELATION, "when": ("when", False)})])


def f_edges(r) -> str:
    out = []
    for name in ("confidence", "edge", "kind_by_target", "iam_action_kind", "merge_priority", "synthetic", "label_format"):
        out.append(f"**`[[{name}]]`**\n\n" + _fields([(name, rule_data.OTHER_TABLES[name])]))
    out.append("**`edges.toml` の最上位のキー**\n\n" + table(["キー", "値", "意味"], [
        [bt("confidence_order"), bt('["confirmed", "derived", "inferred"]'), "E-MERGE: 確信度は強い方（左が強い）"],
        [bt("iam_action_priority"), bt('"first_row_wins"'), "`[[iam_action_kind]]` は、1 つのステートメントに複数のアクションがあれば上の行を優先"],
        [bt("iam_action_default"), bt('"none"'), "どの行にも当たらないアクションは辺を作らない（v0.1）"],
    ]))
    return "\n\n".join(out)


def f_refs(r) -> str:
    return "\n\n".join(f"**`[[{n}]]`**\n\n" + _fields([(n, rule_data.OTHER_TABLES[n])]) for n in ("noedge", "nonode"))


def f_placement(r) -> str:
    return "\n\n".join(f"**`[[{n}]]`**\n\n" + _fields([(n, rule_data.OTHER_TABLES[n])]) for n in ("placement", "attr"))


# 文書 → その中の生成部分（マーカーの名前の並び。この順に文書にある）
DOC_BLOCKS: dict[str, list[tuple[str, object]]] = {
    "README.md": [("layout", t_layout)],
    "types.md": [("fields-type", f_type), ("types-drawn", t_drawn), ("types-merged", t_merged), ("types-hidden", t_hidden)],
    "relations.md": [("fields-relation", f_relation), ("relations", t_relations)],
    "edges.md": [("fields-edges", f_edges), ("confidence", t_confidence), ("edge-rules", t_edge_rules), ("kind-by-target", t_kind_by_target),
                 ("iam-action-kind", t_iam_action_kind), ("synthetic", t_synthetic), ("merge-priority", t_merge_priority),
                 ("label-format", t_label_format)],
    "refs.md": [("fields-refs", f_refs), ("nonode", t_nonode), ("noedge", t_noedge)],
    "placement.md": [("fields-placement", f_placement), ("placement", t_placement), ("attrs", t_attrs)],
}


# ------------------------------------------------------------------ 文書への差し込み

def render_doc(text: str, blocks: list[tuple[str, object]], rules: rule_data.Rules, name: str) -> tuple[str, list[str]]:
    """文書の text の生成部分を、データから作った内容に置き換えたものと、問題（マーカーの欠け・余り・並びの誤り）。"""
    problems: list[str] = []
    lines = text.split("\n")
    out: list[str] = []
    found: list[str] = []
    i = 0
    funcs = dict(blocks)
    while i < len(lines):
        m = BEGIN.match(lines[i])
        if not m:
            if lines[i].strip() == END:
                problems.append(f"{name}: {i + 1} 行目: 対応する開始マーカーの無い {END}")
            out.append(lines[i])
            i += 1
            continue
        key = m.group(1)
        j = i + 1
        while j < len(lines) and lines[j].strip() != END:
            if BEGIN.match(lines[j]):
                break
            j += 1
        if j >= len(lines) or lines[j].strip() != END:
            problems.append(f"{name}: {i + 1} 行目: {key} の終了マーカー {END} が無い")
            out += lines[i:]
            break
        found.append(key)
        if key not in funcs:
            problems.append(f"{name}: {i + 1} 行目: 未知の生成部分 {key}（{[k for k, _ in blocks]} だけ）")
            out += lines[i:j + 1]
        else:
            out += [lines[i], GENERATED_NOTE, ""] + funcs[key](rules).split("\n") + ["", END]
        i = j + 1
    want = [k for k, _ in blocks]
    if found != want:
        problems.append(f"{name}: 生成部分のマーカーが {found}（あるべき並び: {want}）")
    return "\n".join(out), problems


def process(rules_dir: Path, docs_dir: Path, write: bool) -> list[str]:
    """文書を作り直して比べる（write なら書く）。食い違い・問題を文で返す（空なら一致）。"""
    rules = rule_data.load(rules_dir)
    problems: list[str] = []
    known = set(DOC_BLOCKS)
    if docs_dir.is_dir():
        for extra in sorted(p.name for p in docs_dir.glob("*.md") if p.name not in known):
            problems.append(f"{extra}: docs/spec/rules/ にあるが、render_rules.py の DOC_BLOCKS に無い文書")
    for name, blocks in DOC_BLOCKS.items():
        path = docs_dir / name
        if not path.is_file():
            problems.append(f"{name}: 文書が無い")
            continue
        text = path.read_bytes().decode("utf-8")
        new, probs = render_doc(text, blocks, rules, name)
        problems += probs
        if probs:
            continue
        if new != text:
            if write:
                path.write_bytes(new.encode("utf-8"))
            else:
                problems.append(f"{name}: 生成部分がデータ（data/rules/）と食い違う。`render_rules.py --write` で直せる")
    return problems


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--check", action="store_true", help="生成部分がデータと一致するか調べる（既定）")
    g.add_argument("--write", action="store_true", help="生成部分を書き直す")
    ap.add_argument("--rules-dir", type=Path, default=None)
    ap.add_argument("--docs-dir", type=Path, default=DOCS_DIR)
    a = ap.parse_args()
    try:
        problems = process(a.rules_dir or rule_data.paths.RULES_DIR, a.docs_dir, write=a.write)
    except rule_data.RulesError as e:
        print(e, file=sys.stderr)
        return 2
    if a.write:
        # 書いたあとに、マーカーの問題が残っていないことを確かめる
        fail = [p for p in problems if "食い違う" not in p]
        for p in fail:
            print(f"NG {p}")
        print("render_rules: 書き直した" if not fail else "render_rules: 書けなかった文書がある")
        return 2 if fail else 0
    for p in problems:
        print(f"NG {p}")
    print("render_rules: OK（docs/spec/rules/ の表はデータと一致）" if not problems else f"render_rules: {len(problems)} 件の食い違い")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
