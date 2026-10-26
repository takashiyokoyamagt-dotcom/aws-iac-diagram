"""ネストスタック: 子テンプレートの場所（TemplateURL の読み替えを含む）、展開、出力のたどり方。"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from aws_iac_diagram.adapters.cloudformation.conditions import weaker
from aws_iac_diagram.adapters.cloudformation.loader import load_template
from aws_iac_diagram.adapters.cloudformation.marks import prepend_through, res_with_fn
from aws_iac_diagram.adapters.cloudformation.model import IN_PROGRESS, NO_VALUE
from aws_iac_diagram.core import ir_raw


class NestedMixin:
    """ネストスタック（AWS::CloudFormation::Stack）: 子テンプレートを探して展開し、出力をたどる。

    状態（children・ctx）は StackEval.__init__ に書いてある。stack_output の super() は、StackEval の継承の順（Evaluator が後）で
    Evaluator.stack_output（読めない子は黒箱）になる。子のスタックは type(self)(…) で作る（StackEval は継承されない）。
    """

    def stack_output(self, res: str, output: str, path: str):
        child = self.child(res)
        if child is IN_PROGRESS:
            return self.unknown([], path, f"nested stack {res} refers to itself", "CFN-NESTED-CYCLE")
        if child is None:  # 読めないスタックは黒箱。出力への参照はスタックへの参照のまま
            return super().stack_output(res, output, path)
        value = child.output(output)
        if value is None:
            return self.unknown([], path, f"output {output} is not in nested stack {res}", "CFN-UNDEFINED-REF")
        hop = f"{self.addr(res)}.Outputs.{output}"
        # 出力の中の pruned／unevaluated の参照は、使った側（いまのリソース）の参照にする
        for r in child.output_extras.get(output, []):
            self.extra_refs.append({**r, "from": self.current, "path": path,
                                    "through": [hop] + r.get("through", [])})
        # 出力の値に参照が残らない（文字列になった、評価できなかった）ときも、スタックへの参照を残す（7.3）
        if not any(True for _ in res_with_fn(value)):
            self.extra_refs.append({"from": self.current, "path": path, "to": self.addr(res),
                                    "attr": f"Outputs.{output}", "fn": "GetAtt", "state": "unevaluated"})
        return prepend_through(value, hop)

    def locate(self, res: str, body: dict) -> Path | None:
        """子テンプレートのファイルを探す（docs/spec/ir-schema/ の 7.4）。見つからなければ None。"""
        meta = body.get("Metadata") or {}
        asset = meta.get("aws:asset:path") if isinstance(meta, dict) else None
        if isinstance(asset, str) and (self.asset_dir / asset).is_file():  # CDK のネストスタック
            return self.asset_dir / asset
        saved = self.current
        self.current = self.addr(res)
        url = self.eval((body.get("Properties") or {}).get("TemplateURL"), "Properties.TemplateURL")
        self.current = saved
        if isinstance(url, str) and "://" not in url and not url.startswith("s3:"):
            local = (self.path.parent / url)
            return local if local.is_file() else None
        if isinstance(url, dict) and "$concat" in url and isinstance(url["$concat"][-1], str):
            url = url["$concat"][-1]  # 組み立てた URL は、最後の印より後ろの文字列（パス）で比べる
        if not isinstance(url, str):
            return None
        tail = [s for s in re.sub(r"^[a-z0-9]+://[^/]*", "", url).split("?")[0].split("/") if s]
        best, hits = 0, []
        for f in self.ctx.local_files():
            segs = f.split("/")
            n = 0
            while n < min(len(segs), len(tail)) and segs[-1 - n] == tail[-1 - n]:
                n += 1
            if n > best:
                best, hits = n, [f]
            elif n == best and n:
                hits.append(f)
        if best and len(hits) == 1:
            self.ctx.assumptions.append(f"{self.addr(res)}: TemplateURL {url} を {hits[0]} に読み替えた")
            return self.ctx.root_dir / hits[0]
        return None

    def child(self, res: str):
        if res in self.children:
            return self.children[res]
        body = self.resources[res]
        path = self.locate(res, body)
        if path is None:
            self.children[res] = None
            saved, self.current = self.current, self.addr(res)
            self.diag("warn", "CFN-NESTED-UNREADABLE", "Properties.TemplateURL",
                      f"nested stack {res}: the child template is not found; drawn as a black box")
            self.current = saved
            return None
        if path.resolve() in self.ctx.active_files:
            self.children[res] = None
            saved, self.current = self.current, self.addr(res)
            self.diag("error", "CFN-NESTED-CYCLE", "Properties.TemplateURL", f"nested stack {res} includes itself")
            self.current = saved
            return None
        self.children[res] = IN_PROGRESS
        saved, self.current = self.current, self.addr(res)
        overrides = {}
        for k, v in ((body.get("Properties") or {}).get("Parameters") or {}).items():
            val = self.eval(v, ir_raw.join_path("Properties.Parameters", k))
            if val is not NO_VALUE:
                overrides[k] = val
        self.current = saved
        try:
            template = load_template(path)
        except (OSError, ValueError, yaml.YAMLError) as e:
            self.children[res] = None
            self.diag("error", "CFN-NESTED-UNREADABLE", "Properties.TemplateURL", f"nested stack {res}: {e}")
            return None
        # 親のスタックのリソースが作られないなら、子のリソースも作られない
        enabled = weaker(self.enabled, self.condition(body["Condition"], "Condition") if "Condition" in body else True)
        child = type(self)(self.ctx, template, path, prefix=self.addr(res) + "/", overrides=overrides,
                          stack_address=self.addr(res), enabled=enabled, asset_dir=self.asset_dir)
        child.register_exports()
        self.ctx.active_files.append(path.resolve())
        child.run()
        self.ctx.active_files.pop()
        self.children[res] = child
        return child
