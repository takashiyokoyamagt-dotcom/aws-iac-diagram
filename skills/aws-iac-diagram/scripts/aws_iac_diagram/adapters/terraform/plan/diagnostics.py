"""plan JSON の側の診断の部品。
"""
from __future__ import annotations


ROOT_OTHER_DRIVE_MESSAGE = "root is on another drive; written as the file or folder name only"


def diag(code: str, address: str, path: str, message: str) -> dict:
    return {"level": "info", "code": code, "address": address, "path": path, "message": message}
