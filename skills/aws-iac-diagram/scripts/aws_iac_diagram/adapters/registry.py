"""入力の形式を見分けて、アダプタに振り分ける（フェーズ 2b の R1 では名前の表だけ。見分ける処理は R3 以降で足す）。

アダプタの追加のしかたは docs/architecture.md。ここでは import しない（読み込みは使う側が名前で行う）ので、
どのアダプタにも依存しない。
"""
from __future__ import annotations

# 形式 → アダプタのパッケージ（aws_iac_diagram.adapters の下）
ADAPTER_PACKAGES: dict[str, str] = {
    "tf": "aws_iac_diagram.adapters.terraform",
    "cfn": "aws_iac_diagram.adapters.cloudformation",
}
