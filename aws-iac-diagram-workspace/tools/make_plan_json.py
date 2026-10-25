"""自作 fixture（fixtures/tf/<名前>）と試験用の構成（fixtures/tf-plan/edge）から、Terraform の plan JSON（`terraform show -json` の出力）の fixture を作る。

フェーズ2 の手順4 の開発用の道具（SKILL のスクリプトではない）。**本物の AWS には接続しない。**
  - moto（ローカルの AWS モック。pyproject.toml の依存グループ fixtures。既定の環境には入らない）のサーバーを
    127.0.0.1 で起動し、AWS provider の endpoints をすべてそこへ向ける。fixture の .tf は変えず、%TEMP% の下の作業用のコピーに override のファイル
    （`moto_override.tf`）を置いて、provider の設定を上書きする。
  - 認証情報は偽のもの（AWS_ACCESS_KEY_ID=testing など）だけを渡す。環境変数は必要なものだけから作り直し（AWS_*・
    TF_VAR_* などは引き継がない）、USERPROFILE・HOME・APPDATA を作業用のフォルダにして ~/.aws と Terraform の CLI の
    設定を読ませない。AWS_CONFIG_FILE・AWS_SHARED_CREDENTIALS_FILE も作業用のフォルダの無いファイルにする。
  - ネットワークは `terraform init` の provider とレジストリモジュールの取得だけに使う（three-tier-modules の
    terraform-aws-modules）。
  - `.terraform`・provider のバイナリ・plan のファイルは作業用のフォルダに置き、リポジトリには入れない。
出来た plan JSON から、override で足した provider の設定（endpoints・skip_*・s3_use_path_style）を取り除き、
偽の認証情報・moto の URL・作業用のフォルダの絶対パス・ユーザー名が残っていないかを調べてから、
fixtures/tf-plan/<名前>.json に書く（2スペースのインデント、LF）。

使い方（PowerShell。terraform は winget の Hashicorp.Terraform）:
  uv run --group fixtures python aws-iac-diagram-workspace/tools/make_plan_json.py [名前 ...] [--work <フォルダ>] [--port 5555]
  名前を省くと TARGETS のすべて。three-tier は env/dev.tfvars と env/prod.tfvars の2つ（three-tier.dev.json・
  three-tier.prod.json）。edge は plan JSON の読み方の試験用の小さな構成（sensitive・count 0・モジュール・
  dynamic・.tf.json など）。

終了コード: 0 = すべて作れた、1 = 作れなかったものがある、2 = terraform・moto が無い
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

WS = Path(__file__).resolve().parent.parent
FIXTURES = WS / "fixtures" / "tf"
OUT_DIR = WS / "fixtures" / "tf-plan"

# 出力の名前 → (構成のフォルダ, -var-file)。edge は plan JSON の読み方の試験用の小さな構成（fixtures/tf-plan/edge）
TARGETS = {
    "three-tier.dev": (FIXTURES / "three-tier", "env/dev.tfvars"),
    "three-tier.prod": (FIXTURES / "three-tier", "env/prod.tfvars"),
    "serverless-api": (FIXTURES / "serverless-api", None),
    "vpc-endpoints": (FIXTURES / "vpc-endpoints", None),
    "rag": (FIXTURES / "rag", None),
    "three-tier-modules": (FIXTURES / "three-tier-modules", None),
    "edge": (OUT_DIR / "edge", None),
}

# override で向け直す AWS provider の endpoints（fixture が使うサービス。ほかは AWS_ENDPOINT_URL で同じ先へ）
ENDPOINT_SERVICES = ["acm", "apigateway", "apigatewayv2", "autoscaling", "bedrockagent", "cloudfront", "cloudwatch",
                     "dynamodb", "ec2", "ecr", "ecs", "eks", "elbv2", "events", "iam", "kms", "lambda", "logs",
                     "opensearchserverless", "rds", "route53", "s3", "secretsmanager", "sns", "sqs", "ssm", "sts"]
# override で足した provider の設定のキー（plan JSON の configuration.provider_config から取り除く）
OVERRIDE_KEYS = {"endpoints", "skip_credentials_validation", "skip_requesting_account_id", "skip_metadata_api_check",
                 "skip_region_validation", "s3_use_path_style"}
FAKE_SECRET = "testing"


def override_tf(port: int) -> str:
    lines = ['provider "aws" {',
             "  skip_credentials_validation = true",
             "  skip_requesting_account_id  = true",
             "  skip_metadata_api_check     = true",
             "  skip_region_validation      = true",
             "  s3_use_path_style           = true",
             "  endpoints {"]
    lines += [f'    {s} = "http://127.0.0.1:{port}"' for s in ENDPOINT_SERVICES]
    lines += ["  }", "}", ""]
    return "\n".join(lines)


def clean_env(home: Path, port: int, plugin_cache: Path) -> dict:
    """terraform に渡す環境変数。必要なものだけから作り、本物の認証情報・設定を読ませない。"""
    keep = ("SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "PATH", "TEMP", "TMP", "NUMBER_OF_PROCESSORS",
            "PROCESSOR_ARCHITECTURE", "OS", "LANG")
    env = {k: v for k, v in os.environ.items() if k.upper() in keep}
    for k in ("USERPROFILE", "HOME", "APPDATA", "LOCALAPPDATA"):
        env[k] = str(home)
    env.update({
        "AWS_ACCESS_KEY_ID": FAKE_SECRET, "AWS_SECRET_ACCESS_KEY": FAKE_SECRET, "AWS_SESSION_TOKEN": FAKE_SECRET,
        "AWS_CONFIG_FILE": str(home / "no-aws-config"), "AWS_SHARED_CREDENTIALS_FILE": str(home / "no-aws-credentials"),
        "AWS_EC2_METADATA_DISABLED": "true", "AWS_ENDPOINT_URL": f"http://127.0.0.1:{port}",
        "TF_CLI_CONFIG_FILE": str(home / "terraform.rc"), "TF_PLUGIN_CACHE_DIR": str(plugin_cache),
        "TF_IN_AUTOMATION": "1", "CHECKPOINT_DISABLE": "1",
    })
    return env


def start_moto(port: int) -> subprocess.Popen:
    proc = subprocess.Popen([sys.executable, "-m", "moto.server", "-H", "127.0.0.1", "-p", str(port)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(100):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return proc
        except OSError:
            if proc.poll() is not None:
                break
            time.sleep(0.2)
    proc.kill()
    raise RuntimeError(f"moto のサーバーが起動しませんでした（ポート {port}）")


def run(cmd: list, cwd: Path, env: dict) -> subprocess.CompletedProcess:
    p = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd[:2])} に失敗しました（終了コード {p.returncode}）:\n{p.stderr[-4000:]}")
    return p


def strip_override(plan: dict) -> None:
    """configuration.provider_config（モジュールの中のものも）から、override で足したキーを取り除く。"""
    for conf in (plan.get("configuration") or {}).get("provider_config", {}).values():
        if conf.get("name") == "aws" and isinstance(conf.get("expressions"), dict):
            for k in OVERRIDE_KEYS:
                conf["expressions"].pop(k, None)


def leaks(text: str, work: Path) -> list[str]:
    """plan JSON に残ってはいけない文字列（偽の認証情報、moto の URL、絶対パス、ユーザー名）。"""
    bad = [FAKE_SECRET, "127.0.0.1", "localhost", str(work), work.as_posix(), str(Path.home()), Path.home().as_posix()]
    user = os.environ.get("USERNAME") or os.environ.get("USER")
    if user:
        bad.append(user)
    found = [b for b in bad if b and (b in text or json.dumps(b)[1:-1] in text)]
    return sorted(set(found))


def make_one(name: str, terraform: str, work_root: Path, port: int) -> Path:
    folder, var_file = TARGETS[name]
    work = work_root / name
    if work.exists():
        shutil.rmtree(work)
    cfg = work / "cfg"
    shutil.copytree(folder, cfg)
    (cfg / "moto_override.tf").write_text(override_tf(port), encoding="utf-8", newline="\n")
    home = work / "home"
    home.mkdir()
    (home / "terraform.rc").write_text("", encoding="utf-8")
    plugin_cache = work_root / ".plugin-cache"
    plugin_cache.mkdir(exist_ok=True)
    env = clean_env(home, port, plugin_cache)
    run([terraform, "init", "-input=false", "-no-color"], cfg, env)
    plan_cmd = [terraform, "plan", "-input=false", "-no-color", "-lock=false", "-out=plan.tfplan"]
    if var_file:
        plan_cmd.append(f"-var-file={var_file}")
    run(plan_cmd, cfg, env)
    shown = run([terraform, "show", "-json", "-no-color", "plan.tfplan"], cfg, env).stdout
    plan = json.loads(shown)
    strip_override(plan)
    text = json.dumps(plan, ensure_ascii=False, indent=2) + "\n"
    found = leaks(text, work)
    if found:
        raise RuntimeError(f"plan JSON に残してはいけない文字列があります: {', '.join(found)}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{name}.json"
    out.write_text(text, encoding="utf-8", newline="\n")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="自作 fixture から plan JSON の fixture を作る（moto を使い、AWS に接続しない）")
    ap.add_argument("names", nargs="*", metavar="名前", help=f"作るもの（{', '.join(TARGETS)}）")
    ap.add_argument("--work", type=Path, default=Path(tempfile.gettempdir()) / "tfp")
    ap.add_argument("--port", type=int, default=5555)
    ap.add_argument("--terraform", default=shutil.which("terraform"))
    a = ap.parse_args(argv)
    names = a.names or list(TARGETS)
    unknown = [n for n in names if n not in TARGETS]
    if unknown:
        print(f"知らない名前です: {', '.join(unknown)}（{', '.join(TARGETS)}）", file=sys.stderr)
        return 2
    if not a.terraform:
        print("terraform が見つかりません（winget install --id Hashicorp.Terraform -e）", file=sys.stderr)
        return 2
    try:
        import moto  # noqa: F401
    except ImportError:
        print("moto がありません（uv run --group fixtures python ... で実行してください）", file=sys.stderr)
        return 2
    a.work.mkdir(parents=True, exist_ok=True)
    version = subprocess.run([a.terraform, "version", "-json"], capture_output=True, text=True).stdout
    print(f"terraform {json.loads(version)['terraform_version']}")
    proc = start_moto(a.port)
    failed = 0
    try:
        for n in names:
            try:
                out = make_one(n, a.terraform, a.work, a.port)
                print(f"ok  {n}: {out.relative_to(WS).as_posix()}")
            except RuntimeError as e:
                failed += 1
                print(f"NG  {n}: {e}", file=sys.stderr)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
