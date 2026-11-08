"""Fn::Transform の AWS::Include: 手元のファイル（YAML・JSON）を読んで、その場に差し込む（CloudFormation と同じ考え方）。

差し込んだ中身は、テンプレートの値としてそのまま評価する（中の Ref・Fn::GetAtt・Fn::Sub は、ふつうの参照になる）。
SAM の `AWS::Serverless::Api` の `DefinitionBody`（OpenAPI）が主な使い道（T11s）。

CloudFormation より緩い点（ir-schema の 7.4）: Location に手元の相対パスを書けるのは `aws cloudformation package`・`sam` と同じ
扱い（CloudFormation 自身は S3 の URL だけ）。差し込むファイルの中の YAML の短縮タグ（!Ref など）も読む（CloudFormation は不可）。
"""
from __future__ import annotations

from pathlib import Path

import yaml

from aws_iac_diagram.adapters.cloudformation.loader import load_snippet
from aws_iac_diagram.adapters.cloudformation.model import TEMPLATE_SUFFIXES
from aws_iac_diagram.core.ir_raw import join_path

INCLUDE = "AWS::Include"
MAX_INCLUDE_BYTES = 5 * 1024 * 1024  # 差し込むファイルの大きさの上限
SECTIONS = ("Resources", "Outputs", "Parameters", "Conditions", "Mappings")


def unsupported_forms(template: dict) -> tuple[dict, list[tuple[str, str]]]:
    """展開しない Fn::Transform の書き方を取り除く（ir-schema の 7.4）。(取り除いたテンプレート, [(path, 診断の文)])。

    - 節の中のキーとしての Fn::Transform（`Resources: {Fn::Transform: …}` のように節の中身を差し込むもの）は、リソース・出力などの
      名前として読まない（CFN-MALFORMED-RESOURCE にしない）。
    - 最上位の `Transform` の AWS::Include（テンプレートの一部を差し込むもの）は、読み込みはそのままで診断だけ出す。
    """
    found = []
    out = dict(template)
    for section in SECTIONS:
        body = template.get(section)
        if isinstance(body, dict) and "Fn::Transform" in body:
            out[section] = {k: v for k, v in body.items() if k != "Fn::Transform"}
            found.append((join_path(section, "Fn::Transform"), f"Fn::Transform in the {section} section is not evaluated"))
    top = template.get("Transform")
    for i, t in enumerate(top if isinstance(top, list) else [top]):
        if isinstance(t, dict) and t.get("Name") == INCLUDE:
            found.append((join_path("Transform", i) if isinstance(top, list) else "Transform",
                          f"Transform {INCLUDE} at the template level is not evaluated"))
    return out, found


class IncludeMixin:
    """Fn::Transform（Name が AWS::Include）の展開。Evaluator.transform を上書きする（StackEval の継承の順で Evaluator の前）。

    状態（includes。展開している途中のファイル）は StackEval.__init__ に書いてある。Location の扱い（ir-schema の 7.4）:
    - 相対パス（`./api.yaml`）は、いま読んでいるファイル（テンプレートか、差し込み中のファイル）のフォルダからのパス。
    - URL（`s3://…`、`https://…`）は、ネストスタックの TemplateURL と同じく、パスの末尾の要素が root の下のファイルと
      最も多く一致するものに読み替える。どちらも `evaluation.assumptions` に、差し込んだ位置とファイルを書く。
    - どちらも `Context.inside_root` で root のフォルダの中に限る（絶対パス・ドライブ・UNC・`..`・リンクで外に出るものは読まない）。
    - 見つからない・root の外・拡張子が違う・大きすぎる・読めない・自分を含む（循環）ときは、評価しない値（`$unknown`、CFN-UNEVALUATED）。
    """

    def transform(self, arg, node, path: str):
        if not (isinstance(arg, dict) and arg.get("Name") == INCLUDE):
            return super().transform(arg, node, path)
        params = arg.get("Parameters")
        if not isinstance(params, dict) or "Location" not in params:
            return self.unknown(node, path, f"Fn::Transform {INCLUDE} without Parameters.Location")
        loc = self.eval(params["Location"], path)
        built = isinstance(loc, dict) and "$concat" in loc and isinstance(loc["$concat"][-1], str)
        if built:
            loc = loc["$concat"][-1]  # 組み立てた URL は、最後の印より後ろの文字列（パス）で比べる（URL として扱う）
        if not isinstance(loc, str) or not loc:
            return self.unknown(node, path, f"Fn::Transform {INCLUDE} with a computed Location")
        file, reason = self._include_file(loc, built)
        if file is None:
            return self.unknown(node, path, f"Fn::Transform {INCLUDE}: {loc} {reason}")
        try:
            content = load_snippet(file)
        except (OSError, ValueError, yaml.YAMLError) as e:
            return self.unknown(node, path, f"Fn::Transform {INCLUDE}: {loc} cannot be read ({type(e).__name__})")
        where = f"{self.current}.{path}" if self.current else path
        self.ctx.assumptions.append(f"{where}: {INCLUDE} の Location {loc} に {self.ctx.rel(file)} を差し込んだ")
        self.includes.append(file)
        try:
            return self.eval(content, path)
        finally:
            self.includes.pop()

    def _include_file(self, loc: str, built: bool = False) -> tuple[Path | None, str]:
        """Location → 読むファイル（resolve 済み）。読めなければ (None, 理由)。built は組み立てた URL の後ろの部分。"""
        if not built and "://" not in loc and not loc.startswith("s3:"):
            base = self.includes[-1].parent if self.includes else self.path.parent
            file = self.ctx.inside_root(base, loc)
        else:
            hit = self.ctx.match_url(loc)
            if hit is None:
                return None, "is not found locally"
            file = self.ctx.inside_root(self.ctx.root_dir, hit)  # リンク・ジャンクションで root の外を指すファイルを弾く
        if file is None:
            return None, "is outside the root folder"
        if file.suffix.lower() not in TEMPLATE_SUFFIXES:
            return None, f"is not a {'/'.join(TEMPLATE_SUFFIXES)} file"
        if not file.is_file():
            return None, "is not found locally"
        if file.stat().st_size > MAX_INCLUDE_BYTES:
            return None, f"is larger than {MAX_INCLUDE_BYTES // (1024 * 1024)} MB"
        if file in self.includes or file in self.ctx.active_files or file == self.path.resolve():
            return None, "includes itself"
        return file, ""
