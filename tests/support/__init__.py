"""テストが共有する道具（tests/support/。unit・integration・golden・architecture から使う）。

- paths.py: リポジトリの場所の定数。import すると、SKILL の scripts/ と開発用の tools/ が sys.path に入る
  （`from support.paths import ...` でも、`import support` だけでも入る。テストのファイルが自分で sys.path をいじらない）。
- tools.py: aws-iac-diagram-workspace/tools/ の道具を、名前を指定して読む。
- builders.py ほか: 文字列から raw IR を作る、plan JSON を組み立てる、など。同じ道具を複数のファイルに写さない。
- arch_*.py: 構成の検査（tests/architecture/）のやり方。

import するときの決まり: `from support.paths import ...`（tests/ が sys.path に入っている前提。`discover -s tests` では
入っている。直接動かすとき・`python -m unittest tests.unit...` のときのために、各テストのファイルの先頭で入れている）。
"""
from .paths import SCRIPTS, TOOLS, add_to_sys_path


def ensure_paths() -> None:
    """scripts/（入口とパッケージ aws_iac_diagram）と tools/ を sys.path に入れる（すでにあれば何もしない）。"""
    add_to_sys_path(SCRIPTS, TOOLS)


ensure_paths()
