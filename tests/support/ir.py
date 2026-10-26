"""正解 IR（aws-iac-diagram-workspace/expected）を読む。"""

import json

from support.paths import EXPECTED


def load(name="three-tier"):
    return json.loads((EXPECTED / f"{name}.ir.json").read_text(encoding="utf-8"))
