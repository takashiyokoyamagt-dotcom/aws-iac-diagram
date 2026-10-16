# 共通Agent Skill 開発ガイド
### Windows（VS Code + GitHub Copilot）と GitHub Agentic Workflows で同じSkillを動かす

---

## 0. 前提と結論

### 前提
- Skillは `SKILL.md` と各種スクリプトで構成する
- 実行環境は次の2つ
  - **Windows PC + VS Code + GitHub Copilot**（WSLを使わない利用者もいる）
  - **GitHub Copilot の Agentic Workflows（gh-aw）**（GitHub Actions の ubuntu ランナー）
- 環境ごとに別のSkillを作らず、**1つの共通Skill**にしたい
- Skillの中で **draw.io による描画** を行うことがある

### 結論
1. Skillは **Agent Skills 標準形式（SKILL.md）で1つだけ** 作る
2. **エージェントにはOSに依存しないコマンドを1行だけ実行させ、処理はすべて Python スクリプトの中に入れる**
3. スクリプトの起動は **`uv run`** に統一する
4. **Windows と Linux の両方を CI でテスト**して動作を保証する
5. 配布は **Skill専用リポジトリ（正本）からタグ付きで** 行う

---

## 1. なぜこの構成にするのか

- SKILL.md の形式（Agent Skills 標準）は、VS Code の Copilot、Copilot CLI、Copilot cloud agent などで共通に使える。**共通化が難しいのはスクリプトの実行環境**
- WSLを使わない Windows では、Copilot のエージェントは **PowerShell（多くは 5.1）** でコマンドを実行する。gh-aw では **bash** で実行する
- そのため SKILL.md にシェルの書き方（`&&`、パイプ、`grep`、`$VAR` など）を書くと、どちらかの環境で動かなくなる
- → **シェルに依存する部分をなくし、処理はすべてスクリプト側で吸収する**

---

## 2. 実行基盤：Python + uv

### uv とは
Astral社（Ruff の開発元）が Rust で作った、**Python のツール群を1つにまとめた高速なコマンドラインツール**。

| これまで | uv では |
|---|---|
| Python本体を別途インストール | 必要なバージョンを自動でダウンロード |
| `python -m venv` で仮想環境作成 | 自動で作成・管理 |
| `pip install` | 自動でインストール（非常に高速） |
| `requirements.txt` の管理 | スクリプト内の記述（PEP 723）から解決 |

`uv run scripts/analyze.py` の1行で、Python の準備 → 依存パッケージの導入 → 実行 までを自動で行う。
Windows で起きやすい `python` / `py` / `python3` の名前の違いや、Microsoft Store が開いてしまう問題も避けられる。

### インストール
- **Windows**：`winget install --id=astral-sh.uv -e`
- **Linux / GitHub Actions**：公式インストールスクリプト、または `astral-sh/setup-uv` アクション

### 依存パッケージの書き方（PEP 723）
```python
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6"]
# ///
```

### 他の案との比較

| 案 | Windows利用者の準備 | 評価 |
|---|---|---|
| **Python + uv** | uv のインストール | ◎ 一般的なケースで最善 |
| Deno（TypeScript） | Deno のインストール | ○ チームが TS 中心なら有力。権限を制限して実行できる |
| Go/Rust のビルド済みバイナリ | 不要 | ○ 何もインストールさせられない環境なら最善。ただし変更のたびにビルドが必要 |
| MCP サーバー化 | MCP の設定 | ○ 大規模で、ツールを何度も呼ぶSkill向け。将来の移行先候補 |
| PowerShell スクリプト | 不要 | △ 5.1 と 7 の違い、文字コードの問題で保守が大変 |
| bash と ps1 を両方用意 | — | × 二重管理になる |

---

## 3. リポジトリ構成

```
my-skills/                         ← Skill専用リポジトリ（正本）
├── skills/
│   └── my-skill/
│       ├── SKILL.md
│       ├── scripts/
│       │   ├── analyze.py         ← 本体（OS非依存）
│       │   ├── drawio_export.py   ← draw.io 書き出し
│       │   └── doctor.py          ← 環境チェック
│       └── references/
├── tests/
│   └── fixtures/                  ← 日本語・スペースを含むパスのケースも用意
├── .gitattributes
├── README.md                      ← 利用側に必要な設定（uv、gh-aw の許可設定など）
└── .github/workflows/ci.yml       ← Windows / Linux の両方でテスト
```

---

## 4. SKILL.md の書き方

```markdown
---
name: my-skill
description: ○○を解析してレポートを作る。△△と言われたら使う。
---

# 手順
1. 次のコマンドを**そのまま1行で**実行する（シェルの種類を問わない）:
   `uv run scripts/analyze.py --target <対象パス> --out out/result.json`
2. `out/result.json` を読み、`findings` を重要度順に要約する。
3. スクリプトが終了コード2で終わった場合は、`out/result.json` の `error` を
   ユーザーに伝えて中断する。
4. 失敗した場合は `uv run scripts/doctor.py` を実行し、結果を報告する。

# 禁止事項
- `&&` `|` `grep` `sed` `$(...)` などのシェル機能を使って処理を組み立てない。
  必要な処理はスクリプトのオプションで指定する。

# 実行環境ごとの違い
- `GITHUB_ACTIONS=true` の場合: 結果は safe-outputs で出力する。対話的な確認は行わない。
- それ以外: 結果をユーザーに提示し、変更を加える前に確認を取る。
```

### ポイント
- **コマンドは1行・単一プロセス**。リダイレクトも使わず、出力先は `--out` で指定する
- **結果はファイル（JSON）で受け渡す**。PowerShell 5.1 では標準出力をパイプ等で受けると文字コードが変わることがあるため
- **終了コードの意味を決めておく**（0：成功、1：問題あり、2：実行エラー など）
- frontmatter は標準の **`name` と `description` だけ**にする（特定ツール専用のフィールドは入れない）

---

## 5. スクリプトの作り方

```python
import sys, json, argparse
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent   # Skillからの相対パスで解決

def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")         # cp932対策
    p = argparse.ArgumentParser()
    p.add_argument("--target", required=True)
    p.add_argument("--out", required=True)
    a = p.parse_args()

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        text = Path(a.target).read_text(encoding="utf-8")   # encodingは必ず明示
        result = {"findings": analyze(text)}
        code = 1 if result["findings"] else 0
    except Exception as e:
        result, code = {"error": str(e)}, 2
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2),
                   encoding="utf-8", newline="\n")
    return code

if __name__ == "__main__":
    sys.exit(main())
```

### チェックリスト
- [ ] ファイルの読み書きには必ず `encoding="utf-8"` を指定する
- [ ] パスは `pathlib` で扱う。`/` や `\` を文字列で直接つながない
- [ ] `subprocess` は `shell=True` を使わず、引数をリストで渡す
- [ ] `chmod`、シンボリックリンク、大文字小文字の区別に依存しない
- [ ] 一時ファイルは `tempfile` を使う（`/tmp` を直接書かない）
- [ ] 対話入力を使わない（すべて引数で渡す）
- [ ] 出力は JSON などの構造化形式にする

### .gitattributes
```
* text=auto eol=lf
```

---

## 6. 環境チェック用スクリプト（doctor.py）

次の情報を JSON で出力するスクリプトを用意する。

- OS、Python・uv のバージョン
- 必要な外部ツール（draw.io など）が見つかるか
- Linux の場合 `xvfb-run` があるか
- `GITHUB_ACTIONS` の値

SKILL.md に「失敗したらまず doctor を実行して報告する」と書いておくと、Windows 利用者の環境での問題切り分けが楽になる。

---

## 7. draw.io を使う場合

### 描画（変換）と確認を分けて考える
- **描画（.drawio → PNG/SVG）**：gh-aw のランナーには画面がないため、**画面なしで実行できる作りが必須**
- **確認（目で見る）**：出力された画像を見るだけなので、どこで見てもよい

### 書き出しスクリプトの例
```python
import os, shutil, subprocess, sys
from pathlib import Path

def find_drawio() -> list[str]:
    if sys.platform == "win32":
        exe = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "draw.io" / "draw.io.exe"
        return [str(exe)]
    cmd = [shutil.which("drawio") or "drawio", "--no-sandbox"]
    # Linuxで画面がない場合（gh-awなど）は仮想ディスプレイ上で実行
    if not os.environ.get("DISPLAY") and shutil.which("xvfb-run"):
        cmd = ["xvfb-run", "-a"] + cmd
    return cmd

def export(src: Path, out: Path, fmt: str = "png") -> None:
    subprocess.run(find_drawio() + ["-x", "-f", fmt, "-o", str(out), str(src)], check=True)
```

### 注意点
- draw.io は Electron アプリのため、Linux で画面がないと起動に失敗する → `xvfb-run` を使う
- gh-aw のワークフローでは、事前に draw.io の `.deb` と `xvfb` をインストールし、ネットワーク許可も設定する
- gh-aw で書き出した PNG は、成果物（artifact）や PR コメントとして残すと後から確認できる

### 画像の確認方法

| 方法 | 評価 |
|---|---|
| Windows 側の VS Code で画像ファイルを開く | ◎ WSL 接続中でも Windows の画面に表示される |
| VS Code の Draw.io Integration 拡張で `.drawio` を開く | ◎ 元の図をそのまま確認・編集できる |
| WSLg で Linux 版 draw.io を起動 | ○ Linux 版での見た目を確認したいときだけ |
| WSL にデスクトップ環境全体を入れる | × 不要 |

---

## 8. CI：両OSでの動作を保証する

```yaml
jobs:
  test:
    strategy:
      matrix:
        os: [ubuntu-latest, windows-latest]
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
      - run: uv run --with pytest pytest tests
      - run: uv run skills/my-skill/scripts/analyze.py --target tests/fixtures/sample.txt --out out/r.json
        shell: powershell   # Windowsでは利用者と同じPowerShell 5.1から起動して確認
        if: runner.os == 'Windows'
```

- テストデータに **日本語やスペースを含むパス** を入れて、Windows 特有の問題を早めに見つける

---

## 9. 開発環境（Windows + WSL）

- 開発は Windows 上でも WSL 上でもよい（両OSの動作は CI が保証する）
- WSL を使う場合
  - リポジトリは WSL 側のファイルシステム（`~/work/...`）に置く。`/mnt/c/...` は遅く、権限や改行の問題が出る
  - VS Code は Windows 側で起動し、WSL 拡張機能で接続する
  - Linux の GUI アプリが必要なら **WSLg**（標準機能、`wsl --update` で有効）を使う。デスクトップ環境全体は不要
- **WSL を使わない利用者がいるので、Windows の PowerShell での動作確認も必ず行う**
  - WSL = gh-aw（Linux）側の確認用、PowerShell = Windows 利用者側の確認用 と使い分ける

---

## 10. 配布

| 利用先 | 読み込み方 |
|---|---|
| VS Code + Copilot（Windows） | プロジェクトの `.github/skills/` に置く、または個人用 Skill として `~/.copilot/skills/` などに置く |
| Agentic Workflows（gh-aw） | APM（`shared/apm.md` の `packages:`）や `gh skill install` でタグを指定して読み込む |

- 対象リポジトリが1つだけなら、そのリポジトリの `.github/skills/` に直接置くのが最も簡単
- 複数リポジトリで使うなら Skill 専用リポジトリにタグ（例：`v1.2.0`）を付けて参照する
- gh-aw 側では、ワークフローの frontmatter で `uv` などのコマンド実行とネットワークアクセスを許可する（Skill ではなく**ワークフロー側の設定**なので README に記載しておく）

---

## 11. 開発の流れ

1. Skill 専用リポジトリで開発する（ローカル確認時は `~/.copilot/skills/` から開発フォルダへリンクを張ると即反映される）
2. CI で `windows-latest` と `ubuntu-latest` のテストを実行する
3. タグを付けてリリースする
4. 利用側（VS Code / gh-aw）がタグを指定して読み込む

---

## 12. 将来の拡張

- Skill が大きくなり、エージェントがツールを何度も呼び出すようになったら **MCP サーバー化** を検討する
  - SKILL.md は「どのツールをどの順で使うか」を説明する手順書になる
  - 最初は uv で作り、必要になったら移行するのが現実的
