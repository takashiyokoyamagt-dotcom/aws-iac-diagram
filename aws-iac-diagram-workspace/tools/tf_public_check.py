# /// script
# requires-python = ">=3.12"
# dependencies = ["python-hcl2==8.1.4", "PyYAML==6.0.3", "jsonschema==4.26.0"]
# ///
"""TF アダプタの公開サンプルでの確認（フェーズ2 の手順5）。tests/integration/terraform/test_public_samples.py も同じ関数を使う。

1. 読めること: 公開サンプル（fixtures/public）の TF を TF アダプタで読み、例外が出ない・raw IR が検査（スキーマと
   参照の整合）を通る・error の診断が 0 であることを調べる。
   - 既定: T01〜T20、P01〜P04 のルート（survey_public.py の一覧。52 フォルダ）
   - `--all`: `.tf` のあるフォルダすべて（モジュールの中身・examples・wrappers を含む。205 フォルダ）
2. TF／SAM の対（T01、T05、T06、T07、T11。SELECTION.md の 3 の 3）: TF アダプタと CFN アダプタの raw IR の
   リソースの型の多重集合を、下の「正規化」のあとで比べ、違いを PAIR_EXPECTED（理由つき）と突き合わせる。
   `--pairs` でこの比較の結果を表で出す。

正規化（対の比較だけに使う。最小限）:
  - TF: `data` ブロックと、aws プロバイダ以外のリソース（`random_*`、`null_*`、`time_*` など。CFN に対応する物が無い）を
    除く。`enabled: false` のものも除く。型は TF_TO_CFN で CFN の型名にする（表に無い型は失敗にして、足し忘れを防ぐ）。
    CFN でプロパティとして埋め込まれるもの（`aws_cloudwatch_event_target` など）は「<親の型>#<プロパティ>」という
    型名にする。
  - CFN: SAM の型を SAM_TO_CFN で CFN の型名にする（`AWS::Serverless::Function` → `AWS::Lambda::Function` など。
    SAM が変換のときに足す IAM ロール・Subscription・Permission などは、CFN アダプタが展開しない（暗黙の API を除く。
    ir-schema.md の 7.2）ので、CFN の側には無い）。
  - どちらも型のカウンタ（Counter）にして、TF だけにあるもの（only_tf）と CFN だけにあるもの（only_cfn）を出す。
  - ノードの辺（from の型、to の型、kind）の多重集合の比較は、図の形（正規化）を作るフェーズ3 の仕事（SELECTION.md の
    3 の 3 は正規化後の IR が前提）。ここではリソースの型だけを比べる。

使い方:
  uv run python aws-iac-diagram-workspace/tools/tf_public_check.py [--all] [--jobs N] [--pairs] [--out <report.json>]

終了コード: 0 = すべて通った、1 = 失敗がある（読めない・検査を通らない・error の診断・対の違いが表と合わない）

注意（対の比較）: `AWS::Events::Rule#Targets` のように「プロパティとして埋め込まれる型」は、CFN の raw IR にはリソース単位の型しか無いので、
TF 側にしか現れない。これらの `only_tf` は TF アダプタの数を固定するだけで、SAM 側の取りこぼしは見つけられない。
対の突き合わせとして効くのは、`PAIR_COMMON`（両側にある型）と、独立したリソースの型の違いである。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
WS = TOOLS.parent
PUB = WS / "fixtures" / "public"
SCRIPTS = WS.parent / "skills" / "aws-iac-diagram" / "scripts"
for p in (str(SCRIPTS), str(TOOLS)):
    if p not in sys.path:
        sys.path.insert(0, p)

import survey_public  # noqa: E402
import validate_ir  # noqa: E402
from aws_iac_diagram.adapters.cloudformation import build as cfn_build  # noqa: E402
from aws_iac_diagram.adapters.terraform import build as tf_build  # noqa: E402


# --------------------------------------------------------------------------------------------------------------
# 1. 読めること
# --------------------------------------------------------------------------------------------------------------

def root_folders() -> list[str]:
    """T01〜T20、P01〜P04 の TF のルート（fixtures/public からの相対パス）。"""
    roots = [r for fmt, rs in survey_public.SAMPLES.values() if fmt == "tf" for r in rs]
    return roots + survey_public.t20_roots()


def all_folders() -> list[str]:
    """`.tf` を持つフォルダすべて（モジュールの中身・examples などを含む）。"""
    return sorted({p.parent.relative_to(PUB).as_posix() for p in PUB.rglob("*.tf")})


def check_folder(rel: str) -> dict:
    """1フォルダを TF アダプタで読み、結果の要約を返す（ProcessPoolExecutor から呼べるように top-level に置く）。"""
    out = {"folder": rel, "resources": 0, "levels": {}, "problems": []}
    try:
        raw = tf_build.build_raw(PUB / rel, WS)
    except Exception as e:  # noqa: BLE001
        out["problems"].append(f"exception {type(e).__name__}: {e}")
        return out
    out["resources"] = len(raw["resources"])
    out["levels"] = dict(Counter(d["level"] for d in raw["diagnostics"]))
    # validate_ir.py <ファイル> と同じ検査（スキーマ、参照の整合、出力の形 C5）を、書き出したファイルにかける
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "raw.json"
        f.write_text(tf_build.dump(raw), encoding="utf-8", newline="\n")
        errs = validate_ir.validate_file(f, False, set())
    if errs:
        out["problems"].append(f"raw IR is invalid: {errs[:3]}")
    for d in raw["diagnostics"]:
        if d["level"] == "error":
            out["problems"].append(f"error diagnostic {d['code']}: {d.get('message', '')}")
    return out


def run_folders(rels: list[str], jobs: int = 1) -> dict:
    t0 = time.time()
    if jobs > 1:
        with ProcessPoolExecutor(max_workers=jobs) as ex:
            results = list(ex.map(check_folder, rels, chunksize=4))
    else:
        results = [check_folder(r) for r in rels]
    levels: Counter = Counter()
    for r in results:
        levels.update(r["levels"])
    return {
        "folders": len(results),
        "resources": sum(r["resources"] for r in results),
        "diagnostics": {k: levels.get(k, 0) for k in ("error", "warn", "info")},
        "failures": [{"folder": r["folder"], "problems": r["problems"]} for r in results if r["problems"]],
        "seconds": round(time.time() - t0, 1),
    }


# --------------------------------------------------------------------------------------------------------------
# 2. TF／SAM の対
# --------------------------------------------------------------------------------------------------------------

# 対（TF の側のフォルダ、SAM の側のテンプレート。fixtures/public からの相対パス）。survey_public.SAMPLES から引く
PAIRS = {"T01": "T01s", "T05": "T05s", "T06": "T06s", "T07": "T07s", "T11": "T11s"}

# SAM の型 → CFN の型（変換の後の型）。raw IR の CFN の側は SAM の型のまま
SAM_TO_CFN = {
    "AWS::Serverless::Function": "AWS::Lambda::Function",
    "AWS::Serverless::Api": "AWS::ApiGateway::RestApi",
    "AWS::Serverless::HttpApi": "AWS::ApiGatewayV2::Api",
    "AWS::Serverless::SimpleTable": "AWS::DynamoDB::Table",
    "AWS::Serverless::StateMachine": "AWS::StepFunctions::StateMachine",
}

# TF の型 → CFN の型。「#」の付くものは、CFN では親のリソースのプロパティとして埋め込まれ、独立したリソースにならない
TF_TO_CFN = {
    "aws_api_gateway_deployment": "AWS::ApiGateway::Deployment",
    "aws_api_gateway_integration": "AWS::ApiGateway::Method#Integration",
    "aws_api_gateway_integration_response": "AWS::ApiGateway::Method#Integration.IntegrationResponses",
    "aws_api_gateway_method": "AWS::ApiGateway::Method",
    "aws_api_gateway_method_response": "AWS::ApiGateway::Method#MethodResponses",
    "aws_api_gateway_resource": "AWS::ApiGateway::Resource",
    "aws_api_gateway_rest_api": "AWS::ApiGateway::RestApi",
    "aws_api_gateway_stage": "AWS::ApiGateway::Stage",
    "aws_apigatewayv2_api": "AWS::ApiGatewayV2::Api",
    "aws_apigatewayv2_integration": "AWS::ApiGatewayV2::Integration",
    "aws_apigatewayv2_route": "AWS::ApiGatewayV2::Route",
    "aws_apigatewayv2_stage": "AWS::ApiGatewayV2::Stage",
    "aws_cloudwatch_event_rule": "AWS::Events::Rule",
    "aws_cloudwatch_event_target": "AWS::Events::Rule#Targets",
    "aws_cloudwatch_log_group": "AWS::Logs::LogGroup",
    "aws_dynamodb_table": "AWS::DynamoDB::Table",
    "aws_iam_policy": "AWS::IAM::ManagedPolicy",
    "aws_iam_role": "AWS::IAM::Role",
    "aws_iam_role_policy": "AWS::IAM::Role#Policies",
    "aws_iam_role_policy_attachment": "AWS::IAM::Role#ManagedPolicyArns",
    "aws_lambda_function": "AWS::Lambda::Function",
    "aws_lambda_permission": "AWS::Lambda::Permission",
    "aws_s3_bucket": "AWS::S3::Bucket",
    "aws_s3_bucket_public_access_block": "AWS::S3::Bucket#PublicAccessBlockConfiguration",
    "aws_s3_object": "AWS::S3::Object",  # CFN に対応するリソースは無い（コードのアップロード）
    "aws_sfn_state_machine": "AWS::StepFunctions::StateMachine",
    "aws_sns_topic": "AWS::SNS::Topic",
    "aws_sns_topic_policy": "AWS::SNS::TopicPolicy",
    "aws_sns_topic_subscription": "AWS::SNS::Subscription",
    "aws_sqs_queue": "AWS::SQS::Queue",
    "aws_sqs_queue_policy": "AWS::SQS::QueuePolicy",
}

# 対ごとの、正規化のあとに残る違い（理由つき）。{対の ID: {"only_tf": {型: (件数, 理由)}, "only_cfn": {…}}}。
# ゆるい許容ではなく、型と件数を1つずつ書く。増えても減っても、このテーブルと合わなければ失敗する。
EMBEDDED = "CFN ではプロパティとして埋め込まれ、独立したリソースにならない"
SAM_ROLE = "SAM が変換のときに暗黙に作る IAM ロール（CFN アダプタは展開しない）"
SAM_EVENT = "SAM の Events から暗黙に作られる（CFN アダプタは展開しない）"
PAIR_EXPECTED: dict[str, dict[str, dict[str, tuple[int, str]]]] = {
    "T01": {
        "only_tf": {"AWS::Events::Rule#Targets": (1, EMBEDDED + "（SAM 版は Rule の Targets）")},
        "only_cfn": {},
    },
    "T05": {
        "only_tf": {
            "AWS::IAM::Role": (1, SAM_ROLE),
            "AWS::IAM::ManagedPolicy": (1, "SAM 版は Policies の SQSSendMessagePolicy（ロールに埋め込まれる）"),
            "AWS::IAM::Role#ManagedPolicyArns": (2, "SAM 版は暗黙のロールに AWSLambdaBasicExecutionRole が付く"),
        },
        "only_cfn": {},
    },
    "T06": {
        "only_tf": {
            "AWS::Events::Rule#Targets": (1, EMBEDDED),
            "AWS::IAM::Role": (1, SAM_ROLE),
            "AWS::IAM::Role#ManagedPolicyArns": (1, "SAM 版は暗黙のロールに AWSLambdaBasicExecutionRole が付く"),
            "AWS::Lambda::Permission": (1, SAM_EVENT + "（SNS からの呼び出しの許可）"),
            "AWS::SNS::Subscription": (1, SAM_EVENT + "（Events の Type: SNS）"),
        },
        "only_cfn": {},
    },
    "T07": {
        # TF 版は HTTP API（API Gateway v2）、SAM 版は REST API（Events の Type: Api が作る暗黙の ServerlessRestApi）。
        # 同じ「API → Lambda → DynamoDB」でも、作者が別なので API の種類が違う（構成そのものの違い）
        "only_tf": {
            "AWS::ApiGatewayV2::Api": (1, "TF 版は HTTP API。SAM 版は REST API（only_cfn の RestApi）"),
            "AWS::ApiGatewayV2::Integration": (1, "同上（HTTP API の統合）"),
            "AWS::ApiGatewayV2::Route": (1, "同上（HTTP API のルート）"),
            "AWS::ApiGatewayV2::Stage": (1, "同上（HTTP API のステージ。REST API のステージは SAM が暗黙に作るが展開しない）"),
            "AWS::IAM::Role": (1, SAM_ROLE),
            "AWS::IAM::ManagedPolicy": (1, "SAM 版は Policies の DynamoDBCrudPolicy（暗黙のロールに埋め込まれる）"),
            "AWS::IAM::Role#ManagedPolicyArns": (1, "TF 版は Lambda のロールに管理ポリシーを付ける。SAM 版は Policies として暗黙のロールに入る"),
            "AWS::Lambda::Permission": (1, SAM_EVENT + "（API Gateway からの呼び出しの許可）"),
            "AWS::Logs::LogGroup": (2, "TF 版だけの Lambda と API のログ。SAM 版は作らない"),
            "AWS::S3::Bucket": (1, "TF 版は Lambda のコードの置き場を自分で作る。SAM 版は CodeUri を sam package が上げる"),
            "AWS::S3::Bucket#PublicAccessBlockConfiguration": (1, "同上（コードの置き場の設定）"),
            "AWS::S3::Object": (1, "同上（コードのアップロード）"),
        },
        "only_cfn": {
            "AWS::ApiGateway::RestApi": (1, "SAM 版の暗黙の REST API（ServerlessRestApi）。TF 版は HTTP API"),
        },
    },
    "T11": {
        # REST API のメソッド・統合・応答は、SAM 版では OpenAPI の定義（DefinitionBody の AWS::Include）の中にあり、
        # CFN アダプタはその外部ファイルを展開しない。ステージとデプロイは SAM が暗黙に作る
        "only_tf": {
            "AWS::ApiGateway::Deployment": (1, "SAM の Api が暗黙に作る（CFN アダプタは展開しない）"),
            "AWS::ApiGateway::Stage": (2, "同上（TF 版は Prod と Stage の2つ。SAM は暗黙に作り、CFN アダプタは OpenAPI を展開しない）"),
            "AWS::ApiGateway::Resource": (1, "SAM 版は OpenAPI の定義（外部ファイル）の中のパス"),
            "AWS::ApiGateway::Method": (2, "同上（メソッド）"),
            "AWS::ApiGateway::Method#Integration": (2, "同上（統合）"),
            "AWS::ApiGateway::Method#Integration.IntegrationResponses": (4, "同上（統合の応答）"),
            "AWS::ApiGateway::Method#MethodResponses": (4, "同上（メソッドの応答）"),
            "AWS::IAM::Role": (1, "SAM の StateMachine が暗黙に作るロール（CFN アダプタは展開しない）"),
            "AWS::IAM::Role#Policies": (1, "SAM 版の ApiRole の Policies（ロールに埋め込まれる）"),
            "AWS::IAM::Role#ManagedPolicyArns": (3, "TF 版は API のロールに2つ、ステートマシンのロールに1つ（X-Ray）を付ける。"
                                                  "SAM 版の API のロールには無く、ステートマシンのものは Tracing が暗黙に付ける"),
        },
        "only_cfn": {},
    },
}


def tf_types(raw: dict) -> Counter:
    """TF の raw IR のリソースの型を、CFN の型名のカウンタにする（正規化。モジュールの docstring）。"""
    out: Counter = Counter()
    unmapped = set()
    for r in raw["resources"]:
        if re.match(r"^(?:module\.[^.\[]+(?:\[[^\]]*\])?\.)*data\.", r["address"]) or r["type"].split("_", 1)[0] != "aws" or not r.get("enabled", True):
            continue
        if r["type"] not in TF_TO_CFN:
            unmapped.add(r["type"])
            continue
        out[TF_TO_CFN[r["type"]]] += 1
    if unmapped:
        raise KeyError(f"TF_TO_CFN に無い型: {sorted(unmapped)}")
    return out


def cfn_types(raw: dict) -> Counter:
    """CFN（SAM を含む）の raw IR のリソースの型を、変換の後の CFN の型名のカウンタにする。"""
    return Counter(SAM_TO_CFN.get(r["type"], r["type"]) for r in raw["resources"] if r.get("enabled", True))


def compare_pair(pair_id: str) -> dict:
    """対の TF 版と SAM 版を読み、型の多重集合の違いを返す。"""
    tf_raw = tf_build.build_raw(PUB / survey_public.SAMPLES[pair_id][1][0], WS)
    cfn_raw = cfn_build.build_raw(PUB / survey_public.SAMPLES[PAIRS[pair_id]][1][0], WS)
    a, b = tf_types(tf_raw), cfn_types(cfn_raw)
    return {
        "pair": f"{pair_id}+{PAIRS[pair_id]}",
        "tf": dict(sorted(a.items())), "cfn": dict(sorted(b.items())),
        "common": dict(sorted((a & b).items())),
        "only_tf": dict(sorted((a - b).items())), "only_cfn": dict(sorted((b - a).items())),
        "diagnostics": {"tf": dict(Counter(d["level"] for d in tf_raw["diagnostics"])),
                        "cfn": dict(Counter(d["level"] for d in cfn_raw["diagnostics"]))},
    }


def pair_problems(pair_id: str, result: dict) -> list[str]:
    """compare_pair の結果を PAIR_EXPECTED と突き合わせ、合わない点を返す。"""
    exp = PAIR_EXPECTED[pair_id]
    probs = []
    for side in ("only_tf", "only_cfn"):
        want = {t: n for t, (n, _) in exp[side].items()}
        if want != result[side]:
            probs.append(f"{result['pair']} {side}: expected {want}, got {result[side]}")
    return probs


def run_pairs() -> dict:
    results, problems = [], []
    for pid in PAIRS:
        r = compare_pair(pid)
        results.append(r)
        problems += pair_problems(pid, r)
    return {"pairs": results, "problems": problems}


# --------------------------------------------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="TF アダプタを公開サンプルで確認する（フェーズ2 の手順5）")
    ap.add_argument("--all", action="store_true", help=".tf のあるフォルダすべてを読む（既定は T01〜T20、P01〜P04 のルート）")
    ap.add_argument("--jobs", type=int, default=1, help="並列に読むプロセスの数")
    ap.add_argument("--pairs", action="store_true", help="TF／SAM の対の比較を表で出す")
    ap.add_argument("--out", type=Path, help="結果の JSON を書くファイル")
    a = ap.parse_args(argv)

    folders = all_folders() if a.all else root_folders()
    res = run_folders(folders, a.jobs)
    print(f"{'NG' if res['failures'] else 'OK'} folders={res['folders']} resources={res['resources']} "
          f"diagnostics={res['diagnostics']} ({res['seconds']} s)")
    for f in res["failures"]:
        print(f"  NG {f['folder']}: {f['problems']}")

    pairs = run_pairs()
    print(f"{'NG' if pairs['problems'] else 'OK'} pairs={len(pairs['pairs'])}")
    for p in pairs["problems"]:
        print(f"  NG {p}")
    if a.pairs:
        for r in pairs["pairs"]:
            print(f"  {r['pair']}: common={sum(r['common'].values())} only_tf={sum(r['only_tf'].values())} "
                  f"only_cfn={sum(r['only_cfn'].values())}")
            for side in ("only_tf", "only_cfn"):
                for t, n in r[side].items():
                    print(f"    {side} {t} x{n}")
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        report = {"folders": {k: v for k, v in res.items() if k != "seconds"}, "pairs": pairs}  # 時間は入れない（毎回同じバイト列にする）
        a.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8", newline="\n")
    return 1 if res["failures"] or pairs["problems"] else 0


if __name__ == "__main__":
    sys.exit(main())
