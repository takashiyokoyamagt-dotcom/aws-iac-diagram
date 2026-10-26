"""count・for_each の展開と、モジュールの呼び出しのインスタンス（ローカルのモジュール、A5 の要約表、黒箱）の作成。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from lark import Tree

from aws_iac_diagram.adapters.terraform.addresses import inst_address
from aws_iac_diagram.adapters.terraform.evaluator import values as V
from aws_iac_diagram.adapters.terraform.evaluator.values import EvalError, Res, Unknown, ZeroColl
from aws_iac_diagram.adapters.terraform.hcl import NOTCONST, const, sig, unwrap
from aws_iac_diagram.adapters.terraform.model import (
    Block, Instances, MODULE_META, ModObj, ResList, ResMap, weakest,
)
from aws_iac_diagram.adapters.terraform.modules.sources import is_local, join_summary_source
from aws_iac_diagram.adapters.terraform.modules import resolve as MR
from aws_iac_diagram.adapters.terraform.modules import summaries as MS

if TYPE_CHECKING:
    from aws_iac_diagram.adapters.terraform.module_eval import ModuleEval


# モジュールの入れ子の深さの上限（これより深い呼び出しは黒箱。TF-MODULE-DEPTH）
MAX_MODULE_DEPTH = 16
# count が 0・決まらないモジュールの呼び出しのインスタンスのキー（ModuleEval.child）
ZERO, STAR = "\u0000zero", "\u0000star"


class ExpansionMixin:
    """ModuleEval の count・for_each の展開と子のモジュール。状態は ModuleEval の __init__ が持つ。"""

    def instances(self, blk: Block) -> Instances:
        base = blk.base
        if base in self._inst_cache:
            return self._inst_cache[base]
        meta = "count" if "count" in blk.attrs else "for_each" if "for_each" in blk.attrs else ""
        if not meta:
            inst = Instances("single")
            self._inst_cache[base] = inst
            return inst
        key = ("instances", base)
        if key in self._busy:
            return Instances("unknown", meta, unknown=Unknown(f"{meta} of {base} refers to itself", "TF-CYCLE"))
        self._busy.add(key)
        saved, self.sink = self.sink, set()
        try:
            v = self.eval_safe(blk.attrs[meta], {})
            inst = self.decide_instances(meta, v)
        finally:
            self.sink = saved  # 決まった count・for_each の式の参照は残さない（CFN の Fn::ForEach と同じ）
            self._busy.discard(key)
        self._inst_cache[base] = inst
        return inst

    @staticmethod
    def decide_instances(meta: str, v) -> Instances:
        def unknown(reason, code="TF-UNEVALUATED"):
            return Instances("unknown", meta, unknown=V.unknown_from(v, reason, code) if not isinstance(v, Unknown)
                             else v)
        if meta == "count":
            if v is None:
                return unknown("count is null", "TF-EVAL-ERROR")
            if isinstance(v, str):  # "2"（型の無い変数に --var で渡した値など）は数に変換する（Terraform と同じ）
                try:
                    v = V.to_number(v)
                except EvalError as e:
                    return unknown(str(e), "TF-EVAL-ERROR")
            if not V.is_number(v):
                return unknown("count is not known before apply")
            try:
                n = V.to_int(v)
            except EvalError as e:
                return unknown(str(e), "TF-EVAL-ERROR")
            if n < 0:
                return unknown("count is negative", "TF-EVAL-ERROR")
            return Instances("count", meta, keys=list(range(n))) if n else Instances("zero", meta)
        if isinstance(v, dict):
            keys = sorted(v)
            return Instances("each", meta, keys=keys, values={k: v[k] for k in keys}) if keys else \
                Instances("zero", meta)
        if isinstance(v, list):
            if not all(isinstance(x, str) for x in v):
                if all(V.is_concrete(x) for x in v):
                    return unknown("for_each must be a map or a set of strings", "TF-EVAL-ERROR")
                return unknown("for_each is not known before apply")
            keys = sorted(set(v))
            return Instances("each", meta, keys=keys, values={k: k for k in keys}) if keys else \
                Instances("zero", meta)
        if v is None:
            return unknown("for_each is null", "TF-EVAL-ERROR")
        return unknown("for_each is not known before apply")

    def all_addresses(self, blk: Block) -> list[str]:
        """ブロックのすべてのインスタンスの address（0 個なら作られないブロック、決まらなければ [*]）。"""
        base = self.prefix + blk.base
        inst = self.instances(blk)
        if self.via == "module_summary" and (blk.kind == "data" or inst.mode == "zero"):
            return []  # 要約表の中の data と、作られないリソースは載せない
        if inst.mode in ("count", "each"):
            return [inst_address(base, k) for k in inst.keys]
        if inst.mode == "unknown":
            return [base + "[*]"]
        return [base]

    def block_value(self, blk: Block):
        """リソース・data・module の参照の値（インスタンスごとの Res のまとまり）。展開するモジュールは ModObj。"""
        base = self.prefix + blk.base
        inst = self.instances(blk)
        if blk.kind == "module" and self.expanded(blk):
            if inst.mode == "single":
                return ModObj(self.child(blk, None))
            if inst.mode == "count":
                return ResList(ModObj(self.child(blk, k)) for k in inst.keys)
            if inst.mode == "each":
                return ResMap((k, ModObj(self.child(blk, k))) for k in inst.keys)
            if inst.mode == "zero":  # 要約表の中の作られない呼び出しは載せない（リソースと同じ）
                return ResList() if self.via == "module_summary" else ZeroColl(ModObj(self.child(blk, ZERO)))
            return ModObj(self.child(blk, STAR))
        if inst.mode == "single":
            return Res(base)
        if inst.mode == "count":
            return ResList(Res(inst_address(base, k)) for k in inst.keys)
        if inst.mode == "each":
            return ResMap((k, Res(inst_address(base, k))) for k in inst.keys)
        if inst.mode == "zero":
            # 要約表の中の作られないリソースは載せないので、Terraform と同じく空のまとまり（[0] は誤り。try で null）
            return ResList() if self.via == "module_summary" else ZeroColl(Res(base))
        return Res(base + "[*]", None, True)

    # --- モジュールの呼び出し
    def module_plan(self, blk: Block) -> tuple:
        """モジュールの呼び出しの読み方。("local", フォルダ)・("summary", Summary, 前提)・
        ("blackbox", level, code, 理由)。"""
        if blk.base in self._plans:
            return self._plans[blk.base]
        source = const(blk.attrs["source"]) if "source" in blk.attrs else NOTCONST
        version = const(blk.attrs["version"]) if "version" in blk.attrs else NOTCONST
        version = version if isinstance(version, str) and version else None
        plan: tuple
        if not (isinstance(source, str) and source):
            plan = ("blackbox", "warn", "TF-MALFORMED-BLOCK", "module has no constant source")
        elif self.via == "module_summary" and is_local(source):
            # 要約表の中のサブモジュール（"./modules/x"）は、同じ版の要約表の "<source>//modules/x"
            key = join_summary_source(self.summary.source, source)
            cands = [s for s in MS.load()[0].get(key or "", []) if set(s.majors) & set(self.summary.majors)]
            plan = ("summary", cands[0], None) if cands else \
                ("blackbox", "info", "TF-MODULE-BLACKBOX", f"submodule {key} is not in the summary table")
        elif is_local(source):
            d = (self.dir / source).resolve() if self.dir is not None else None
            if d is None or not d.is_dir() or not any(p.suffix == ".tf" for p in d.iterdir() if p.is_file()):
                where = self.ctx.rel(d) if d is not None else source
                plan = ("blackbox", "warn", "TF-MODULE-UNREADABLE",
                        f"local module {source} cannot be read (no .tf files in {where})")
            else:
                plan = ("local", d)
        else:
            summary, why, note = MR.choose(source, version)
            if summary is None:
                plan = MR.blackbox_plan(source, why)
            else:
                plan = ("summary", summary, note)
        if plan[0] != "blackbox":
            key = plan[1] if plan[0] == "local" else f"summary:{plan[1].source}"
            if key in self.chain:
                plan = ("blackbox", "warn", "TF-MODULE-CYCLE", f"module {source} calls itself")
            elif self.depth + 1 > MAX_MODULE_DEPTH:
                plan = ("blackbox", "warn", "TF-MODULE-DEPTH",
                        f"module {source} is nested deeper than {MAX_MODULE_DEPTH} levels")
        self._plans[blk.base] = plan
        return plan

    def expanded(self, blk: Block) -> bool:
        return blk.kind == "module" and self.module_plan(blk)[0] != "blackbox"

    def child(self, blk: Block, key) -> "ModuleEval":
        """展開するモジュールの呼び出しのインスタンス（key は count の番号・for_each のキー・None・ZERO・STAR）。"""
        ck = (blk.base, key)
        if ck in self._children:
            return self._children[ck]
        base = self.prefix + blk.base
        plan = self.module_plan(blk)
        enabled = True
        meta = "count" if "count" in blk.attrs else "for_each"
        if key is None:
            addr, env = base, {}
        elif key in (ZERO, STAR):
            why = ("count is 0" if meta == "count" else "for_each is empty") if key == ZERO else f"{meta} is not known"
            u = Unknown(f"{'count.index' if meta == 'count' else 'each'} is not known ({why})", "TF-COUNT-INDEX", "info")
            env = {"count": {"index": u}} if meta == "count" else {"each": {"key": u, "value": u}}
            addr = base if key == ZERO else base + "[*]"
            enabled = False if key == ZERO else None
        else:
            addr = inst_address(base, key)
            inst = self.instances(blk)
            env = {"count": {"index": key}} if inst.mode == "count" else \
                {"each": {"key": key, "value": inst.values[key]}}
        c = type(self)(self.ctx, plan[1] if plan[0] == "local" else None, addr + ".")
        c.parent = self
        c.call_address = addr
        c.call_args = {k: v for k, v in blk.attrs.items() if k not in MODULE_META}
        c.call_env = env
        if plan[0] == "summary":
            c.via, c.summary = "module_summary", plan[1]
            c.file_override = blk.file
            if plan[2]:
                self.ctx.assume(f"{addr}: {plan[2]}")
        c.enabled_base = weakest(self.enabled_base, enabled)
        c.multi = self.multi or key == STAR
        c.chain = self.chain + ((plan[1] if plan[0] == "local" else f"summary:{plan[1].source}"),)
        c.depth = self.depth + 1
        if "providers" in blk.attrs:
            c.explicit_providers = True
            c.provider_map = self.providers_arg(blk.attrs["providers"], addr)
        c.depends_from = self.depends_from + ([(self, blk.attrs["depends_on"])] if "depends_on" in blk.attrs else [])
        self._children[ck] = c
        c.load()
        c.setup_child()
        self.ctx.modules.append(c)
        return c

    def child_keys(self, blk: Block) -> list:
        inst = self.instances(blk)
        if inst.mode == "single":
            return [None]
        if inst.mode in ("count", "each"):
            return list(inst.keys)
        if inst.mode == "zero":
            return [] if self.via == "module_summary" else [ZERO]
        return [STAR]

    def providers_arg(self, expr, addr: str) -> dict:
        """モジュールの providers 引数（{ aws = aws.use1, aws.east = aws }）を、子の名前 → 親の名前にする。"""
        out: dict = {}
        t = unwrap(expr)
        if not (isinstance(t, Tree) and t.data == "object"):
            self.diag("warn", "TF-MALFORMED-BLOCK", "providers", "providers is not an object", addr)
            return out
        for el in sig(t):
            cs = sig(el)
            k, v = self.provider_name(sig(cs[0])[0]), self.provider_name(cs[-1])
            if k is None or v is None:
                self.diag("warn", "TF-MALFORMED-BLOCK", "providers", "providers has an entry that is not a provider",
                          addr)
                continue
            out[k] = v
        return out

    def resolve_provider(self, name: str):
        """provider の名前（aws・aws.east）を、設定のあるモジュールとその中の名前にする。無ければ None。"""
        if name in self.providers:
            return self, name
        if self.parent is None:
            return None
        if name in self.provider_map:
            return self.parent.resolve_provider(self.provider_map[name])
        if "." not in name and not self.explicit_providers:  # 既定の provider は呼び出し側から引き継ぐ
            return self.parent.resolve_provider(name)
        return None

    def resource_addresses(self) -> list[str]:
        """このモジュールの中（入れ子のモジュールを含む）のすべてのリソース・data の address（depends_on に使う）。"""
        out: list[str] = []
        for base, blk in sorted(self.blocks.items()):
            if blk.kind == "data" and self.via == "module_summary":
                continue
            if self.expanded(blk):
                for k in self.child_keys(blk):
                    out += self.child(blk, k).resource_addresses()
            elif blk.kind == "module" or blk.kind in ("resource", "data"):
                out += self.all_addresses(blk)
        return out
