"""モジュール1つ分の .tf（か要約表の HCL）を読み、resource・data・module・variable・output・provider のブロックを集める。
override のファイルは、ほかのファイルをすべて読んでから Terraform と同じ規則で重ねる。
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import hcl2
from lark import Tree

from aws_iac_diagram.adapters.terraform.hcl import const, fix_heredocs, label_text, merge_body, name_of, sig
from aws_iac_diagram.adapters.terraform.model import Block
from aws_iac_diagram.adapters.terraform.modules import summaries as M

if TYPE_CHECKING:
    from aws_iac_diagram.adapters.terraform.module_eval import ModuleEval


_SUMMARY_TREES: dict = {}


def summary_tree(summary: M.Summary) -> Tree:
    """要約表の HCL の構文木（1回だけ読む）。"""
    key = (summary.source, summary.majors, summary.line)
    if key not in _SUMMARY_TREES:
        _SUMMARY_TREES[key] = hcl2.parses_to_tree(summary.text)
    return _SUMMARY_TREES[key]


class LoadMixin:
    """ModuleEval の読み込み（.tf のファイル、要約表）。状態は ModuleEval の __init__ が持つ。"""

    # --- 読み込み
    def load(self) -> None:
        if self.summary is not None:  # 要約表（references/module-summaries.md）の HCL
            self.collect(summary_tree(self.summary), self.file_override)
            return
        if not self.dir.is_dir():
            raise ValueError(f"フォルダではありません: {self.dir}")
        for f in sorted(self.dir.glob("*.tf.json")):
            self.diag("warn", "TF-TFJSON-UNSUPPORTED", "", f"{self.ctx.rel(f)}: .tf.json is not read without a plan JSON "
                      "(telling nested blocks from attributes needs provider schemas); pass --plan to take its blocks "
                      "from the plan", "")
        # Terraform が読まないファイル（. で始まるもの、エディタの一時ファイル #…#・…~）は読まない
        files = sorted(p for p in self.dir.iterdir() if p.is_file() and p.suffix == ".tf"
                       and not p.name.startswith((".", "#")) and not p.name.endswith("~"))
        if not files:
            raise ValueError(f".tf がありません: {self.dir}")
        overrides = []
        for f in files:
            tree = self.read_tf(f)
            if tree is None:
                continue
            if f.stem == "override" or f.stem.endswith("_override"):
                overrides.append((tree, self.ctx.rel(f)))
            else:
                self.collect(tree, self.ctx.rel(f))
        for tree, rel in overrides:  # override のファイルは、ほかのファイルをすべて読んでから重ねる（名前順）
            self.collect(tree, rel, override=True)

    def read_tf(self, f: Path) -> Tree | None:
        rel = self.ctx.rel(f)
        try:
            text = f.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError) as e:
            self.diag("error", "TF-PARSE-ERROR", "", f"{rel}: {type(e).__name__}: {e}", "")
            return None
        text, fixed = fix_heredocs(text)
        if fixed:
            self.diag("info", "TF-HEREDOC-TRAILING-SPACE", "",
                      f"{rel}: removed trailing spaces on {fixed} heredoc marker line(s) before parsing", "")
        try:
            return hcl2.parses_to_tree(text)
        except Exception as e:  # noqa: BLE001  lark の例外（UnexpectedToken など）
            first = str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__
            self.diag("error", "TF-PARSE-ERROR", "", f"{rel}: {type(e).__name__}: {first}", "")
            return None

    @staticmethod
    def body_attrs(b: Tree) -> dict:
        return {name_of(sig(a)[0]): sig(a)[-1] for a in sig(b) if isinstance(a, Tree) and a.data == "attribute"}

    def collect(self, tree: Tree, rel: str, override: bool = False) -> None:
        body = sig(tree)[0]
        for item in sig(body):
            if not (isinstance(item, Tree) and item.data == "block"):
                continue
            cs = sig(item)
            btype = name_of(cs[0])
            labels = [label_text(x) for x in cs[1:-1]]
            b = cs[-1]
            attrs = self.body_attrs(b)
            if btype == "check":
                # check ブロックの中の data（scoped data source）。assert は読まない
                for inner in sig(b):
                    if isinstance(inner, Tree) and inner.data == "block":
                        ics = sig(inner)
                        if name_of(ics[0]) == "data" and len(ics) == 4:
                            self.add_block(Block("data", label_text(ics[1]), label_text(ics[2]), rel, ics[-1],
                                                 self.body_attrs(ics[-1])), rel, override)
                continue
            if btype in ("resource", "data", "ephemeral") and len(labels) == 2:
                self.add_block(Block(btype, labels[0], labels[1], rel, b, attrs), rel, override)
            elif btype == "module" and len(labels) == 1:
                self.add_block(Block("module", "module", labels[0], rel, b, attrs), rel, override)
            elif btype == "locals":
                for name, expr in attrs.items():
                    if name in self.locals and not override:
                        self.diag("warn", "TF-DUPLICATE-BLOCK", "", f"{rel}: local.{name} is defined twice", "")
                    self.locals[name] = expr
            elif btype == "variable" and len(labels) == 1:
                name = labels[0]
                if override and name in self.variables:
                    self.variables[name] = merge_body(self.variables[name], b)
                elif name in self.variables:
                    self.diag("warn", "TF-DUPLICATE-BLOCK", "", f"{rel}: variable {name} is defined twice", "")
                else:
                    self.variables[name] = b
            elif btype == "provider" and len(labels) == 1:
                alias = const(attrs["alias"]) if "alias" in attrs else None
                key = labels[0] + (f".{alias}" if isinstance(alias, str) else "")
                if override and key in self.providers:
                    self.providers[key] = merge_body(self.providers[key], b)
                else:
                    self.providers[key] = b
            elif btype == "output" and len(labels) == 1:
                name = labels[0]
                if override and name in self.outputs:
                    self.outputs[name] = merge_body(self.outputs[name], b)
                elif name in self.outputs:
                    self.diag("warn", "TF-DUPLICATE-BLOCK", "", f"{rel}: output {name} is defined twice", "")
                else:
                    self.outputs[name] = b

    def add_block(self, blk: Block, rel: str, override: bool) -> None:
        table = self.ephemerals if blk.kind == "ephemeral" else self.blocks
        if override:
            old = table.get(blk.base)
            if old is None:
                self.diag("warn", "TF-OVERRIDE-UNMATCHED", "", f"{rel}: {blk.base} is not defined in other files", "")
                return
            body = merge_body(old.body, blk.body)
            table[blk.base] = Block(old.kind, old.type, old.name, old.file, body, self.body_attrs(body))
            self.ctx.assume(f"override file {rel} is merged into {blk.base}")
            return
        if blk.base in table:
            self.diag("warn", "TF-DUPLICATE-BLOCK", "", f"{rel}: {blk.base} is defined twice; the first one is used",
                      "")
            return
        table[blk.base] = blk
