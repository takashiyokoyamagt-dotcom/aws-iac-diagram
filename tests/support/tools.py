"""aws-iac-diagram-workspace/tools/ の道具を、別名で読む。

`tools/golden.py` は、`tests/golden/`（テストのパッケージ。`discover -s tests` では最上位の名前が `golden`）と
名前が同じなので、`import golden` ではテストのパッケージを読んでしまう。それを避けるため、ファイルの場所から別名で読む。
"""
from __future__ import annotations

import importlib.util
import sys
from types import ModuleType

from .paths import TOOLS


def load_tool(name: str, alias: str | None = None) -> ModuleType:
    """tools/<name>.py を、モジュール名 alias（省略すると name）で読み込む。同じ alias は 1 回だけ読む。"""
    alias = alias or name
    if alias in sys.modules:
        return sys.modules[alias]
    spec = importlib.util.spec_from_file_location(alias, TOOLS / f"{name}.py")
    if spec is None or spec.loader is None:
        raise ImportError(f"tools/{name}.py を読めない")
    module = importlib.util.module_from_spec(spec)
    sys.modules[alias] = module
    spec.loader.exec_module(module)
    return module
