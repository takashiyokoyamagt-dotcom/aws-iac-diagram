"""1つのモジュール（ルートモジュールか、モジュールの呼び出しのインスタンス1つ）を評価する ModuleEval。

責務ごとに分けたミックスイン（module_load・module_vars・module_expand・module_expr・module_props・module_emit）を
ここで1つのクラスに束ねる。状態はすべてこの __init__ が持つ（ミックスインは持たない）。
"""
from __future__ import annotations

from pathlib import Path

from lark import Tree

from aws_iac_diagram.adapters.terraform.model import Block, Context, Instances
from aws_iac_diagram.adapters.terraform.module_emit import EmitMixin
from aws_iac_diagram.adapters.terraform.module_expand import ExpansionMixin
from aws_iac_diagram.adapters.terraform.module_expr import ExpressionMixin
from aws_iac_diagram.adapters.terraform.module_load import LoadMixin
from aws_iac_diagram.adapters.terraform.module_props import PropertiesMixin
from aws_iac_diagram.adapters.terraform.module_vars import VariablesMixin
from aws_iac_diagram.adapters.terraform.modules import summaries as MS


class ModuleEval(LoadMixin, VariablesMixin, ExpansionMixin, ExpressionMixin, PropertiesMixin, EmitMixin):
    """1つのモジュール（ルートモジュールか、モジュールの呼び出しのインスタンス1つ）のブロックを集めて評価する。

    子のモジュール（ローカルのモジュールと、A5 の要約表から作るもの）は、呼び出しのインスタンスごとに1つ作る。
    子の変数は呼び出しの引数を親の中で評価した値、親から見た module.x.y は子の出力 y の値（どちらも through に
    経路を足す。7.3）。
    """

    def __init__(self, ctx: Context, directory: Path | None, prefix: str = ""):
        self.ctx = ctx
        self.dir = directory  # 要約表から作るモジュールは None
        self.prefix = prefix  # address の前に付けるもの（モジュールの中は "module.x."）
        # 子のモジュールのとき（ルートは parent が None）
        self.parent: ModuleEval | None = None
        self.call_address = ""  # 呼び出しのインスタンスの address（module.x、module.x[0]）
        self.call_args: dict[str, Tree] = {}  # 引数の名前 → 親の中の式
        self.call_env: dict = {}  # 引数を評価するときの count.index・each（親の側）
        self.via: str | None = None  # 要約表から作るときは "module_summary"
        self.summary: MS.Summary | None = None
        self.file_override: str | None = None  # 要約表のブロックの file（呼び出しのあるファイル）
        self.enabled_base = True  # 呼び出しの enabled（count が 0 なら false、決まらなければ null）
        self.multi = False  # 呼び出しが ×N（count・for_each が決まらない）
        self.chain: tuple = ()  # 呼び出しの経路のフォルダ・要約表（循環の検出）
        self.depth = 0
        self.provider_map: dict[str, str] = {}  # 子の provider の名前 → 親の provider の名前（providers 引数）
        self.explicit_providers = False  # providers 引数があるか（無ければ既定の provider を引き継ぐ）
        self.depends_from: list = []  # 呼び出しの depends_on（(書かれたモジュール, 式) の並び）
        self.outputs: dict[str, Tree] = {}  # output ブロックの本体
        self._children: dict = {}
        self._plans: dict = {}
        self._var_cache: dict = {}
        self._out_cache: dict = {}
        self._dep_cache: list | None = None
        self._uncovered: list = []  # 要約表に写していない、渡された最上位の入力
        self.blocks: dict[str, Block] = {}  # base（prefix を除いたもの）→ ブロック
        self.ephemerals: dict[str, Block] = {}
        self.locals: dict[str, Tree] = {}
        self.variables: dict[str, Tree] = {}  # 変数の名前 → variable ブロックの本体
        self.var_values: dict[str, object] = {}
        self.var_sources: dict[str, dict] = {}  # evaluation.vars に書くもの（値の出どころ。値は書かない）
        self.redact: set = set()  # --redact-var で伏せる変数の名前
        self.var_files: list[str] = []
        self.providers: dict[str, Tree] = {}  # "aws"・"aws.us_east_1" → provider ブロックの本体
        self.current = ""  # いま評価しているリソースの address
        self.current_enabled = True  # いま評価しているリソースの enabled
        self.extra_refs: list[dict] = []  # unevaluated・pruned の参照
        self.sink: set = set()  # いま評価している属性で、値に残らなかった参照（pruned）
        self.const_mode = False  # tfvars・--var の値を読むとき（参照を使えない）
        self.try_depth = 0  # try()・can() の中を評価しているとき 1 以上
        self._local_cache: dict[str, tuple] = {}
        self._inst_cache: dict[str, Instances] = {}
        self._busy: set = set()

    # --- 診断と参照
    def diag(self, level: str, code: str, path: str, message: str, address: str | None = None) -> None:
        self.ctx.diagnostics.append({"level": level, "code": code,
                                     "address": self.current if address is None else address,
                                     "path": path, "message": message})

    def add_ref(self, path: str, to: str, attr, state: str, through=()) -> None:
        ref = {"from": self.current, "path": path, "to": to, "attr": attr, "fn": "ref", "state": state}
        if through:
            ref["through"] = list(through)
        self.extra_refs.append(ref)
