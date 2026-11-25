# /// script
# requires-python = ">=3.12"
# dependencies = ["python-hcl2==8.1.4", "PyYAML==6.0.3", "jsonschema==4.26.0"]
# ///
"""IaC（Terraform・CloudFormation）から図まで一度に進める（フェーズ 6）。中では adapt_*.py → normalize_ir.py → diagram.py を順に動かす。

使い方:
  uv run scripts/make_diagram.py --input <入力> --out-dir <フォルダ> [アダプタの引数...] [--no-external]
  入力の見分け方: フォルダに *.tf → Terraform。plan JSON（`terraform show -json`）→ Terraform の plan。
                  フォルダに manifest.json（cdk.out）か、YAML／JSON のテンプレート → CloudFormation。
  Terraform: --var-file、--var、--plan、--workspace、--redact-var。CloudFormation: --param、--param-file。

環境が複数ある入力（値の無い変数があり、自動では読まれない *.tfvars がある）で変数を渡さないときは、図を作らずに
result.json に確認の質問（`questions`）を書いて終わる（終了コード 0。CRITERIA 6.5）。

書くもの（--out-dir）: raw.json、ir.json、diagram/（.drawio・.mmd・.png・coverage.md・result.json）、result.json（全体のまとめ）。

終了コード: 0 = 成功（スキップや確認の質問があっても）、1 = 書けたが検証で問題がある、2 = 実行エラー（どの段階かは result.json）
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from aws_iac_diagram.adapters.terraform import build as tf_build  # noqa: E402

NAME = re.compile(r"[^a-z0-9]+")


def detect(path: Path) -> str:
    """"tf"／"tf-plan"／"cfn"。分からなければ ValueError。"""
    if path.is_dir():
        if any(path.glob("*.tf")):
            return "tf"
        if (path / "manifest.json").is_file():
            return "cfn"
        raise ValueError(f"フォルダに *.tf も manifest.json（cdk.out）もない（テンプレートはファイルを渡す）: {path}")
    if not path.is_file():
        raise ValueError(f"入力が無い: {path}")
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    suffix = path.suffix.lower()
    if suffix == ".json" or (suffix == ".template" and text.lstrip().startswith("{")):
        try:
            doc = json.loads(text)
        except json.JSONDecodeError as ex:
            raise ValueError(f"JSON として読めない: {ex}") from ex
        if isinstance(doc, dict) and "format_version" in doc and ("planned_values" in doc or "configuration" in doc):
            return "tf-plan"
        if isinstance(doc, dict) and "Resources" in doc:
            return "cfn"
        raise ValueError("JSON だが、plan JSON でも CloudFormation のテンプレートでもない")
    if suffix in (".yaml", ".yml", ".template") and re.search(r"^Resources\s*:", text, re.M):
        return "cfn"
    raise ValueError(f"形式が分からない: {path}")


def ir_name(path: Path) -> str:
    base = path.name if path.is_dir() else path.stem
    if base in ("template", "cdk.out", "main", "plan") or not base:
        base = path.resolve().parent.name if not path.is_dir() else base
    return NAME.sub("-", base.lower()).strip("-") or "diagram"


def tf_question(input_dir: Path, raw_path: Path) -> dict | None:
    """値の無い変数があり、自動では読まれない *.tfvars があれば、どれを使うかの質問。"""
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    missing = sorted(k for k, v in raw.get("evaluation", {}).get("vars", {}).items() if v.get("source") is None)
    # 下のフォルダに *.tf があれば、それは別のルート（例など）の変数なので候補にしない
    candidates = [p.relative_to(input_dir).as_posix() for p in tf_build.var_file_candidates(input_dir)
                  if p.parent == input_dir or not any(p.parent.glob("*.tf"))]
    if not missing or not candidates:
        return None
    return {"id": "tf-var-file", "question": "どの環境の変数のファイルで図を作りますか（--var-file で渡す）",
            "variables_without_value": missing, "choices": candidates}


def run(step: str, cmd: list[str], steps: dict) -> int:
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    p = subprocess.run([sys.executable, *cmd], capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    steps[step] = {"exit": p.returncode, "stderr": p.stderr.strip()[-1500:]}
    if p.stderr.strip():
        print(f"[{step}] {p.stderr.strip()[-1500:]}", file=sys.stderr)
    return p.returncode


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="IaC から図まで一度に進める")
    ap.add_argument("--input", required=True, type=Path)
    ap.add_argument("--out-dir", required=True, type=Path)
    ap.add_argument("--name", default=None, help="図の名前（小文字・数字・-）。省略すると入力の名前から作る")
    ap.add_argument("--no-external", action="store_true", help="PNG の書き出しと mmdc の描画確認をしない")
    a, rest = ap.parse_known_args(argv)
    result: dict = {"input": str(a.input), "steps": {}, "questions": []}
    out = a.out_dir

    def finish(code: int) -> int:
        result["exit"] = code
        try:
            out.mkdir(parents=True, exist_ok=True)
            (out / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                                             encoding="utf-8", newline="\n")
        except OSError as ex:
            print(f"result.json を書けません: {ex}", file=sys.stderr)
            return 2
        return code

    try:
        fmt = detect(a.input)
        out.mkdir(parents=True, exist_ok=True)
        # 前回の出力を消す（今回の段階が失敗したのに、古い raw.json・ir.json・図を今回の結果として読まないように）。
        # 消すのはこのスクリプトが書く名前だけ
        for old in ("raw.json", "ir.json", "result.json"):
            (out / old).unlink(missing_ok=True)
        if (out / "diagram").is_dir():
            for f in (out / "diagram").iterdir():
                if f.is_file() and (f.suffix in (".drawio", ".mmd", ".png") or f.name in ("coverage.md", "result.json")):
                    f.unlink()
    except (ValueError, OSError) as ex:
        result["error"] = str(ex)
        print(f"書けません: {ex}", file=sys.stderr)
        return finish(2)
    result["format"] = fmt
    name = a.name or ir_name(a.input)
    raw, ir = out / "raw.json", out / "ir.json"
    if fmt == "cfn":
        code = run("adapt", [str(HERE / "adapt_cfn.py"), "--input", str(a.input), "--out", str(raw), *rest], result["steps"])
    else:
        code = run("adapt", [str(HERE / "adapt_tf.py"), "--input", str(a.input), "--out", str(raw), *rest], result["steps"])
    if code == 2 or not raw.is_file():
        return finish(2)
    if fmt == "tf" and not any(x in rest for x in ("--var-file", "--var", "--plan")):
        q = tf_question(a.input, raw)
        if q is not None:  # どの環境の図かが決まらないので、図は作らない
            result["questions"].append(q)
            print(f"確認が要ります: {q['question']}: {', '.join(q['choices'])}", file=sys.stderr)
            return finish(0)
    worst = code
    code = run("normalize", [str(HERE / "normalize_ir.py"), "--input", str(raw), "--out", str(ir), "--name", name], result["steps"])
    if code == 2 or not ir.is_file():
        return finish(2)
    worst = max(worst, code)
    cmd = [str(HERE / "diagram.py"), "--input", str(ir), "--out-dir", str(out / "diagram")]
    code = run("diagram", cmd + (["--no-external"] if a.no_external else []), result["steps"])
    if code == 2:
        return finish(2)
    worst = max(worst, code)
    try:
        result["diagram"] = json.loads((out / "diagram" / "result.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return finish(2)
    return finish(worst)


if __name__ == "__main__":
    raise SystemExit(main())
