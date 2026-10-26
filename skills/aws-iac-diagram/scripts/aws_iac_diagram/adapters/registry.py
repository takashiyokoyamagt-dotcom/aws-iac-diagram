"""入力の形式を見分けて、アダプタに振り分ける（いまは名前の表だけ。見分ける処理は、入力を自動で判定する入口 diagram.py を作るとき（フェーズ 5〜6）に足す）。

アダプタの追加のしかたは docs/architecture.md。ここでは import しない（読み込みは使う側が名前で行う）ので、
どのアダプタにも依存しない。
"""
from __future__ import annotations

# 形式 → アダプタのパッケージ（aws_iac_diagram.adapters の下）
ADAPTER_PACKAGES: dict[str, str] = {
    "tf": "aws_iac_diagram.adapters.terraform",
    "cfn": "aws_iac_diagram.adapters.cloudformation",
}
