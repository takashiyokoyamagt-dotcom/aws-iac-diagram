"""集めたブロックをリソース（raw IR の resources）にして出す。count・for_each のインスタンスごとの出力、provider・region、
depends_on、要約表に写していない入力の診断。
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from lark import Tree

from aws_iac_diagram.adapters.terraform.addresses import inst_address
from aws_iac_diagram.adapters.terraform.evaluator import functions as E
from aws_iac_diagram.adapters.terraform.evaluator.functions import Unknown
from aws_iac_diagram.adapters.terraform.hcl import NOTCONST, const, flatten, name_of, sig, unwrap
from aws_iac_diagram.adapters.terraform.model import Block, DATA_META, Instances, MODULE_META, RESOURCE_META, weakest
from aws_iac_diagram.adapters.terraform.modules import summaries as M
from aws_iac_diagram.adapters.terraform.refs import collect_active, ref_order

if TYPE_CHECKING:
    from aws_iac_diagram.adapters.terraform.module_eval import ModuleEval


def path_present(value, parts: list):
    """value の中に、経路 parts（"*" はどのキー・要素でもよい）の値（null・空の {}・[] 以外）があるか。
    True／False と、途中や葉の値が決まらず調べられなかったときは None（ほかに当たるものが無いとき）。"""
    if isinstance(value, Unknown):
        return None
    if not parts:
        return value is not None and value != {} and value != []
    head, rest = parts[0], parts[1:]
    if head == "*":
        if isinstance(value, dict):
            items = list(value.values())
        elif isinstance(value, list):
            items = value
        else:
            return None if not (value is None or E.is_concrete(value)) else False
        got = [path_present(v, rest) for v in items]
        return True if True in got else None if None in got else False
    if isinstance(value, dict):
        return path_present(value[head], rest) if head in value else False
    return None if not (value is None or E.is_concrete(value)) else False


class EmitMixin:
    """ModuleEval のリソースの書き出し。状態は ModuleEval の __init__ が持つ。"""

    # --- 本体
    def report_uncovered(self) -> None:
        """要約表に写していない入力（最上位の名前と、# not-covered: の入れ子の経路 listeners.*.rules など）を、
        渡された値に当たれば TF-MODULE-SUMMARY-INPUT に書く。"""
        hits = list(self._uncovered)
        unknown: list = []
        for path in self.summary.uncovered:
            parts = path.split(".")
            if len(parts) < 2 or parts[0] not in self.call_args or parts[0] not in self.variables:
                continue
            saved, self.sink = self.sink, set()
            try:
                value = self.child_var(parts[0])
            finally:
                self.sink = saved
            got = path_present(value, parts[1:])
            if got:
                hits.append(path)
            elif got is None:
                unknown.append(path)
        if unknown:
            self.diag("info", "TF-MODULE-SUMMARY-INPUT", "unknown",
                      f"inputs that the summary table does not cover could not be checked (the value is not known): "
                      f"{', '.join(sorted(unknown))}", self.call_address)
        if hits:
            self.diag("info", "TF-MODULE-SUMMARY-INPUT", "",
                      f"inputs that the summary table does not cover (resources they make are not written): "
                      f"{', '.join(sorted(set(hits)))}", self.call_address)

    def run(self) -> None:
        if self.via == "module_summary":
            self.report_uncovered()
        for base, blk in sorted(self.blocks.items()):
            if blk.kind == "data" and self.via == "module_summary":
                continue  # 要約表の中の data は載せない（4章の module_summary）
            inst = self.instances(blk)
            addr = self.prefix + base
            if inst.mode == "zero" and self.via == "module_summary":
                continue  # 要約表から展開するのは、作られるリソースだけ（4章の module_summary）
            if self.expanded(blk):
                if inst.mode == "unknown":
                    u = inst.unknown
                    self.diag("warn", "TF-COUNT-UNRESOLVED", inst.meta,
                              f"{inst.meta} is not known ({u.reason}); the module is written once with "
                              "multiplicity N", addr + "[*]")
                for k in self.child_keys(blk):
                    self.child(blk, k).run()
                continue
            if inst.mode == "single":
                self.emit(blk, inst, addr, True, {})
            elif inst.mode == "count":
                for k in inst.keys:
                    self.emit(blk, inst, inst_address(addr, k), True, {"count": {"index": k}})
            elif inst.mode == "each":
                for k in inst.keys:
                    self.emit(blk, inst, inst_address(addr, k), True,
                              {"each": {"key": k, "value": inst.values[k]}})
            else:
                why = ("count is 0" if inst.meta == "count" else "for_each is empty") if inst.mode == "zero" else \
                    f"{inst.meta} is not known"
                u = Unknown(f"{'count.index' if inst.meta == 'count' else 'each'} is not known ({why})",
                            "TF-COUNT-INDEX", "info")
                env = {"count": {"index": u}} if inst.meta == "count" else {"each": {"key": u, "value": u}}
                if inst.mode == "zero":
                    self.emit(blk, inst, addr, False, env)
                else:
                    self.emit(blk, inst, addr + "[*]", None, env)
        self.ctx.refs += self.extra_refs
        self.extra_refs = []

    def emit(self, blk: Block, inst: Instances, address: str, enabled, env: dict) -> None:
        ctx = self.ctx
        enabled = weakest(enabled, self.enabled_base)
        if blk.kind == "module" and "create" in blk.attrs and self.create_convention(blk):
            # 黒箱の呼び出しで、create 引数（terraform-aws-modules の慣習。false なら何も作らない）が false と決まる
            # ものは作られない。決まらなければ、count が決まらないときと同じく null（7.2）
            c = self.quiet_eval(blk.attrs["create"], env)
            if c is False or c == "false":
                enabled = weakest(enabled, False)
                self.diag("info", "TF-MODULE-NOT-CREATED", "create",
                          "create is false; the module call makes nothing (terraform-aws-modules convention)", address)
            elif not (c is True or c == "true"):
                enabled = weakest(enabled, None)
                self.diag("info", "TF-MODULE-NOT-CREATED", "create",
                          "create is not known; whether the module makes anything is not known", address)
        self.current = address
        self.current_enabled = enabled
        entry: dict = {"address": address, "type": blk.type, "file": blk.file, "enabled": enabled}
        if self.via:
            entry["via"] = self.via
        if self.prefix:
            entry["module"] = self.prefix[:-1]
        if inst.mode == "unknown" or self.multi:
            entry["multiplicity"] = "N"
        if inst.mode == "unknown":
            u = inst.unknown
            for to, attr, through in sorted(u.refs, key=ref_order):
                self.add_ref(inst.meta, to, attr, "unevaluated", through)
            self.diag("warn", "TF-COUNT-UNRESOLVED", inst.meta,
                      f"{inst.meta} is not known ({u.reason}); written as one block with multiplicity N")
        region = None
        if blk.kind == "module":  # 黒箱のモジュールの呼び出し（2章）
            meta = MODULE_META
            entry["via"] = "module_blackbox"
            source = const(blk.attrs["source"]) if "source" in blk.attrs else NOTCONST
            version = const(blk.attrs["version"]) if "version" in blk.attrs else NOTCONST
            if isinstance(source, str) and source:
                entry["source"] = source
                if isinstance(version, str) and version:
                    entry["version"] = version
            plan = self.module_plan(blk)
            self.diag(plan[1], plan[2], "source" if plan[2] == "TF-MALFORMED-BLOCK" else "", plan[3])
            if "providers" in blk.attrs:  # 中身の既定の provider（aws）を別の provider にした呼び出し
                target = self.providers_arg(blk.attrs["providers"], address).get("aws")
                if target and "." in target:
                    entry["provider"] = target
                    region = self.provider_region(self.resolve_provider(target))
        else:
            meta = RESOURCE_META if blk.kind == "resource" else DATA_META
            explicit = self.provider_name(blk.attrs["provider"]) if "provider" in blk.attrs else None
            if "provider" in blk.attrs and explicit is None:
                self.diag("warn", "TF-MALFORMED-BLOCK", "provider", "provider is not a provider reference")
            name = explicit or blk.type.split("_", 1)[0]
            found = self.resolve_provider(name)
            if found is not None:
                pmod, pname = found
                # 既定の provider（alias の無いもの）は書かない。リージョンはルートの既定の provider 以外なら書く
                if "." in pname:
                    entry["provider"] = pname
                if "." in pname or pmod.parent is not None:
                    region = self.provider_region(found)
            elif explicit and "." in explicit:
                entry["provider"] = explicit
                self.diag("info", "TF-PROVIDER-UNCONFIGURED", "provider",
                          f"provider {explicit} has no configuration in this module or its callers; "
                          "region is not known")
            # AWS provider v6 のリソースの引数 region は、provider の region より優先する（Terraform と同じ）
            if blk.type.startswith("aws_") and "region" in blk.attrs:
                r = self.quiet_eval(blk.attrs["region"], env)
                if isinstance(r, str):
                    region = r
        if isinstance(region, str) and region:
            entry["region"] = region
        props = self.body_props(blk.body, "", env, meta)
        entry["props"] = collect_active(props, address, ctx.refs)
        if "depends_on" in blk.attrs:
            for a in self.depends_targets(blk.attrs["depends_on"], self):
                ctx.refs.append({"from": address, "path": "depends_on", "to": a, "attr": None,
                                 "fn": "depends_on", "state": "active"})
        for a in self.inherited_depends():
            ctx.refs.append({"from": address, "path": "depends_on", "to": a, "attr": None,
                             "fn": "depends_on", "state": "active"})
        ctx.resources.append(entry)

    def create_convention(self, blk: Block) -> bool:
        """create 引数を「false なら何も作らない」と読んでよい呼び出しか（terraform-aws-modules と、要約表の中）。"""
        if self.via == "module_summary":
            return True
        source = const(blk.attrs["source"]) if "source" in blk.attrs else NOTCONST
        key = M.registry_key(source) if isinstance(source, str) else None
        return bool(key and key.startswith("terraform-aws-modules/"))

    def provider_region(self, found) -> str | None:
        """provider の設定（resolve_provider の結果）の region。文字列で決まらなければ None。"""
        if found is None:
            return None
        pmod, pname = found
        conf_attrs = pmod.body_attrs(pmod.providers[pname])
        if "region" not in conf_attrs:
            return None
        r = pmod.quiet_eval(conf_attrs["region"], {})
        return r if isinstance(r, str) else None

    def inherited_depends(self) -> list[str]:
        """モジュールの呼び出しの depends_on（入れ子の呼び出しのものも）の先の address。中のすべてのリソースに付ける。"""
        if self._dep_cache is None:
            out: list[str] = []
            for mod, expr in self.depends_from:
                out += mod.depends_targets(expr, self)
            self._dep_cache = sorted(set(out))
        return self._dep_cache

    def quiet_eval(self, expr, env: dict):
        """参照や診断を残さずに値だけを見る（provider・region）。"""
        saved, self.sink = self.sink, set()
        try:
            return self.eval_safe(expr, env)
        finally:
            self.sink = saved

    @staticmethod
    def provider_name(expr) -> str | None:
        """メタ引数 provider の値（aws.us_east_1）。古い書き方の文字列（"aws.us_east_1"）も読む。読めなければ None。"""
        root, steps = flatten(expr)
        if isinstance(root, Tree) and root.data == "identifier" and all(s[0] == "attr" for s in steps) \
                and len(steps) <= 1:
            return ".".join([name_of(root)] + [s[1] for s in steps])
        v = const(expr)
        if isinstance(v, str) and re.fullmatch(r"[a-z0-9_-]+(\.[A-Za-z0-9_-]+)?", v):
            return v
        return None

    def depends_targets(self, expr, where: "ModuleEval") -> list[str]:
        """depends_on の先の address。展開するモジュールなら、その中のすべてのリソース。where は診断を書くモジュール。"""
        items = sig(unwrap(expr)) if isinstance(unwrap(expr), Tree) and unwrap(expr).data == "tuple" else []
        out: list[str] = []
        for el in items:
            root, steps = flatten(el)
            name = name_of(root) if isinstance(root, Tree) and root.data == "identifier" else None
            first = steps[0][1] if steps and steps[0][0] == "attr" else None
            if name == "data":
                base = f"data.{first}.{steps[1][1] if len(steps) > 1 and steps[1][0] == 'attr' else ''}"
            elif name == "module":
                base = f"module.{first}"
            else:
                base = f"{name}.{first}"
            blk = self.blocks.get(base) if name and first else None
            if blk is not None:
                if self.expanded(blk):
                    for k in self.child_keys(blk):
                        out += self.child(blk, k).resource_addresses()
                else:
                    out += self.all_addresses(blk)
            elif name == "ephemeral":
                continue
            else:
                text = name or "an expression"
                if first:
                    text += f".{first}"
                where.diag("warn", "TF-UNDEFINED-REF", "depends_on",
                           f"depends_on to {text} is not a resource, a data source or a module in this module")
        return out
