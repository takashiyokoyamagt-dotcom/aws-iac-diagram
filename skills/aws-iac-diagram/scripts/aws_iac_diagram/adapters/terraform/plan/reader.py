"""plan JSON のインスタンス・モジュール・設定（configuration）を読んで、リソースと参照を集める（PlanReader）。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from aws_iac_diagram.adapters.terraform.addresses import block_address, inst_address
from aws_iac_diagram.adapters.terraform.plan.addresses import collapse, key_order, parse_steps, prefixed
from aws_iac_diagram.adapters.terraform.plan.values import (
    ABSENT, SENS, UNK, conv, finish, has_true, leaves, mark_paths, merge_flags, set_at, string_paths,
)
from aws_iac_diagram.adapters.terraform.refs import collect_active
from aws_iac_diagram.core import ir_raw


# .tf では $pseudo にする data の属性（7.2。引数の無い data だけ）
PSEUDO_DATA = {"aws_region": ("name", "region", "id"), "aws_caller_identity": ("account_id",),
               "aws_partition": ("partition", "id", "dns_suffix")}
SKIP_ROOTS = {"count", "each", "path", "terraform", "self", "ephemeral"}


@dataclass
class Inst:
    address: str
    mode: str
    type: str
    after: object
    unknown: object
    sens: object
    provider_key: str | None = None

    def value_of(self, attr: str | None):
        """属性の値（決まっていて sensitive でないときだけ）。無ければ ABSENT。"""
        if attr is None or not isinstance(self.after, dict):
            return ABSENT
        if self.sens is True:
            return ABSENT
        u = self.unknown.get(attr) if isinstance(self.unknown, dict) else None
        s = self.sens.get(attr) if isinstance(self.sens, dict) else None
        if u is True or s is True or (s and has_true(s)):
            return ABSENT
        v = self.after.get(attr)
        if v is None or (u and has_true(u)):
            return ABSENT
        return v


@dataclass
class Target:
    to: str
    attr: str | None
    through: tuple = ()
    exact: bool = True       # インスタンス1つを指す（添字があるか、count・for_each の無いブロック）
    whole: bool = False      # count・for_each のブロックの全体（スプラットなど）のインスタンスの1つ


@dataclass
class ModInst:
    prefix: str              # "module.vpc." のようなインスタンスの経路（ルートは ""）
    cfg: dict                # configuration の module（resources・module_calls・outputs・variables）
    parent: "ModInst | None" = None
    name: str = ""           # 呼び出しの名前
    call: dict = field(default_factory=dict)
    remote: bool = False     # レジストリ・git などのモジュール（とその中のモジュール）
    zero: bool = False       # count が 0・for_each が空の呼び出し（添字なしの経路）
    children: dict = field(default_factory=dict)  # 名前 → [ModInst]
    dir: str | None = None   # ローカルモジュールのフォルダ（ルートからの相対。.tf.json の file を探すため）
    rindex: dict | None = None  # cfg の resources を address で引く表（block_cfg が最初に使うときに作る）


def is_local_source(src) -> bool:
    return isinstance(src, str) and (src.startswith("./") or src.startswith("../"))


class PlanReader:
    def __init__(self, plan: dict, file_name: str):
        self.plan = plan
        self.file = file_name
        self.insts: dict[str, Inst] = {}
        self.by_block: dict[str, list[Inst]] = {}
        self.resources: list[dict] = []
        self.refs: list[dict] = []
        self.diagnostics: list[dict] = []
        self.locals_seen: set = set()
        self.emitted: set = set()
        self.deleted: set = set()       # actions が delete・forget だけのリソースの address
        self.deleted_sens: dict = {}    # そのブロックの address → sensitive の印（before・after・prior_state の OR）
        self.destroy_plan = False       # managed のリソースの変更がすべて delete・forget（terraform plan -destroy）
        self.root_vars = {k: (v or {}).get("value") for k, v in (plan.get("variables") or {}).items()}
        self.provider_config = (plan.get("configuration") or {}).get("provider_config") or {}
        self.collect_instances()
        root_cfg = (plan.get("configuration") or {}).get("root_module") or {}
        self.root = ModInst("", root_cfg, dir=".")
        self.build_tree(self.root)

    # ---- インスタンス
    def add_inst(self, inst: Inst) -> None:
        if inst.address in self.insts:
            # resource_changes・prior_state・planned_values のどれかが sensitive とした位置は、全部で sensitive にする
            old = self.insts[inst.address]
            old.sens = merge_flags(old.sens, inst.sens)
            return
        self.insts[inst.address] = inst
        self.by_block.setdefault(block_address(inst.address), []).append(inst)

    def collect_instances(self) -> None:
        live_managed = False
        for rc in self.plan.get("resource_changes") or []:
            if "deposed" in rc:
                continue  # 置き換えで残った古いオブジェクト（同じ address の今のオブジェクトとは別）
            ch = rc.get("change") or {}
            actions = ch.get("actions") or []
            if actions == ["delete"] or actions == ["forget"]:
                # 設定から消えたもの・terraform plan -destroy の対象（これから消す）は図に載せない。prior_state にも
                # あるので、address を覚えておいて、そちらから足さない
                self.deleted.add(rc["address"])
                self.note_deleted_sens(rc["address"], ch.get("before_sensitive"))
                self.note_deleted_sens(rc["address"], ch.get("after_sensitive"))
                continue
            live_managed = live_managed or rc.get("mode", "managed") == "managed"
            self.add_inst(Inst(rc["address"], rc.get("mode", "managed"), rc.get("type", ""), ch.get("after"),
                               ch.get("after_unknown") or {},
                               merge_flags(ch.get("after_sensitive") or {}, ch.get("before_sensitive")),
                               rc.get("provider_config_key")))
        self.destroy_plan = bool(self.deleted) and not live_managed

        def walk(mod):
            for r in (mod or {}).get("resources") or []:
                if r["address"] in self.deleted:
                    self.note_deleted_sens(r["address"], r.get("sensitive_values"))
                    continue
                self.add_inst(Inst(r["address"], r.get("mode", "managed"), r.get("type", ""), r.get("values"), {},
                                   r.get("sensitive_values") or {}))
            for c in (mod or {}).get("child_modules") or []:
                walk(c)
        walk(((self.plan.get("prior_state") or {}).get("values") or {}).get("root_module"))
        walk((self.plan.get("planned_values") or {}).get("root_module"))
        for lst in self.by_block.values():
            lst.sort(key=lambda i: key_order(self.inst_key(i.address)))
        self.sorted_addrs = sorted(self.insts)

    def note_deleted_sens(self, address: str, flags) -> None:
        """これから消すリソース（図には作られないものとして出す）の sensitive の印。ブロックごとに合わせて覚える。"""
        b = block_address(address)
        self.deleted_sens[b] = merge_flags(self.deleted_sens.get(b), flags)

    @staticmethod
    def inst_key(address: str):
        steps = parse_steps(address)
        return steps[-1][1] if steps and steps[-1][0] == "index" else None

    # ---- モジュールの木
    def build_tree(self, mod: ModInst) -> None:
        for name, call in sorted(((mod.cfg.get("module_calls") or {}).items())):
            src = call.get("source")
            remote = mod.remote or not is_local_source(src)
            child_dir = None
            if not remote and mod.dir is not None and isinstance(src, str):
                child_dir = os.path.normpath(os.path.join(mod.dir, src)).replace("\\", "/")
            base = f"{mod.prefix}module.{name}"
            counted = "count_expression" in call or "for_each_expression" in call
            keys = set()
            if counted:
                for a in prefixed(self.sorted_addrs, base + "["):
                    steps = parse_steps(a[len(mod.prefix):])
                    if len(steps) >= 3 and steps[2][0] == "index":
                        keys.add(steps[2][1])
            kids = []
            if counted and not keys:
                kids.append(ModInst(base + ".", call.get("module") or {}, mod, name, call, remote, True,
                                    dir=child_dir))
            elif counted:
                for k in sorted(keys, key=key_order):
                    kids.append(ModInst(inst_address(base, k) + ".", call.get("module") or {}, mod, name, call,
                                        remote, mod.zero, dir=child_dir))
            else:
                kids.append(ModInst(base + ".", call.get("module") or {}, mod, name, call, remote, mod.zero,
                                    dir=child_dir))
            mod.children[name] = kids
            for k in kids:
                self.build_tree(k)

    def all_mods(self, mod: ModInst | None = None):
        mod = mod or self.root
        yield mod
        for kids in mod.children.values():
            for k in kids:
                yield from self.all_mods(k)

    def block_cfg(self, mod: ModInst, rel: str) -> dict | None:
        if mod.rindex is None:
            mod.rindex = {}
            for r in mod.cfg.get("resources") or []:
                mod.rindex.setdefault(r.get("address"), r)
        return mod.rindex.get(rel)

    def listed(self, mod: ModInst, rel: str, cfg: dict) -> bool:
        """そのブロックを resources に載せるか（リモートのモジュールの中の data と作られないブロックは載せない）。"""
        if not mod.remote:
            return True
        if cfg.get("mode") == "data":
            return False
        return bool(self.by_block.get(mod.prefix + rel)) and not mod.zero

    # ---- 参照の解決
    def resolve(self, mod: ModInst, ref: str, extra: list | None = None, depth: int = 0) -> list[Target]:
        steps = parse_steps(ref)
        if not steps or steps[0][0] != "attr" or depth > 32:
            return []
        steps = steps + list(extra or [])
        head = steps[0][1]
        if head in SKIP_ROOTS:
            return []
        if head == "local":
            if len(steps) > 1:
                self.locals_seen.add(f"{mod.prefix}local.{steps[1][1]}")
            return []
        if head == "var":
            if mod.parent is None or len(steps) < 2:
                return []
            name = steps[1][1]
            expr = (mod.call.get("expressions") or {}).get(name)
            if not isinstance(expr, dict):
                return []
            hop = f"{mod.prefix[:-1]}.var.{name}"
            out = []
            for r in collapse(expr.get("references") or []):
                for t in self.resolve(mod.parent, r, steps[2:], depth + 1):
                    out.append(Target(t.to, t.attr, (hop,) + t.through, t.exact, t.whole))
            return out
        if head == "module":
            if len(steps) < 2:
                return []
            name = steps[1][1]
            rest = steps[2:]
            kids = mod.children.get(name) or []
            if rest and rest[0][0] == "index":
                want = rest[0][1]
                kids = [k for k in kids if self.inst_key(k.prefix[:-1]) == want]
                rest = rest[1:]
            if not rest or rest[0][0] != "attr":
                return []
            out_name = rest[0][1]
            out = []
            for k in kids:
                o = (k.cfg.get("outputs") or {}).get(out_name) or {}
                expr = o.get("expression") or {}
                hop = f"{k.prefix[:-1]}.output.{out_name}"
                for r in collapse(expr.get("references") or []):
                    for t in self.resolve(k, r, rest[1:], depth + 1):
                        out.append(Target(t.to, t.attr, (hop,) + t.through, t.exact, t.whole))
            return out
        if head == "data":
            if len(steps) < 3:
                return []
            rel = f"data.{steps[1][1]}.{steps[2][1]}"
            typ, rest = steps[1][1], steps[3:]
            cfg = self.block_cfg(mod, rel)
            first = next((s[1] for s in rest if s[0] == "attr"), None)
            if cfg is not None and first in PSEUDO_DATA.get(typ, ()) and not cfg.get("expressions"):
                return []  # .tf の $pseudo と同じく参照にしない
            if cfg is not None and typ == "aws_availability_zones" and first == "names":
                return []  # .tf の $az と同じく参照にしない
        else:
            if len(steps) < 2:
                return []
            rel = f"{head}.{steps[1][1]}"
            rest = steps[2:]
            cfg = self.block_cfg(mod, rel)
        if cfg is None or not self.listed(mod, rel, cfg):
            return []
        base = mod.prefix + rel
        insts = self.by_block.get(base, [])
        if rest and rest[0][0] == "index":
            key = rest[0][1]
            attr = rest[1][1] if len(rest) > 1 and rest[1][0] == "attr" else None
            if not insts:
                return [Target(base, attr)]  # 作られないブロック（.tf と同じく添字なし）
            if key == "*":
                return [Target(i.address, attr, exact=False, whole=True) for i in insts]
            a = inst_address(base, key)
            return [Target(a, attr)] if a in self.insts else []
        attr = rest[0][1] if rest and rest[0][0] == "attr" else None
        if insts and any(self.inst_key(i.address) is not None for i in insts):
            return [Target(i.address, attr, exact=False, whole=True) for i in insts]
        return [Target(base, attr)]

    def resolve_all(self, mod: ModInst, refs: list) -> tuple[list[Target], bool]:
        refs = refs if isinstance(refs, list) else []
        dyn = any(isinstance(r, str) and r.split(".")[0] in ("count", "each") for r in refs)
        out: list[Target] = []
        seen: set = set()
        for r in collapse(refs if isinstance(refs, list) else []):
            for t in self.resolve(mod, r):
                if (t.to, t.attr, t.through) not in seen:
                    seen.add((t.to, t.attr, t.through))
                    out.append(t)
        return out, dyn

    # ---- props と参照
    def add_ref(self, frm: str, path: str, t: Target, state: str, fn: str = "ref") -> None:
        r = {"from": frm, "path": path or "depends_on", "to": t.to, "attr": t.attr if fn == "ref" else None,
             "fn": fn, "state": state}
        if t.through:
            r["through"] = list(t.through)
        self.refs.append(r)

    @staticmethod
    def res_marker(t: Target) -> dict:
        m = {"$res": t.to, "attr": t.attr}
        if t.through:
            m["__through"] = list(t.through)
        return m

    def place(self, frm: str, path: str, v, targets: list[Target], dyn: bool, created: bool):
        """1つの式の値 v に参照を置く（7.3 の plan JSON の参照）。置いた値を返す。"""
        if not targets:
            return v
        if not created:
            v = UNK  # 作られないブロックは値が無い（.tf と同じく、参照は $res のまま残す）
        if v is UNK:
            if not dyn and len(targets) == 1 and targets[0].exact:
                return self.res_marker(targets[0])
            if not dyn and any(t.whole for t in targets):
                return [self.res_marker(t) for t in targets]
            for t in targets:
                self.add_ref(frm, path, t, "unevaluated")
            return v
        unk = mark_paths(v, path, UNK)
        if unk:
            if not dyn and len(unk) == len(targets) and all(t.exact for t in targets):
                for (p, rel), t in zip(unk, targets):
                    v = set_at(v, rel, self.res_marker(t))
                return v
            if not dyn and len(unk) == 1 and targets and all(t.whole for t in targets):
                return set_at(v, unk[0][1], [self.res_marker(t) for t in targets])
            for t in targets:
                self.add_ref(frm, path, t, "unevaluated")
            return v
        if v is ABSENT or v is None:
            for t in targets:
                self.add_ref(frm, path, t, "pruned")  # 値が null（条件で選ばれなかった）
            return v
        for t in targets:
            tv = self.insts[t.to].value_of(t.attr) if t.to in self.insts else ABSENT
            done = False
            if tv is not ABSENT and conv(tv) == v and not isinstance(tv, bool):
                v = self.res_marker(t)  # 値がそのまま先の属性の値（JSON の文字列は $json どうしで比べる）
                continue
            if isinstance(tv, (str, int, float)) and not isinstance(tv, bool):
                tv_s = str(tv)
                for p, rel, s in string_paths(v, path):
                    if s == tv_s:
                        v = set_at(v, rel, self.res_marker(t))
                        done = True
                        break
                    if len(tv_s) >= 3 and tv_s in s:
                        pieces = s.split(tv_s)
                        parts = []
                        for i, piece in enumerate(pieces):
                            if i:
                                parts.append(self.res_marker(t))
                            parts.append(piece)
                        v = set_at(v, rel, ir_raw.normalize_concat(parts))
                        done = True
                        break
            if not done:
                self.add_ref(frm, path, t, "unevaluated")
        return v

    def body(self, frm: str, mod: ModInst, exprs: dict, after, unknown, sens, path: str, created: bool) -> dict:
        out: dict = {}
        a = after if isinstance(after, dict) else {}
        u = unknown if isinstance(unknown, dict) else {}
        s = sens if isinstance(sens, dict) else {}
        sg = (lambda _k: True) if sens is True else s.get  # sens が true: すべての属性が sensitive
        for k in exprs:
            e = exprs[k]
            p = ir_raw.join_path(path, k)
            if isinstance(e, list):  # 入れ子のブロック
                if sg(k) is True:  # ブロックの全体が sensitive: 中の値は使わない
                    for be in e:
                        for t in self.resolve_all(mod, all_refs(be))[0]:
                            self.add_ref(frm, p, t, "unevaluated")
                    out[("$" + k) if k.startswith("$") else k] = SENS
                    continue
                vals = a.get(k) if isinstance(a.get(k), list) else []
                us = u.get(k) if isinstance(u.get(k), list) else []
                ss = s.get(k) if isinstance(s.get(k), list) else []
                blocks = []
                n = len(vals) if created else len(e)
                for i in range(n):
                    be = e[i] if i < len(e) else (e[-1] if e else {})
                    if not isinstance(be, dict):
                        continue
                    blocks.append(self.body(frm, mod, be, vals[i] if i < len(vals) else None,
                                            us[i] if i < len(us) else None, ss[i] if i < len(ss) else None,
                                            ir_raw.join_path(p, i), created))
                if blocks:
                    out[k] = blocks
                elif e and created:
                    for be in e:
                        for t in self.resolve_all(mod, all_refs(be))[0]:
                            self.add_ref(frm, p, t, "pruned")  # ブロックが無い（dynamic の空など）
                continue
            if not isinstance(e, dict):
                continue
            if created:
                v = conv(a.get(k), u.get(k), sg(k))
            else:  # 作られない（destroy の plan のものは、消す前の sensitive の印で伏せる）
                v = conv(e["constant_value"], None, sg(k)) if "constant_value" in e else ABSENT
            targets, dyn = self.resolve_all(mod, e.get("references") or [])
            v = self.place(frm, p, v, targets, dyn, created) if targets else v
            if v is ABSENT or v is None or (v is UNK and not created):
                continue  # 作られないブロックの、参照を置けなかった値は書かない（値が無い）
            out[("$" + k) if k.startswith("$") else k] = v
        if created:
            for k, x in a.items():  # 設定に無い入れ子のブロック（dynamic ブロック。plan JSON の設定に現れない）
                if k in exprs or not (isinstance(x, list) and x and all(isinstance(y, dict) for y in x)):
                    continue
                if path == "" and k in ("timeouts",):
                    continue
                v = conv(x, u.get(k), sg(k))
                if v and v is not ABSENT:
                    out[("$" + k) if k.startswith("$") else k] = v
                    self.diag("info", "TF-PLAN-DYNAMIC-BLOCK", frm, ir_raw.join_path(path, k),
                              "block that is not in the plan's configuration (a dynamic block, or a block the "
                              "provider fills); references in it are not known from the plan JSON")
        return out

    def diag(self, level, code, address, path, message) -> None:
        self.diagnostics.append({"level": level, "code": code, "address": address, "path": path,
                                 "message": message})

    # ---- provider と region
    def provider_of(self, mod: ModInst, cfg: dict, inst: Inst | None):
        key = (inst.provider_key if inst and inst.provider_key else None) or cfg.get("provider_config_key") or ""
        name = key.split(":", 1)[1] if ":" in key else key
        conf = self.provider_config.get(key) or {}
        in_module = ":" in key
        provider = name if "." in name else None
        after_region = None
        if inst and isinstance(inst.after, dict) and isinstance(inst.after.get("region"), str) \
                and cfg.get("type", "").startswith("aws_"):
            after_region = inst.after["region"]  # AWS provider v6 は、すべてのリソースの region を埋める
        region = None
        if provider or in_module:
            region = after_region or self.config_region(conf, in_module)
        elif "region" in (cfg.get("expressions") or {}):
            # リソースの引数 region（v6）。null を渡したもの（モジュールの region = var.region など）は、after では
            # 既定のリージョンが入るので、既定と違うときと、定数で書いたときだけ書く（.tf と同じ）
            e = cfg["expressions"]["region"]
            if isinstance(e, dict) and isinstance(e.get("constant_value"), str):
                region = e["constant_value"]
            elif after_region and after_region != self.config_region(self.provider_config.get("aws") or {}, False):
                region = after_region
        return provider, region

    def config_region(self, conf: dict, in_module: bool) -> str | None:
        """provider の設定の region（定数か、ルートの変数）。"""
        e = (conf.get("expressions") or {}).get("region") or {}
        if isinstance(e.get("constant_value"), str):
            return e["constant_value"]
        refs = collapse(e.get("references") or [])
        if not in_module and len(refs) == 1 and refs[0].startswith("var.") \
                and isinstance(self.root_vars.get(refs[0][4:]), str):
            return self.root_vars[refs[0][4:]]
        return None

    # ---- 書き出し
    def run(self) -> None:
        mods = list(self.all_mods())
        for mod in mods:
            for cfg in mod.cfg.get("resources") or []:
                rel = cfg.get("address")
                if not rel or not self.listed(mod, rel, cfg):
                    continue
                base = mod.prefix + rel
                insts = [] if mod.zero else self.by_block.get(base, [])
                if insts:
                    for inst in insts:
                        self.emit(mod, cfg, inst.address, inst, True)
                else:
                    self.emit(mod, cfg, base, None, False)
        known = {r["address"] for r in self.resources}
        self.res_by_block = {}
        self.res_by_module = {}
        for r in self.resources:  # 以下で何度も引くので、一度だけ表にする
            self.res_by_block.setdefault(block_address(r["address"]), []).append(r["address"])
            self.res_by_module.setdefault(r.get("module", ""), []).append(r["address"])
        self.res_sorted = sorted(known)
        for mod in mods:  # depends_on（モジュールの呼び出しのものは中のすべてのリソースへ）
            for cfg in mod.cfg.get("resources") or []:
                addrs = self.res_by_block.get(mod.prefix + cfg.get("address", ""), [])
                if not addrs or not cfg.get("depends_on"):
                    continue
                targets = self.depends_targets(mod, cfg.get("depends_on") or [])
                for a in addrs:
                    for t in targets:
                        self.add_ref(a, "depends_on", Target(t, None), "active", "depends_on")
            inherited = []
            m = mod
            while m.parent is not None:
                inherited += self.depends_targets(m.parent, m.call.get("depends_on") or [])
                m = m.parent
            if inherited:
                for a in self.res_by_module.get(mod.prefix[:-1], []):
                    for t in inherited:
                        self.add_ref(a, "depends_on", Target(t, None), "active", "depends_on")
        self.refs = [r for r in self.refs if r["from"] in known and r["to"] in known]
        if self.locals_seen:
            self.diag("info", "TF-PLAN-LOCALS", "", "",
                      f"the plan JSON has no expressions for local values; references through "
                      f"{len(self.locals_seen)} local value(s) are not known (pass the .tf folder with --input to "
                      "read them)")
        if self.deleted:
            if self.destroy_plan:
                self.diag("warn", "TF-PLAN-DESTROY", "", "",
                          f"this is a destroy plan (every resource change is a delete): {len(self.deleted)} "
                          "resource(s) will be destroyed; resources still in the configuration are written as "
                          "not created (enabled: false)")
            else:
                self.diag("info", "TF-PLAN-DESTROY", "", "",
                          f"{len(self.deleted)} resource(s) will be destroyed or forgotten by this plan; they are "
                          "not drawn as created")
        if self.plan.get("errored"):
            self.diag("warn", "TF-PLAN-ERRORED", "", "", "the plan failed (errored: true); the plan may be partial")
        elif self.plan.get("complete") is False:
            self.diag("warn", "TF-PLAN-INCOMPLETE", "", "",
                      "the plan is not complete (complete: false, e.g. deferred changes or -target)")
        if self.plan.get("deferred_changes"):
            self.diag("warn", "TF-PLAN-INCOMPLETE", "", "deferred_changes",
                      f"{len(self.plan['deferred_changes'])} change(s) are deferred and not in the plan")

    def depends_targets(self, mod: ModInst, items: list) -> list[str]:
        out = []
        for d in items:
            steps = parse_steps(d) if isinstance(d, str) else []
            if len(steps) >= 2 and steps[0] == ("attr", "module"):
                pre = f"{mod.prefix}module.{steps[1][1]}"
                out += list(prefixed(self.res_sorted, pre + ".")) + list(prefixed(self.res_sorted, pre + "["))
            elif steps:
                base = mod.prefix + ".".join(s[1] for s in steps[:3 if steps[0] == ("attr", "data") else 2])
                out += self.res_by_block.get(base, [])
        return sorted(set(out))

    def emit(self, mod: ModInst, cfg: dict, address: str, inst: Inst | None, created: bool) -> None:
        if address in self.emitted:
            return
        self.emitted.add(address)
        entry = {"address": address, "type": cfg.get("type", inst.type if inst else ""), "file": self.file,
                 "enabled": created}
        if mod.prefix:
            entry["module"] = mod.prefix[:-1]
        provider, region = self.provider_of(mod, cfg, inst)
        if provider:
            entry["provider"] = provider
        if region:
            entry["region"] = region
        exprs = cfg.get("expressions") or {}
        sens = inst.sens if inst else self.deleted_sens.get(block_address(address))
        props = self.body(address, mod, exprs, inst.after if inst else None, inst.unknown if inst else None,
                          sens, "", created)
        for p in leaves(props, "", [], SENS):
            self.diag("info", "TF-PLAN-SENSITIVE", address, p, "sensitive value in the plan; not used")
        for p in leaves(props, "", [], UNK):
            self.diag("info", "TF-PLAN-UNKNOWN", address, p, "value is known only after apply")
        entry["props"] = collect_active(finish(props), address, self.refs)
        self.resources.append(entry)

    def module_vars(self) -> dict:
        out = {}
        for mod in self.all_mods():
            if mod.parent is None or mod.remote:
                continue
            given = mod.call.get("expressions") or {}
            for name, spec in sorted((mod.cfg.get("variables") or {}).items()):
                spec = spec or {}
                src = "argument" if name in given else "default" if "default" in spec else None
                e = {"source": src}
                if spec.get("sensitive"):
                    e["hidden"] = "sensitive"
                elif spec.get("ephemeral"):
                    e["hidden"] = "ephemeral"
                out[f"{mod.prefix}{name}"] = e
        return out


def all_refs(be) -> list:
    out = []
    if isinstance(be, dict):
        if "references" in be and isinstance(be["references"], list):
            out += be["references"]
        for k, v in be.items():
            if k not in ("references", "constant_value"):
                out += all_refs(v)
    elif isinstance(be, list):
        for x in be:
            out += all_refs(x)
    return out
