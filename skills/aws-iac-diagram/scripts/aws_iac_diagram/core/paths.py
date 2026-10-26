"""SKILL の同梱ファイルの場所（スクリプトが実行時に開くもの）。

場所の決め方をここ 1 か所にする（各所に `parents[N]` や `.parent.parent` を書かない）。このファイルは
`<SKILL>/scripts/aws_iac_diagram/core/paths.py` にある前提で、SKILL のフォルダを自分の場所から決める
（作業ディレクトリや環境変数に依らない。SKILL のフォルダを日本語やスペースを含む場所に、別の深さに置いても同じ）。

- `data/` : スクリプトが読むデータ（スキーマ、アイコンの辞書、モジュールの要約表）。1 ファイル 1 単位。
- `references/` : エージェントが読む文書（手順書）の置き場。今は README.md だけ（規則表はスクリプトが読むデータなので `data/rules/` にある）。

標準ライブラリだけを使い、ほかの層を import しない（core の決まり）。
"""
from __future__ import annotations

from pathlib import Path

# core → aws_iac_diagram → scripts → SKILL
SKILL_DIR = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = SKILL_DIR / "scripts"
ASSETS_DIR = SKILL_DIR / "assets"
DATA_DIR = SKILL_DIR / "data"
REFERENCES_DIR = SKILL_DIR / "references"

SCHEMAS_DIR = DATA_DIR / "schemas"
IR_SCHEMA = SCHEMAS_DIR / "ir.schema.json"
IR_RAW_SCHEMA = SCHEMAS_DIR / "ir-raw.schema.json"

ICONS_DIR = DATA_DIR / "icons"
ICON_CATALOG = ICONS_DIR / "catalog.json"
ICON_BROKEN = ICONS_DIR / "broken.json"

# <モジュール>/v<major>.md（モジュールの要約表）と、IAM だけを作るモジュールの一覧 iam-only-sources.md
MODULE_SUMMARIES_DIR = DATA_DIR / "module-summaries"
IAM_ONLY_SOURCES = MODULE_SUMMARIES_DIR / "iam-only-sources.md"

# 規則表（TOML。読み込みと検査は core/rules.py。説明の文章はリポジトリの docs/spec/rules/）。
# types/*.toml と relations.toml・edges.toml・refs.toml・placement.toml（README.md は読まない）
RULES_DIR = DATA_DIR / "rules"
RULES_TYPES_DIR = RULES_DIR / "types"
