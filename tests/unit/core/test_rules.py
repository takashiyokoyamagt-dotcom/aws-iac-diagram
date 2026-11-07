"""規則表（data/rules/）の読み込み・検査（core/rules.py）のテスト。

  1. 出荷した規則表の不変量（行数、規則 ID の数、正解 IR・文書が使う ID が実在する、正解 IR の型が草案のときと同じに描ける）
  2. 構造の検査: わざと壊した規則表（一時フォルダのコピー）が、はっきりしたエラーになる（変異テスト）
  3. 決定論: ディレクトリの列挙の順を変えても、読み順と結果が同じ
"""
from __future__ import annotations

import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from types import MappingProxyType
from unittest import mock

# tests/ を import の道に入れる（`python tests/.../test_x.py` で直接動かすときのため。discover では要らないが害は無い）
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "support").is_dir())))
from support.paths import EXPECTED, ROOT, SKILL
from support.rules_data import copy_rules, edit
from aws_iac_diagram.core import paths, rules  # noqa: E402

ID_IN_TEXT = re.compile(r"(?<![A-Za-z0-9_-])((?:H|M|R|E|N|P)-[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*)(?![A-Za-z0-9_-])")


class ShippedRulesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = rules.load()

    def test_row_counts_per_table(self):
        r = self.r
        self.assertEqual((len(r.drawn), len(r.merged), len(r.hidden), len(r.relations)), (32, 19, 15, 16))
        self.assertEqual((len(r.confidences), len(r.edges), len(r.kind_by_target), len(r.iam_action_kinds), len(r.merge_priority),
                          len(r.synthetic), len(r.label_formats)), (3, 12, 3, 3, 6, 2, 6))
        self.assertEqual((len(r.noedge), len(r.nonode), len(r.placement), len(r.attrs)), (7, 1, 5, 1))

    def test_rule_ids_per_prefix(self):
        ids = self.r.rule_ids
        by = {p: sorted(i for i in ids if i.startswith(p)) for p in ("E-", "H-", "M-", "N-", "P-", "R-")}
        self.assertEqual({p: len(v) for p, v in by.items()}, {"E-": 20, "H-": 15, "M-": 19, "N-": 3, "P-": 4, "R-": 16})
        self.assertEqual(len(ids), 77)
        self.assertEqual(self.r.edge_ids | self.r.ref_ids, frozenset(by["E-"]))
        self.assertEqual(len(self.r.ref_ids), 8)  # E-NOEDGE-* 7 と E-REF-NONODE
        self.assertEqual(self.r.synthetic_ids | {i for i in self.r.placement_ids if i.startswith("N-")}, frozenset(by["N-"]))
        self.assertEqual(self.r.placement_ids - {"N-AZ"}, frozenset(by["P-"]))
        self.assertTrue(self.r.drawn_ids.isdisjoint(ids))  # 描く型の名前は規則 ID と混ざらない

    def test_the_documented_rule_ids_are_defined(self):
        # 仕様の文書・正解 IR・スキーマが書いている規則 ID は、規則表にある（消していない・綴りを間違えていない）
        files = sorted((ROOT / "docs" / "spec" / "ir-schema").glob("*.md")) + [ROOT / "aws-iac-diagram-workspace" / "evals" / "CRITERIA.md"]
        files += sorted((SKILL / "data" / "schemas").glob("*.json"))
        used = set()
        for f in files:
            used |= set(ID_IN_TEXT.findall(f.read_text(encoding="utf-8")))
        self.assertGreaterEqual(len(used), 8)  # 空振りの防止
        ids = self.r.rule_ids
        unknown = sorted(x for x in used if x not in ids and not any(i.startswith(x + "-") for i in ids))  # `E-NOEDGE` のような接頭辞だけの書き方は可
        self.assertEqual(unknown, [])

    def test_expected_irs_use_defined_rules_and_drawable_types(self):
        ids, drawable = self.r.rule_ids, self.r.drawable_types()
        seen_rules = set()
        for p in sorted(EXPECTED.glob("*.ir.json")):
            ir = json.loads(p.read_text(encoding="utf-8"))
            nodes = {n["id"]: n for n in ir["nodes"]}
            for src in ir["sources"].values():
                for res in src["resources"]:
                    if "rule" in res:
                        seen_rules.add(res["rule"])
                        self.assertIn(res["rule"], ids, (p.name, res["address"]))
                    if res["class"] == "drawn" and res.get("via") != "module_blackbox":
                        self.assertIn(nodes[res["node"]]["type"], drawable[res["type"]], (p.name, res["address"]))
                for e in src["edges"]:
                    seen_rules |= set(e["rules"])
                    self.assertTrue(set(e["rules"]) <= ids, (p.name, e["edge"]))
        self.assertGreaterEqual(len(seen_rules), 10)  # 空振りの防止

    def test_every_drawn_type_has_a_placement(self):
        # 描く型は、VPC（最上位）と黒箱の module を除いて、どれかの入れ子の規則で parent が決まる（手順 2 で足した型の漏れを防ぐ）
        placed = {t for p in self.r.placement for t in p.types}
        self.assertEqual(sorted(self.r.drawn_ids - placed), ["module", "vpc"])

    def test_synthetic_types_and_module_row(self):
        self.assertEqual(self.r.synthetic_types, {"availability_zone", "external", "bedrock_model"})
        d = self.r.drawable_types()
        self.assertEqual(d["AWS::CloudFormation::Stack"], {"module"})
        self.assertEqual(d["aws_lb"], {"alb"})
        self.assertEqual(len(d), 65)
        self.assertNotIn("module", d)  # TF の黒箱の入力の型は module だが、規則表には書かない（validate_ir.py の BLACKBOX_TYPES）

    def test_column_values_match_the_schema_enums(self):
        # 列の値の集合（kind・category・確信度・via）は、スキーマの enum と同じ（ir.schema.json・ir-raw.schema.json）
        def enum_after(text: str, key: str) -> set[str]:
            m = re.search(rf'"{key}"\s*:\s*\{{"enum":\s*\[([^\]]*)\]', text)
            self.assertIsNotNone(m, key)
            return set(re.findall(r'"([^"]+)"', m.group(1)))
        schema = paths.IR_SCHEMA.read_text(encoding="utf-8")
        raw = paths.IR_RAW_SCHEMA.read_text(encoding="utf-8")
        self.assertEqual(enum_after(schema, "category"), set(rules.CATEGORIES))
        self.assertEqual(enum_after(schema, "kind"), set(rules.KINDS))
        self.assertEqual(enum_after(schema, "confidence"), set(rules.CONFIDENCES))
        self.assertEqual(enum_after(raw, "via"), set(rules.VIA_VALUES))

    def test_h_iam_points_at_the_module_source_list_that_core_reads(self):
        h = self.r.row("H-IAM")
        self.assertEqual(h.module_sources_file, paths.IAM_ONLY_SOURCES.relative_to(paths.SKILL_DIR).as_posix())
        self.assertTrue(h.evidence_source)

    def test_data_policy_is_carried_as_data(self):
        # 既存インフラを指す data（設計案 8 章の 3）の方針: 表の行の data = true、それ以外は H-DATA（動きは手順 2 以降）
        self.assertEqual(sorted(r.id for r in self.r.drawn if r.get("data")), ["s3_bucket", "subnet", "vpc"])
        self.assertTrue(self.r.row("H-DATA").data_block)

    def test_lookup_helpers(self):
        self.assertEqual(self.r.row("alb").category, "resource")
        with self.assertRaises(KeyError):
            self.r.row("no-such-row")
        self.assertEqual(sorted(x.id for x in self.r.rows_for_input_type("random_pet")), ["H-UTILITY"])  # 末尾 * の前方一致
        self.assertEqual(sorted(x.id for x in self.r.rows_for_input_type("aws_security_group_rule")), ["H-SG-EGRESS", "R-SG"])
        self.assertEqual(self.r.rows_for_input_type("aws_nothing"), ())
        self.assertEqual(rules.neutral_key("VpcId"), rules.neutral_key("vpc_id"))
        self.assertEqual(rules.neutral_key("CidrBlock"), "cidrblock")
        # awscc の型 → 同じ名前の CFN の型（正規化の分類と validate_ir の「描く型」の検査が共有する。ir-schema の 2 章）
        self.assertEqual(self.r.awscc_as_cfn("awscc_s3_bucket"), "AWS::S3::Bucket")
        self.assertEqual(self.r.awscc_as_cfn("awscc_ec2_vpc"), "AWS::EC2::VPC")
        self.assertIsNone(self.r.awscc_as_cfn("aws_s3_bucket"))
        self.assertIsNone(self.r.awscc_as_cfn("awscc_imaginary_thing"))

    def test_rows_are_read_only(self):
        row = self.r.row("alb")
        with self.assertRaises(TypeError):
            row.fields["id"] = "x"  # type: ignore[index]
        with self.assertRaises(AttributeError):
            row.id = "x"  # type: ignore[misc]
        self.assertIsInstance(row.tf, tuple)

    def test_rows_can_be_hashed_and_copied(self):
        # 行はハッシュでき（集合や辞書のキーにできる）、copy・deepcopy は同じ行を返す（変えられないので写さない。作りかけの行で
        # __getattr__ が自分を呼び続けない）。id の無い表（[[confidence]]）の行も同じ
        import copy
        for row in (self.r.row("alb"), self.r.confidences[0], self.r.attrs[0]):
            with self.subTest(row.table):
                self.assertEqual(hash(row), hash(row))
                self.assertIn(row, {row})
                self.assertIs(copy.copy(row), row)
                self.assertIs(copy.deepcopy(row), row)
                self.assertIs(copy.deepcopy([row])[0], row)
        self.assertEqual(hash(rules.load().row("alb")), hash(self.r.row("alb")))  # 等しい行は同じハッシュ
        a = rules.Row("t", "f", MappingProxyType({"a": 1, "b": 2}))
        b = rules.Row("t", "f", MappingProxyType({"b": 2, "a": 1}))
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))  # 列の順に依らない（eq と同じ）
        row = copy.deepcopy(self.r.row("alb"))
        with self.assertRaises(TypeError):
            row.fields["id"] = "x"  # type: ignore[index]
        with self.assertRaises(AttributeError):
            row.id = "x"  # type: ignore[misc]
        with self.assertRaises(AttributeError):
            row.__setstate__  # noqa: B018  列の名前でない（_ で始まる）ものは AttributeError（列に無い名前なので、ガードが無くても同じ）
        bare = object.__new__(rules.Row)  # fields の無い作りかけ（copy・pickle が経る形）でも、属性の問い合わせは AttributeError
        with self.assertRaises(AttributeError):
            bare.category  # noqa: B018

    def test_default_is_cached_and_equal_to_load(self):
        self.assertIs(rules.default(), rules.default())
        self.assertEqual([r.id for r in rules.default().types], [r.id for r in self.r.types])

    # --- 原文の説明（applies・match・reason など）と、機械が読む列が食い違わない（草案の表を写したときの取りこぼしの防止）

    def test_rule_ids_in_the_text_columns_exist(self):
        def strings(v):
            if isinstance(v, str):
                yield v
            elif isinstance(v, tuple):
                for x in v:
                    yield from strings(x)
            elif hasattr(v, "items"):
                for x in v.values():
                    yield from strings(x)
        id_text = re.compile(r"(?<![A-Za-z0-9_-])((?:H|M|R|E|N|P)-[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*)(?![A-Za-z0-9_*-])")
        n, bad = 0, []
        for tbl in (self.r.types, self.r.relations, self.r.confidences, self.r.edges, self.r.kind_by_target, self.r.iam_action_kinds,
                    self.r.merge_priority, self.r.synthetic, self.r.label_formats, self.r.noedge, self.r.nonode, self.r.placement, self.r.attrs):
            for row in tbl:
                for s in strings(row.fields):
                    for m in id_text.findall(s):
                        n += 1
                        if m not in self.r.rule_ids:
                            bad.append((row.get("id"), m))
        self.assertGreaterEqual(n, 80)  # 空振りの防止
        self.assertEqual(bad, [])

    def test_hidden_rows_list_the_input_types_their_text_names(self):
        typed = re.compile(r"`((?:data\.)?(?:aws_|awscc_|time_|random_|null_|terraform_)[A-Za-z0-9_*]*|AWS::[A-Za-z0-9]+::[A-Za-z0-9]+)`")
        n = 0
        for x in self.r.hidden:
            if x.get("data_block"):
                continue  # H-DATA の applies は例（`aws_ssm_parameter` など）で、型の一覧ではない
            listed = set(x.tf) | set(x.cfn) | {"data." + t for t in x.get("tf_data", ())}
            named = set(typed.findall(x.applies))
            self.assertEqual(named, listed, x.id)
            n += len(named)
        self.assertGreaterEqual(n, 20)

    def test_noedge_attrs_cover_the_names_in_the_text(self):
        name = re.compile(r"`([A-Za-z][A-Za-z0-9_-]*)`")
        n = 0
        for x in self.r.noedge:
            if x.get("from_class"):
                continue
            keys = {rules.neutral_key(a) for a in x.attrs}
            for t in name.findall(x.match):
                self.assertIn(rules.neutral_key(t), keys, (x.id, t))
                n += 1
        self.assertGreaterEqual(n, 25)

    def test_input_types_shared_by_two_rows_are_the_two_known_cases(self):
        # 同じ入力の型が、統合の行・関係の行・描く型の行の複数にあるのは、when で分かれるものだけ（読み込みが検査する）。
        # その例外が増えていない（今あるのは 2 つの型）
        seen: dict[str, list[str]] = {}
        for x in (*self.r.types, *self.r.relations):
            for t in (*x.tf, *x.cfn):
                seen.setdefault(t, []).append(x.id)
        shared = {t: ids for t, ids in seen.items() if len(ids) > 1}
        self.assertEqual(shared, {"aws_security_group_rule": ["H-SG-EGRESS", "R-SG"], "AWS::CloudFormation::Stack": ["module", "H-NESTED-STACK"]})


class StructureTest(unittest.TestCase):
    """わざと壊した規則表（一時フォルダのコピー）は、はっきりしたエラーになる。"""

    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.dir = copy_rules(Path(td.name) / "日本語 パス")
        rules.load(self.dir)  # コピーそのものは通る

    def assertBroken(self, *needles: str) -> list[str]:
        with self.assertRaises(rules.RulesError) as cm:
            rules.load(self.dir)
        text = "\n".join(cm.exception.problems)
        for n in needles:
            self.assertIn(n, text)
        self.assertTrue(str(cm.exception).startswith("規則表（data/rules/）に問題があります"))
        return cm.exception.problems

    def test_bad_toml(self):
        edit(self.dir, "types/compute.toml", 'class = "drawn"', "class = ", count=5)
        self.assertBroken("types/compute.toml: TOML として読めない")

    def test_not_utf8(self):
        (self.dir / "refs.toml").write_bytes("# あ\n".encode("cp932"))
        self.assertBroken("refs.toml: 読めない（UTF-8")

    def test_duplicate_ids(self):
        edit(self.dir, "types/compute.toml", 'id = "ec2_instance"', 'id = "ecs_service"')
        self.assertBroken("id 'ecs_service' が重複")
        # ファイルをまたぐ重複（relations.toml の R-ROUTE を、別の表の ID にする）
        self.setUp()
        edit(self.dir, "relations.toml", 'id = "R-ROUTE"', 'id = "R-SG"')
        self.assertBroken("id 'R-SG' が重複")

    def test_unknown_field_and_missing_required_column(self):
        edit(self.dir, "relations.toml", 'id = "R-ROUTE"', 'id = "R-ROUTE"\nbogus = 1')
        self.assertBroken("未知のフィールド 'bogus'")
        self.setUp()
        edit(self.dir, "types/network.toml", 'category = "group"\n', "", count=3)
        self.assertBroken("必須の列 'category' が無い")

    def test_wrong_column_types(self):
        edit(self.dir, "types/network.toml", 'tf = ["aws_vpc"]', 'tf = "aws_vpc"')
        self.assertBroken("'tf' は文字列の配列")
        self.setUp()
        edit(self.dir, "types/network.toml", 'name_attr = { tf = "name", cfn = "Name" }', 'name_attr = { tf = 1 }')
        self.assertBroken("'name_attr'")
        self.setUp()
        edit(self.dir, "edges.toml", "rank = 1", 'rank = "1"')
        self.assertBroken("'rank' は整数")

    def test_prefix_and_class_must_agree(self):
        edit(self.dir, "types/merged-and-hidden.toml", 'id = "H-LOGS"', 'id = "X-LOGS"')
        self.assertBroken("class hidden の id 'X-LOGS' は H-* の形の規則 ID")
        self.setUp()
        edit(self.dir, "types/merged-and-hidden.toml", 'id = "M-EIP-NAT"', 'id = "H-EIP-NAT"')
        self.assertBroken("class merged_into の id 'H-EIP-NAT' は M-*")
        self.setUp()
        edit(self.dir, "types/network.toml", 'id = "vpc"', 'id = "R-VPC"')
        self.assertBroken("描く型の id 'R-VPC' は正規の型名")
        self.setUp()
        edit(self.dir, "types/network.toml", 'class = "drawn"', 'class = "visible"', count=8)
        self.assertBroken("class は ['drawn', 'merged_into', 'hidden'] のどれか")
        self.setUp()
        edit(self.dir, "relations.toml", 'id = "R-SG"', 'id = "E-SG"')
        self.assertBroken("[[relation]] の id 'E-SG' は R-*")

    def test_input_type_overlap(self):
        edit(self.dir, "types/network.toml", 'tf = ["aws_internet_gateway"]', 'tf = ["aws_internet_gateway", "aws_vpc"]')
        self.assertBroken("型 aws_vpc が複数の行に当たる: vpc")
        # when が同時に成り立たないなら、同じ型が複数の行にあってよい（出荷した表の aws_security_group_rule・AWS::CloudFormation::Stack）
        self.setUp()
        edit(self.dir, "types/merged-and-hidden.toml", 'when = { types = ["aws_security_group_rule"], prop = { tf = "type" }, in = ["egress"] }\n', "")
        self.assertBroken("型 aws_security_group_rule が複数の行に当たる")
        self.setUp()
        edit(self.dir, "relations.toml", 'in = ["ingress"]', 'in = ["egress", "ingress"]')
        self.assertBroken("型 aws_security_group_rule が複数の行に当たる")  # in が重なる
        self.setUp()
        edit(self.dir, "types/merged-and-hidden.toml", 'when = { via_not = ["module_blackbox"] }', 'when = { via = ["module_blackbox"] }')
        self.assertBroken("型 AWS::CloudFormation::Stack が複数の行に当たる")  # どちらも via が module_blackbox
        self.setUp()
        edit(self.dir, "types/network.toml", 'tf = ["aws_internet_gateway"]', 'tf = ["aws_internet_gateway", "aws_*"]')
        self.assertBroken("が複数の行に当たる")  # 末尾 * の前方一致も重なりとして数える
        self.setUp()
        edit(self.dir, "types/network.toml", 'tf = ["aws_internet_gateway"]', 'tf = ["aws_internet_gateway", "aws_nat_gateway", "aws_nat_gateway"]')
        self.assertBroken("tf に同じ型が 2 回ある")

    def test_input_type_shapes(self):
        edit(self.dir, "types/network.toml", 'cfn = ["AWS::EC2::VPC"]', 'cfn = ["aws_vpc2"]')
        self.assertBroken("'aws_vpc2' は CFN の型の形でない")
        self.setUp()
        edit(self.dir, "types/network.toml", 'tf = ["aws_vpc"]', 'tf = ["AWS::EC2::VPC"]')
        self.assertBroken("は TF の型の形でない")

    def test_unknown_tables_keys_and_files(self):
        (self.dir / "refs.toml").write_text((self.dir / "refs.toml").read_text(encoding="utf-8") + '\n[[bogus]]\nid = "x"\n',
                                            encoding="utf-8", newline="\n")
        self.assertBroken("refs.toml: 未知のキー 'bogus'")
        self.setUp()
        edit(self.dir, "relations.toml", "[[relation]]\nid = \"R-ROUTE\"", "[[type]]\nid = \"R-ROUTE\"")
        self.assertBroken("relations.toml: 未知のキー 'type'")
        self.setUp()
        (self.dir / "relations.toml").write_text('top = 1\n' + (self.dir / "relations.toml").read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
        self.assertBroken("relations.toml: 未知のキー 'top'")

    def test_missing_and_stray_files(self):
        (self.dir / "relations.toml").unlink()
        self.assertBroken("relations.toml: 無い")
        self.setUp()
        (self.dir / "notes.txt").write_text("x", encoding="utf-8")
        self.assertBroken("notes.txt: 規則表のフォルダに置いてよい名前ではない")
        self.setUp()
        (self.dir / "types" / "README.md").write_text("x", encoding="utf-8")
        self.assertBroken("types/README.md: 読まれない")
        self.setUp()
        for f in (self.dir / "types").glob("*.toml"):
            f.unlink()
        self.assertBroken("types/: .toml のファイルが 1 つも無い")
        self.setUp()
        import shutil
        shutil.rmtree(self.dir / "types")
        self.assertBroken("types/: 無い")
        with self.assertRaises(rules.RulesError):
            rules.load(self.dir.parent / "nowhere")  # 規則表のフォルダごと無い

    def test_os_and_editor_junk_files_are_ignored(self):
        # OS やエディタが作るファイル（.DS_Store、Thumbs.db、desktop.ini、控え edges.toml~、vim の .swp、emacs の #…#）は黙って読まない
        junk = (".DS_Store", "Thumbs.db", "Desktop.ini", "edges.toml~", ".edges.toml.swp", "edges.toml.swp", "#refs.toml#", ".hidden")
        for d in (self.dir, self.dir / "types"):
            for n in junk:
                (d / n).write_bytes(b"\x00\xff junk")
        (self.dir / ".cache").mkdir()
        (self.dir / "types" / ".backup").mkdir()
        (self.dir / "types" / ".backup" / "compute.toml").write_text("not = [toml", encoding="utf-8")
        self.assertEqual(rules.load(self.dir), rules.load())
        # ほかの名前は、これまでどおり誤り（置き場所・綴りの違い）
        (self.dir / "foo.toml").write_text("", encoding="utf-8")
        (self.dir / "types" / "compute.toml.bak").write_text("", encoding="utf-8")
        self.assertBroken("foo.toml: 規則表のフォルダに置いてよい名前ではない", "types/compute.toml.bak: 読まれない")

    def test_wrongly_typed_values_are_errors_not_crashes(self):
        # 列の型の違う値は、表どうしの検査（ハッシュ・文字列の操作をする）に回さず、列の検査の文だけになる（TypeError などで落ちない）
        cases = [
            ("relations.toml", 'fallback = "H-RT-NOROUTE"', 'fallback = {a="b"}', "'fallback' は空でない文字列"),
            ("refs.toml", 'attrs = ["role", ', 'attrs = [1, "role", ', "'attrs' は文字列の配列"),
            ("refs.toml", 'use = ["R-SG"]', "use = [1]", "'use' は文字列の配列"),
            ("relations.toml", 'prop = { tf = "type" }, in = ["ingress"]', 'prop = { tf = "type" }', "when.prop があるのに when.in が無い"),
            ("types/merged-and-hidden.toml", 'node_types = ["nat_gateway"]', "node_types = [1]", "'into' は"),
            ("edges.toml", 'level = "derived"', "level = [1]", "'level' は空でない文字列"),
            ("edges.toml", 'confidence_order = ["confirmed", "derived", "inferred"]', "confidence_order = 1", "confidence_order は"),
            ("types/merged-and-hidden.toml", 'module_sources_file = "data/module-summaries/iam-only-sources.md"',
             "module_sources_file = [1]", "'module_sources_file' は空でない文字列"),
        ]
        for rel, old, new, needle in cases:
            with self.subTest(new):
                self.setUp()
                edit(self.dir, rel, old, new)
                self.assertBroken(needle)

    def test_one_wrong_value_gives_one_error(self):
        # ほかの行が引く行（確信度の rules、辺にしない参照の except_rules）の別の列が誤っていても、引く側の行に
        # 「無い」「指していない」の誤りが連鎖しない（第三者レビュー 2 回目の 1）
        cases = [
            ("edges.toml", 'level = "derived"', "basis", "basis = 1", "'basis'"),
            ("edges.toml", 'level = "derived"', None, "draw2 = 1", "draw2"),
            ("refs.toml", 'id = "E-NOEDGE-FROM-RULE"', "match", "match = 1", "'match'"),
        ]
        for rel, anchor, key, line, needle in cases:
            with self.subTest(line):
                self.setUp()
                # anchor の行の後ろで、key の行を line に差し替える（key が None なら anchor の次に line を足す）
                p = self.dir / rel
                text = p.read_text(encoding="utf-8")
                at = text.index(anchor) + len(anchor) + 1
                if key is not None:
                    at = text.index(f"\n{key} = ", at - 1) + 1
                    text = text[:at] + text[text.index("\n", at) + 1:]
                p.write_text(text[:at] + line + "\n" + text[at:], encoding="utf-8", newline="\n")
                problems = self.assertBroken(needle)
                self.assertEqual(len(problems), 1, problems)

    def test_dot_toml_in_types_is_an_error(self):
        # `.` で始まる .toml は OS・エディタのファイルとして黙らせず、読まれないことを知らせる（型の表を隠したつもりのない誤り）
        (self.dir / "types" / "compute.toml").rename(self.dir / "types" / ".compute.toml")
        self.assertBroken("types/.compute.toml: 読まれない")

    def test_module_sources_file_must_stay_inside_the_skill(self):
        # SKILL の外（`..`・絶対パス）は、ファイルがあっても誤り（SKILL の外のファイルを規則として読ませない）
        for name in ("..", "absolute", "data/.."):
            with self.subTest(name):
                self.setUp()
                outside = self.dir.parent.parent.parent / "x.md"  # <tmp>/日本語 パス/x.md（SKILL = <tmp>/日本語 パス/skill の外）
                outside.write_text("x\n", encoding="utf-8")
                f = {"..": "../x.md", "absolute": outside.as_posix(), "data/..": "data/../../x.md"}[name]
                edit(self.dir, "types/merged-and-hidden.toml", 'module_sources_file = "data/module-summaries/iam-only-sources.md"',
                     f'module_sources_file = "{f}"')
                self.assertBroken(f"module_sources_file {f!r} が SKILL の外を指す")

    def test_bad_references(self):
        cases = [
            ("types/merged-and-hidden.toml", 'node_types = ["nat_gateway"]', 'node_types = ["nat_gatewayy"]', "into.node_types ['nat_gatewayy'] が描く型にない"),
            ("relations.toml", 'fallback = "H-RT-NOROUTE"', 'fallback = "H-NOPE"', "fallback 'H-NOPE' が非表示の規則（H-*）にない"),
            ("relations.toml", 'fallback = "H-RT-NOROUTE"', 'fallback = "M-EIP-NAT"', "fallback 'M-EIP-NAT'"),
            ("placement.toml", 'types = ["availability_zone", "subnet"]', 'types = ["availability_zone", "zubnet"]', "'zubnet' が描く型にない"),
            ("placement.toml", 'source = "R-ROUTE"', 'source = "R-NOPE"', "source 'R-NOPE' が規則 ID にない"),
            ("placement.toml", 'type = "subnet"', 'type = "nothing"', "[[attr]] の type 'nothing'"),
            ("refs.toml", 'use = ["P-*"]', 'use = ["Q-*"]', "use の 'Q-*' に当たる規則 ID が無い"),
            ("refs.toml", 'except_rules = ["M-ECS-TASKDEF", "M-APIGW-AUTHORIZER"]', 'except_rules = ["M-ECS-TASKDEF", "M-NOPE"]', "except_rules 'M-NOPE'"),
            ("refs.toml", 'from_class = ["merged_into", "hidden"]', 'from_class = ["merged_into", "drawn"]', "from_class 'drawn'"),
            ("edges.toml", 'rules = ["E-ENV-REF", "E-KB-STORAGE", "E-CDN-ORIGIN"', 'rules = ["E-ENV-REF", "E-KB-STORAGE", "E-NOPE", "E-CDN-ORIGIN"', "'E-NOPE' に当たる規則 ID が無い"),
            ("edges.toml", 'rules = ["E-ENV-STR"]', 'rules = ["E-ENV-STR", "X-*"]', "'X-*' に当たる規則 ID が無い"),
            ("edges.toml", 'types = ["sns_topic", "sqs_queue", "eventbridge_rule"]', 'types = ["sns_topic", "sqs_queuee", "eventbridge_rule"]', "'sqs_queuee' が描く型にない"),
            ("edges.toml", 'kind = "event"\ntypes', 'kind = "bogus"\ntypes', "[[kind_by_target]] の kind 'bogus'"),
            ("edges.toml", 'kind_by = "iam_action_kind"', 'kind_by = "nothing"', "kind_by 'nothing'"),
            ("relations.toml", 'kind = "route"', 'kind = "bogus"', "kind 'bogus'"),
            ("relations.toml", 'confidence = "derived"\nfallback = "H-RT-NOROUTE"', 'confidence = "inferred"\nfallback = "H-RT-NOROUTE"',
             "confidence inferred が、edges.toml の確信度の表の rules に無い"),
        ]
        for rel, old, new, want in cases:
            with self.subTest(want):
                self.setUp()
                p = self.dir / rel
                text = p.read_text(encoding="utf-8")
                self.assertIn(old, text)
                p.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")
                self.assertBroken(want)

    def test_synthetic_nodes_must_not_have_input_types(self):
        edit(self.dir, "types/network.toml", 'synthetic = "N-AZ"\ntf = []\ncfn = []', 'synthetic = "N-AZ"\ntf = ["aws_az"]\ncfn = []')
        self.assertBroken("合成ノード availability_zone に入力の型")
        self.setUp()
        edit(self.dir, "types/network.toml", 'synthetic = "N-AZ"', 'synthetic = "N-NOPE"')
        self.assertBroken("synthetic 'N-NOPE' が、合成ノードの規則")
        self.setUp()
        edit(self.dir, "types/network.toml", 'tf = ["aws_internet_gateway"]\ncfn = ["AWS::EC2::InternetGateway"]', "tf = []\ncfn = []")
        self.assertBroken("描く型 internet_gateway に入力の型（tf・cfn）が 1 つも無い")

    def test_neutral_keys_must_not_repeat(self):
        edit(self.dir, "refs.toml", '"availability_zone", "db_subnet_group_name"', '"availability_zone", "AvailabilityZone", "db_subnet_group_name"')
        self.assertBroken("中立キー", "AvailabilityZone")
        self.setUp()
        edit(self.dir, "refs.toml", 'attrs = ["security_groups",', 'attrs = ["role", "security_groups",')
        self.assertBroken("属性名 'role' が E-NOEDGE-ROLE と E-NOEDGE-SG の両方にある")
        self.assertEqual(rules.neutral_key("VPCSecurityGroups"), "vpcsecuritygroups")

    def test_when_is_checked(self):
        edit(self.dir, "types/network.toml", ', in = ["application"]', "")
        self.assertBroken("when.prop があるのに when.in が無い")
        self.setUp()
        edit(self.dir, "types/network.toml", 'default = "application"', 'default = "network"')
        self.assertBroken("when.default は when.in の中の値")
        self.setUp()
        edit(self.dir, "types/network.toml", 'in = ["application"]', 'in = ["application"], foo = 1')
        self.assertBroken("when の未知のキー 'foo'")
        self.setUp()
        edit(self.dir, "types/merged-and-hidden.toml", 'via_not = ["module_blackbox"]', 'via_not = ["nowhere"]')
        self.assertBroken("when.via_not は ['nested_stack', 'module_summary', 'module_blackbox'] のどれか")
        self.setUp()
        edit(self.dir, "types/merged-and-hidden.toml", 'via_not = ["module_blackbox"]', 'via = ["nested_stack"], via_not = ["module_blackbox"]')
        self.assertBroken("when.via と when.via_not は一緒に書かない")
        self.setUp()
        edit(self.dir, "edges.toml", "[[confidence]]\nlevel = \"inferred\"", "[[confidence]]\nlevel = \"inferred\"\nwhen = { via = [\"nested_stack\"] }")
        self.assertBroken("[[confidence]] #3（inferred）: 未知のフィールド 'when'")  # when は型と関係の行だけ

    def test_data_policy_needs_an_h_data_row(self):
        edit(self.dir, "types/merged-and-hidden.toml", "data_block = true\n", "")
        self.assertBroken("data = true の型があるのに、data_block = true の H-* の行（H-DATA）が無い")

    def test_module_sources_file_must_exist(self):
        edit(self.dir, "types/merged-and-hidden.toml", 'module_sources_file = "data/module-summaries/iam-only-sources.md"',
             'module_sources_file = "data/module-summaries/nowhere.md"')
        self.assertBroken("module_sources_file 'data/module-summaries/nowhere.md' が SKILL の下に無い")

    def test_merge_priority_and_confidence_tables(self):
        edit(self.dir, "edges.toml", "rank = 3", "rank = 4")
        self.assertBroken("rank は 1 から順に 1 つずつ")
        self.setUp()
        edit(self.dir, "edges.toml", 'level = "derived"', 'level = "confirmed"')
        self.assertBroken("level が重複")
        self.setUp()
        edit(self.dir, "edges.toml", 'confidence_order = ["confirmed", "derived", "inferred"]', 'confidence_order = ["derived", "confirmed", "inferred"]')
        self.assertBroken("confidence_order は")
        self.setUp()
        edit(self.dir, "edges.toml", 'iam_action_priority = "first_row_wins"', 'iam_action_priority = "last_row_wins"')
        self.assertBroken("iam_action_priority")
        for bad in ("1", "[]", '"all"'):
            self.setUp()
            edit(self.dir, "edges.toml", 'iam_action_default = "none"', f"iam_action_default = {bad}")
            self.assertBroken("iam_action_default")
        self.setUp()
        edit(self.dir, "edges.toml", '    "dynamodb:*",\n', '    "dynamodb:*",\n    "sns:Publish",\n')
        self.assertBroken("アクション 'sns:Publish' が重複")

    def test_refs_as_target_must_be_used_by_an_exception(self):
        edit(self.dir, "refs.toml", 'except_rules = ["M-ECS-TASKDEF", "M-APIGW-AUTHORIZER"]', "except_rules = []")
        self.assertBroken("refs_as_target の ['M-ECS-TASKDEF', 'M-APIGW-AUTHORIZER'] を、辺にしない参照の except_rules が指していない")

    def test_all_problems_are_collected(self):
        edit(self.dir, "relations.toml", 'id = "R-ROUTE"', 'id = "R-SG"')
        edit(self.dir, "refs.toml", 'use = ["P-*"]', 'use = ["Q-*"]')
        edit(self.dir, "types/compute.toml", 'tf = ["aws_instance"]', 'tf = "aws_instance"')
        problems = self.assertBroken("重複", "Q-*", "'tf' は文字列の配列")
        self.assertGreaterEqual(len(problems), 3)


class DeterminismTest(unittest.TestCase):
    def test_read_order_does_not_depend_on_directory_listing_order(self):
        want = [r.id for r in rules.load().types]
        real = Path.iterdir
        for name, fn in (("reversed", lambda self_: iter(reversed(list(real(self_))))),
                         ("shuffled", lambda self_: iter(sorted(real(self_), key=lambda p: hash(p.name) % 7)))):
            with self.subTest(name), mock.patch.object(Path, "iterdir", fn):
                got = rules.load()
                self.assertEqual([r.id for r in got.types], want)
                self.assertEqual([r.file for r in got.types], [r.file for r in rules.load().types])
        # 読む順: types/ の中は名前の昇順、そのあと relations → edges → refs → placement
        order = []
        for r in rules.load().types:
            if r.file not in order:
                order.append(r.file)
        self.assertEqual(order, sorted(order))
        self.assertEqual(len(order), 7)

    def test_error_messages_do_not_depend_on_directory_listing_order(self):
        with tempfile.TemporaryDirectory() as t:
            d = copy_rules(Path(t))
            for n in ("a.txt", "b.txt", "c.txt"):
                (d / n).write_text("x", encoding="utf-8")
            (d / "types" / "z.md").write_text("x", encoding="utf-8")
            (d / "types" / "y.md").write_text("x", encoding="utf-8")

            def problems():
                with self.assertRaises(rules.RulesError) as cm:
                    rules.load(d)
                return cm.exception.problems
            want = problems()
            self.assertEqual(len(want), 5)
            self.assertEqual(want, sorted(want[:3]) + sorted(want[3:]))  # 名前の昇順（ルート 3 件、types/ 2 件）
            real = Path.iterdir
            for name, fn in (("reversed", lambda self_: iter(reversed(list(real(self_))))),
                             ("shuffled", lambda self_: iter(sorted(real(self_), key=lambda p: hash(p.name) % 7)))):
                with self.subTest(name), mock.patch.object(Path, "iterdir", fn):
                    self.assertEqual(problems(), want)

    def test_results_are_equal_across_independent_loads(self):
        a, b = rules.load(), rules.load()
        self.assertEqual(a, b)
        self.assertEqual(sorted(a.rule_ids), sorted(b.rule_ids))
        self.assertEqual(a.drawable_types(), b.drawable_types())


if __name__ == "__main__":
    unittest.main()
