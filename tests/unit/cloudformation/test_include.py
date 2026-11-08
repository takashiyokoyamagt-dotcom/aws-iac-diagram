"""CloudFormation アダプタ: Fn::Transform の AWS::Include（include.py。docs/spec/ir-schema/ の 7.4）。"""

from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

# tests/ を import の道に入れる（`python tests/.../test_x.py` で直接動かすときのため。discover では要らないが害は無い）
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "support").is_dir())))
from support.builders import assert_valid
from support.cloudformation import ref_by, write_files
from support.main_set import main_set_raw
from aws_iac_diagram.adapters.cloudformation import build as cfn_build  # noqa: E402
from aws_iac_diagram.adapters.cloudformation import include as cfn_include  # noqa: E402


def api_template(location: str) -> str:
    return f"""
        Resources:
          Fn:
            Type: AWS::Lambda::Function
          Role:
            Type: AWS::IAM::Role
          Api:
            Type: AWS::Serverless::Api
            Properties:
              StageName: Prod
              DefinitionBody:
                Fn::Transform:
                  Name: AWS::Include
                  Parameters:
                    Location: {location}
        """


OPENAPI_YAML = """
    openapi: "3.0.1"
    paths:
      /items:
        get:
          x-amazon-apigateway-integration:
            credentials:
              Fn::GetAtt: [Role, Arn]
            uri:
              Fn::Sub: arn:aws:apigateway:${AWS::Region}:lambda:path/2015-03-31/functions/${Fn.Arn}/invocations
            type: aws_proxy
    """

OPENAPI_JSON = """
    {"openapi": "3.0.1",
     "paths": {"/items": {"post": {"x-amazon-apigateway-integration": {
       "uri": {"Fn::Sub": "arn:aws:apigateway:${AWS::Region}:lambda:path/2015-03-31/functions/${Fn.Arn}/invocations"},
       "credentials": {"Ref": "Role"}, "type": "aws_proxy"}}}}}
    """

URI = 'Properties.DefinitionBody.paths["/items"].{}.x-amazon-apigateway-integration.uri'


def build(files: dict[str, str], top: str = "main.yaml", root: str = "") -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        write_files(tmp, files)
        return cfn_build.build_raw(tmp / top, tmp / root if root else tmp)


def api_props(raw: dict) -> dict:
    return next(r for r in raw["resources"] if r["address"] == "Api")["props"]


class IncludeTest(unittest.TestCase):
    def test_yaml_relative_path_is_inlined_and_refs_are_active(self):
        raw = build({"main.yaml": api_template("./api.yaml"), "api.yaml": OPENAPI_YAML})
        assert_valid(self, raw)
        self.assertEqual(raw["diagnostics"], [])
        body = api_props(raw)["DefinitionBody"]
        self.assertEqual(body["openapi"], "3.0.1")
        integ = body["paths"]["/items"]["get"]["x-amazon-apigateway-integration"]
        self.assertEqual(integ["credentials"], {"$res": "Role", "attr": "Arn"})
        self.assertIn({"$res": "Fn", "attr": "Arn"}, integ["uri"]["$concat"])
        r = ref_by(raw, "Api", URI.format("get"))
        self.assertEqual([(x["to"], x["attr"], x["fn"], x["state"]) for x in r], [("Fn", "Arn", "Sub", "active")])
        cred = ref_by(raw, "Api", URI.format("get").replace(".uri", ".credentials"))
        self.assertEqual([(x["to"], x["fn"], x["state"]) for x in cred], [("Role", "GetAtt", "active")])
        # 差し込んだ位置とファイルを assumptions に書く（どこから来た中身か追えるように）
        self.assertEqual(raw["evaluation"]["assumptions"],
                         ["Api.Properties.DefinitionBody: AWS::Include の Location ./api.yaml に api.yaml を差し込んだ"])

    def test_json_file(self):
        raw = build({"main.yaml": api_template("api.json"), "api.json": OPENAPI_JSON})
        self.assertEqual(raw["diagnostics"], [])
        self.assertEqual([x["to"] for x in ref_by(raw, "Api", URI.format("post"))], ["Fn"])
        cred = ref_by(raw, "Api", URI.format("post").replace(".uri", ".credentials"))
        self.assertEqual([(x["to"], x["fn"]) for x in cred], [("Role", "Ref")])

    def test_s3_url_is_matched_by_path_suffix(self):
        raw = build({"main.yaml": api_template("s3://my-bucket/specs/api.yaml"),
                     "specs/api.yaml": OPENAPI_YAML,
                     "other/api.yaml": "openapi: '3.0.1'\npaths: {}\n"})
        self.assertEqual(raw["diagnostics"], [])
        self.assertIn("/items", api_props(raw)["DefinitionBody"]["paths"])  # 末尾 2 要素が一致する specs/api.yaml
        self.assertEqual(raw["evaluation"]["assumptions"],
                         ["Api.Properties.DefinitionBody: AWS::Include の Location s3://my-bucket/specs/api.yaml に "
                          "specs/api.yaml を差し込んだ"])
        # 末尾が同じだけ一致するファイルが 2 つあれば、決めずに評価しない
        raw = build({"main.yaml": api_template("s3://my-bucket/api.yaml"),
                     "a/api.yaml": OPENAPI_YAML, "b/api.yaml": OPENAPI_YAML})
        self.assertEqual(api_props(raw)["DefinitionBody"],
                         {"$unknown": "Fn::Transform AWS::Include: s3://my-bucket/api.yaml is not found locally"})
        self.assertEqual(raw["evaluation"]["assumptions"], [])

    def test_missing_or_remote_file_stays_unevaluated(self):
        for loc in ("./missing.yaml", "s3://my-bucket/missing.yaml"):
            with self.subTest(loc):
                raw = build({"main.yaml": api_template(loc)})
                assert_valid(self, raw)
                why = f"Fn::Transform AWS::Include: {loc} is not found locally"
                self.assertEqual(api_props(raw)["DefinitionBody"], {"$unknown": why})
                self.assertEqual([(d["code"], d["level"], d["address"], d["path"], d["message"]) for d in raw["diagnostics"]],
                                 [("CFN-UNEVALUATED", "warn", "Api", "Properties.DefinitionBody", why)])

    def test_other_transforms_and_computed_locations_are_not_evaluated(self):
        raw = build({"main.yaml": """
            Parameters:
              Spec: {Type: String}
            Resources:
              Q:
                Type: AWS::SQS::Queue
                Properties:
                  A:
                    Fn::Transform: {Name: MyMacro, Parameters: {X: !Ref Q}}
                  B:
                    Fn::Transform: {Name: AWS::Include, Parameters: {Location: !Ref Spec}}
            """})
        props = next(r for r in raw["resources"] if r["address"] == "Q")["props"]
        self.assertEqual(props["A"], {"$unknown": "Fn::Transform is not evaluated"})
        self.assertEqual(props["B"], {"$unknown": "Fn::Transform AWS::Include with a computed Location"})
        # 評価しないマクロの中の参照は、これまでどおり unevaluated で残す
        self.assertEqual([(x["to"], x["state"]) for x in ref_by(raw, "Q", "Properties.A")], [("Q", "unevaluated")])

    def test_path_outside_the_root_is_not_read(self):
        raw = build({"proj/main.yaml": api_template("../secret.yaml"), "secret.yaml": OPENAPI_YAML},
                    top="proj/main.yaml", root="proj")
        why = "Fn::Transform AWS::Include: ../secret.yaml is outside the root folder"
        self.assertEqual(api_props(raw)["DefinitionBody"], {"$unknown": why})
        self.assertEqual([d["code"] for d in raw["diagnostics"]], ["CFN-UNEVALUATED"])

    def test_cycles_are_cut(self):
        include = "Fn::Transform: {{Name: AWS::Include, Parameters: {{Location: {}}}}}\n"
        raw = build({"main.yaml": api_template("./parts/a.yaml"),
                     # 差し込んだファイルの中の相対パスは、そのファイルのフォルダから
                     "parts/a.yaml": "openapi: '3.0.1'\npaths:\n  " + include.format("./b.yaml"),
                     "parts/b.yaml": "/x:\n  get:\n    " + include.format("./a.yaml")})
        assert_valid(self, raw)
        body = api_props(raw)["DefinitionBody"]
        self.assertEqual(body["paths"]["/x"]["get"], {"$unknown": "Fn::Transform AWS::Include: ./a.yaml includes itself"})
        self.assertEqual([d["code"] for d in raw["diagnostics"]], ["CFN-UNEVALUATED"])
        # テンプレート自身を差し込むのも循環
        raw = build({"main.yaml": api_template("./main.yaml")})
        self.assertEqual(api_props(raw)["DefinitionBody"],
                         {"$unknown": "Fn::Transform AWS::Include: ./main.yaml includes itself"})

    def test_unreadable_file(self):
        raw = build({"main.yaml": api_template("./bad.yaml"), "bad.yaml": "a: [1, 2\n", "empty.yaml": ""})
        self.assertEqual(api_props(raw)["DefinitionBody"],
                         {"$unknown": "Fn::Transform AWS::Include: ./bad.yaml cannot be read (ParserError)"})
        raw = build({"main.yaml": api_template("./empty.yaml"), "empty.yaml": ""})
        self.assertEqual(api_props(raw)["DefinitionBody"],
                         {"$unknown": "Fn::Transform AWS::Include: ./empty.yaml cannot be read (ValueError)"})

    def test_url_built_with_sub_is_matched_by_its_last_string(self):
        # !Sub で組み立てた URL（$concat）は、最後の印より後ろの文字列（/specs/api.yaml）で比べる
        raw = build({"main.yaml": api_template('!Sub "https://${Fn.Arn}/specs/api.yaml"'), "specs/api.yaml": OPENAPI_YAML})
        self.assertEqual(raw["diagnostics"], [])
        self.assertIn("/items", api_props(raw)["DefinitionBody"]["paths"])
        self.assertIn("specs/api.yaml を差し込んだ", raw["evaluation"]["assumptions"][0])

    def test_missing_parameters_and_wrong_files(self):
        raw = build({"main.yaml": """
            Resources:
              Q:
                Type: AWS::SQS::Queue
                Properties:
                  A: {Fn::Transform: {Name: AWS::Include}}
                  B: {Fn::Transform: {Name: AWS::Include, Parameters: [x]}}
                  C: {Fn::Transform: {Name: AWS::Include, Parameters: {Location: ./api.txt}}}
                  D: {Fn::Transform: {Name: AWS::Include, Parameters: {Location: ./big.yaml}}}
            """, "api.txt": "a: 1\n", "big.yaml": "a: " + "x" * 200 + "\n"})
        props = next(r for r in raw["resources"] if r["address"] == "Q")["props"]
        self.assertEqual(props["A"], {"$unknown": "Fn::Transform AWS::Include without Parameters.Location"})
        self.assertEqual(props["B"], {"$unknown": "Fn::Transform AWS::Include without Parameters.Location"})
        self.assertEqual(props["C"], {"$unknown": "Fn::Transform AWS::Include: ./api.txt is not a .yaml/.yml/.json/.template file"})
        self.assertEqual(props["D"], {"a": "x" * 200})  # 上限（5 MB）より小さい
        with mock.patch.object(cfn_include, "MAX_INCLUDE_BYTES", 100):
            raw = build({"main.yaml": api_template("./big.yaml"), "big.yaml": "a: " + "x" * 200 + "\n"})
        self.assertEqual(api_props(raw)["DefinitionBody"], {"$unknown": "Fn::Transform AWS::Include: ./big.yaml is larger than 0 MB"})

    def test_absolute_drive_and_unc_locations_are_rejected_without_touching_them(self):
        locs = ("//no-such-host.invalid/share/api.yaml", r"\\no-such-host.invalid\share\api.yaml",
                "C:/Windows/api.yaml", "C:api.yaml", "/etc/api.yaml", "~/api.yaml")
        for loc in locs:
            with self.subTest(loc):
                t0 = time.monotonic()
                raw = build({"main.yaml": api_template("'" + loc + "'")})
                self.assertLess(time.monotonic() - t0, 2.0)  # ネットワークに触らない
                self.assertEqual(api_props(raw)["DefinitionBody"],
                                 {"$unknown": f"Fn::Transform AWS::Include: {loc} is outside the root folder"})

    def test_link_under_root_pointing_outside_is_rejected(self):
        # root の下のジャンクション（Windows）・シンボリックリンクが root の外を指す。URL の読み替えでも相対パスでも読まない
        tmp = Path(tempfile.mkdtemp())
        outside, root, link = tmp / "outside", tmp / "root", tmp / "root" / "link"
        (outside / "specs").mkdir(parents=True)
        root.mkdir()
        (outside / "specs" / "api.yaml").write_text(OPENAPI_YAML, encoding="utf-8")
        try:
            if os.name == "nt":
                import _winapi
                _winapi.CreateJunction(str(outside), str(link))
            else:
                os.symlink(outside, link, target_is_directory=True)
        except (OSError, NotImplementedError) as e:
            self.skipTest(f"リンクを作れない: {e}")
        try:
            for loc in ("s3://bkt/specs/api.yaml", "./link/specs/api.yaml"):
                with self.subTest(loc):
                    write_files(root, {"main.yaml": api_template(loc)})
                    raw = cfn_build.build_raw(root / "main.yaml", root)
                    self.assertEqual(api_props(raw)["DefinitionBody"],
                                     {"$unknown": f"Fn::Transform AWS::Include: {loc} is outside the root folder"})
                    self.assertEqual(raw["evaluation"]["assumptions"], [])
        finally:
            os.rmdir(link) if os.name == "nt" else os.unlink(link)  # リンクだけ外す（先は消さない）
            for p in sorted(tmp.rglob("*"), key=lambda x: len(x.parts), reverse=True):
                p.unlink() if p.is_file() else p.rmdir()
            tmp.rmdir()

    def test_unsupported_forms_are_reported(self):
        raw = build({"main.yaml": """
            Transform:
              - AWS::Serverless-2016-10-31
              - {Name: AWS::Include, Parameters: {Location: ./part.yaml}}
            Resources:
              Fn::Transform: {Name: AWS::Include, Parameters: {Location: ./res.yaml}}
              Q:
                Type: AWS::SQS::Queue
                Properties:
                  Tags:
                    Fn::Transform: {Name: AWS::Include, Parameters: {Location: ./tags.yaml}}
                    Extra: 1
            Outputs:
              Fn::Transform: {Name: AWS::Include, Parameters: {Location: ./out.yaml}}
            """})
        assert_valid(self, raw)
        self.assertEqual([r["address"] for r in raw["resources"]], ["Q"])  # Fn::Transform をリソースの名前として読まない
        self.assertEqual(next(r for r in raw["resources"] if r["address"] == "Q")["props"]["Tags"], {"Extra": 1})
        got = sorted((d["code"], d["level"], d["path"], d["message"]) for d in raw["diagnostics"])
        self.assertEqual(got, [
            ("CFN-UNEVALUATED", "warn", 'Outputs["Fn::Transform"]', "Fn::Transform in the Outputs section is not evaluated"),
            ("CFN-UNEVALUATED", "warn", 'Properties.Tags["Fn::Transform"]', "Fn::Transform next to other keys is not evaluated"),
            ("CFN-UNEVALUATED", "warn", 'Resources["Fn::Transform"]', "Fn::Transform in the Resources section is not evaluated"),
            ("CFN-UNEVALUATED", "warn", "Transform[1]", "Transform AWS::Include at the template level is not evaluated"),
        ])

    def test_t11s_openapi_is_expanded(self):
        # 主セットの T11s（apigw-sfn-crud）: api.openapi.yaml の requestTemplates の ${StateMachine} が active な参照になる
        raw = main_set_raw("T11s")
        self.assertEqual([d for d in raw["diagnostics"] if d["code"] == "CFN-UNEVALUATED"], [])
        got = sorted((r["path"].split(".x-amazon-apigateway-integration.")[1], r["to"]) for r in raw["references"]
                     if r["from"] == "Api" and r["path"].startswith("Properties.DefinitionBody."))
        self.assertEqual(got, [("credentials", "ApiRole"), ("credentials", "ApiRole"),
                               ('requestTemplates["application/json"]', "StateMachine"),
                               ('requestTemplates["application/json"]', "StateMachine")])


if __name__ == "__main__":
    unittest.main()
