# aws-iac-diagram 計画書

- 作成日: 2026-10-14
- 状態: **フェーズ0 実施中**（2026-10-15）。再開時は [HANDOFF.md](HANDOFF.md) から読むこと
- 目的: Terraform と CloudFormation のコードを読み込み、AWS 構成図を draw.io・Mermaid・PNG の3形式で出力する Claude Code 用の SKILL を作る

---

## 1. 確定した要件と決定事項

| 項目 | 決定内容 |
|---|---|
| 入力（Terraform） | `.tf` を python-hcl2 で静的に解析するのが基本。`terraform show -json` の plan JSON があれば、そちらを優先して使う |
| 入力（CloudFormation） | YAML と JSON の両方。SAM と CDK の出力（`cdk.out` 配下のテンプレート）も対象 |
| 出力 | `.drawio`（これを正本とする）、`.mmd`（Mermaid）、`.png` の3形式 |
| 置き場所 | 独立した private リポジトリ `takashiyokoyamagt-dotcom/aws-iac-diagram`。`~/.claude/skills/aws-iac-diagram` から symlink で参照する |
| インストール（許可済み） | draw.io Desktop（brew cask）、`@mermaid-js/mermaid-cli`（npm）、`python-hcl2`・`defusedxml`（venv に入れる） |
| ダウンロード（許可済み） | draw.io の `Sidebar-AWS4.js`（Apache-2.0）、awslabs/aws-icons-for-plantuml の Mermaid 用アイコン JSON（AWS アイコンの利用規約に従う） |
| ライセンス上の注意 | TerraVision は AGPL-3.0 なので、考え方だけを参考にしてコードは流用しない。awslabs のスキル（Apache-2.0）や vidanov のスキル（MIT）から取り入れた知見は、NOTICE に出典を明記する |

環境の確認結果（2026-10-14、Mac）:
- インストール済み: Node/npm、Python 3.14、PyYAML、gh
- 未インストール: draw.io、mmdc（mermaid-cli）、python-hcl2、terraform、graphviz

### 1.1 Windows への移行（2026-10-15）

開発環境を Windows 11 に移した。Mac と Windows の両方で動くことを前提にする。

| 項目 | Mac | Windows |
|---|---|---|
| draw.io Desktop | `brew install --cask drawio` | `winget install JGraph.Draw`（v32.4.1、`%LOCALAPPDATA%\Programs\draw.io\draw.io.exe`） |
| SKILL の登録 | symlink（`ln -s`） | ジャンクション（`mklink /J`。管理者権限も開発者モードも不要） |
| venv の Python | `.venv/bin/python` | `.venv\Scripts\python.exe`（3.12.10） |
| PNG 書き出し | `export_png.sh` の予定だった | **`export_png.py` に変更**し、両 OS で同じスクリプトを使う。draw.io の実行ファイルの場所は OS ごとに探す |

- スクリプトは Python で書き、シェルスクリプトは作らない。パスは `pathlib` で扱う。
- 生成するテキストファイルは UTF-8・LF で書く（`newline="\n"`）。git の自動改行変換で C5（バイト単位で同じ出力）が崩れないよう、`.gitattributes` で LF に固定する。
- Windows で確認済み: draw.io `-x -f png --disable-gpu` で PNG が出る。`mmdc` 12.0.0 で architecture-beta の PNG が出る。

---

## 2. 調査で分かったこと（計画の根拠）

### 2.1 参考事例

- **Classmethod の記事**（https://dev.classmethod.jp/articles/trial-and-error-aws-diagram-agent-skills/ ）
  - アイコン定義と検索スクリプト `find_aws_icon.py` を用意したことで、読み込むトークンが約1/18に減った
  - レイアウトのルールを具体的に書くと品質が安定した
  - スキルを直すたびに同じプロンプトで再生成して比べた
  - それでも出来上がりは「ドラフト止まり」だった
- **awslabs/agent-plugins の deploy-on-aws / aws-architecture-diagram**（Apache-2.0。AWS 公式の Diagram MCP Server の後継）
  - IaC は LLM に直接読ませている
  - 座標も LLM が決めている
  - PostToolUse フックで XML を検証し、決定論的な修正を当てている
  - 重なりの検査はない
- **vidanov/aws-architecture-diagram-skill**（MIT）
  - 壊れるステンシルの代替表を持っている（例: `dynamodb_table` は空の箱になるので `dynamodb` を使う）
  - サービスの改名に対応する表を持っている
  - resourceIcon とそれ以外とで strokeColor の規則が逆になる
- **jgraph/drawio-mcp**（draw.io 公式、Apache-2.0）
  - `drawio --layout` で ELK を使える
  - `libavoid` は頂点を動かさずに辺だけを迂回させる
  - Mermaid から直接 `-e` 付きで PNG を出すとクラッシュするので、一度 `.drawio` を経由する
- **Agents365-ai/drawio-skill**（MIT）
  - 約15ノードを超えたら Graphviz で自動レイアウトする
  - `--tune` で上下方向と左右方向を両方試し、スコアで選ぶ
  - 「目視だけでは幾何学的な欠陥を見逃すし、存在しない欠陥を幻視もする」
- **TerraVision**（AGPL。考え方のみ参考）
  - 型ごとの統合・削除・移動の表を持っている
  - VPC → AZ → Subnet の中間ノードを挿入している
  - SG はポートのラベル付きの辺に変換している
  - `docs/LEARNINGS_DRAWIO_NATIVE.md` に多数の失敗知見がある（下の 2.2）
- **InfraMap**（MIT）
  - 型ごとに「ノードにする型」と「辺にする型」の表を持っている
  - 中間の型は1本の辺に畳んでいる
- **cfn-diagram**
  - Ref、GetAtt、Sub、ImportValue を再帰的に集めている（DependsOn は見ていない）
  - SAM の Events は向きを逆にした Invoke 辺として描いている
- **pagopa/dx generate-terraform-module-diagram**
  - Mermaid のアイコンパックを使っている
  - アイコンノードに `classDef` で塗りを付けるとアイコンが隠れる

### 2.2 失敗知見（実装時に必ず守ること）

**アイコンとスタイル**
1. アイコン名は推測しない。`Sidebar-AWS4.js` から機械的に作った辞書だけを使う。`stencils/aws4.xml` から作った名前は壊れる。
2. シェイプには3つの系統があり、それぞれ指定が違う。
   - 直接シェイプ: 48x48、fillColor を指定、`strokeColor=none`
   - resourceIcon: 78x78、`strokeColor=#ffffff`
   - group: grIcon を使う
3. fillColor を省くとアイコンが見えなくなる。

**座標と配置**
4. 子要素の座標は「直接の親」からの相対座標になる。
5. Graphviz のスプライン制御点を waypoint に流用すると、線がコンテナを突き抜ける。`orthogonalEdgeStyle` にして waypoint を置かず、ルーティングは draw.io に任せる。
6. レイアウトを整えるための不可視エッジを、実在の辺として出力しないこと。

**XML の書き方**
7. `<mxfile><diagram><mxGraphModel><root>` の入れ子と、id=0／id=1 のセルは必須。エッジには `mxGeometry` が必要。
8. `background` 属性を付けるとダークモードが崩れる。ラベルの背景を white にしない。
9. XML コメントの中に `--` を書かない。圧縮した XML にしない。
10. 画像を埋め込むときは `data:image/png,<base64>` の形式にする（`;base64` を付けない）。

**書き出し**
11. PNG にするとグループの外が黒くなることがある。全体を覆う背景矩形を最背面に置いて防ぐ。
12. `drawio -x` について
    - サンドボックス内では、何も出力せずに終わることがある
    - `--scale` を付けるとハングするという issue がある（#1774）
    - GPU エラーが出る場合は `--disable-gpu` を付ける
    - 出力サイズが0なら失敗として扱う
    - `--timeout` は v31.5.2 以降で使える

**CloudFormation の読み込み**
13. `!Ref` などの短縮タグは、通常の YAML パーサではエラーになる。awscli の yamlhelper と同じ方式で、`Fn::*` の長い形式に正規化する。

**Mermaid**
14. architecture-beta の組み込みアイコンは5種類しかなく、6〜8ノードを超えると読めなくなる。
15. 存在しないアイコン名は「?」で表示される。
16. GitHub では独自のアイコンパックが効かない。
17. ARN をノードIDにすると壊れる。

### 2.3 調査から導いた設計原則

- **IaC の解析・配置・検証はスクリプトで決定論的に行う。** LLM が担当するのは、判断（あいまいな点の確認）、ラベル付け、最終の目視確認、説明文の作成だけにする。
- **中間表現（IR、JSON）を正本にする。** draw.io・Mermaid・PNG はすべて IR から生成する。

---

## 3. アーキテクチャ

```
入力の自動判定
 ├ Terraform plan JSON（あれば優先） ─┐
 ├ Terraform .tf（python-hcl2）     ─┼→ ① アダプタ → IR（ノード・辺・入れ子・由来）
 └ CloudFormation / SAM / cdk.out   ─┘
 ② 正規化（型別の設定表）: 統合 / 非表示 / 移動、AZ の挿入、関係リソースの辺への変換、SG を辺に変換
 ③ 配置: 枠と階層はスクリプトでグリッド計算。候補を複数作り、スコアで選ぶ（B1）
 ④ 出力: .drawio（正本）、.mmd（アイコン付き版と GitHub 表示用の素の版）、.png
 ⑤ 検証: XML 構造、アイコンの辞書照合、重なりと貫通の数値判定、IR との突き合わせ、網羅（A6）
 ⑥ LLM: あいまいな点を一括で確認、ラベル付け、別のサブエージェントによる目視採点（C6）、説明 .md の作成
```

### リポジトリ構成（予定）

```
aws-iac-diagram/
├── PLAN.md  HANDOFF.md  README.md  NOTICE
├── aws-iac-diagram/                 ← ~/.claude/skills/aws-iac-diagram からの symlink 先
│   ├── SKILL.md
│   ├── references/
│   │   ├── resource-catalog.md      # aws_* ⇔ AWS::* ⇔ アイコン ⇔ 扱い（描く/統合/非表示/移動）
│   │   ├── relation-resources.md    # 辺に変換する「関係リソース」の表（A1）
│   │   ├── edge-rules.md            # 型の組ごとの向き・ラベル・確信度（A2, A3）
│   │   ├── module-summaries.md      # 公開モジュールの中身の要約（A5）
│   │   ├── layout-guidelines.md
│   │   └── icons/*.md               # カテゴリ別のアイコン定義（生成物）
│   ├── assets/                      # Mermaid 用のアイコン JSON など
│   └── scripts/
│       ├── adapters/{tf_plan,tf_hcl,cfn}.py
│       ├── evaluate.py              # 変数・条件の評価（A4）
│       ├── normalize.py  layout.py  emit_drawio.py  emit_mermaid.py
│       ├── export_png.py  validate.py  find_aws_icon.py
│       ├── build_icon_catalog.py    # Sidebar-AWS4.js から辞書を再生成
│       └── check_icons.py           # 全アイコンを描画して壊れたものを検出（C2）
└── aws-iac-diagram-workspace/
    ├── fixtures/{tf,cfn}/…  expected/*.ir.json
    └── evals/
```

---

## 4. 精度向上策（ユーザーがおすすめどおり採用）

### A. 図の正しさ
- **A1 関係リソースを辺に変換する**
  - 対象: `aws_lambda_event_source_mapping`、`aws_sns_topic_subscription`、`aws_lb_listener`、`aws_lb_target_group_attachment`、`aws_lambda_permission`、Route53 の alias、EventBridge の target、CloudFront の origin、API Gateway の integration_uri など
  - CloudFormation の同等の型も同じ表で扱う
- **A2 矢印の向きを型の組で決める**
  - Terraform の参照は依存の向きを表し、データの流れとは逆になることがある
  - 「参照元の型 × 参照先の型 → 向き・ラベル」の表で決める
- **A3 確信度を3段階にする**

  | 確信度 | 根拠 | 描き方 |
  |---|---|---|
  | 確定 | 直接の参照 | 実線 |
  | 導出 | A1 の変換、SG から導いたもの | 実線 + ラベル |
  | 推定 | IAM の Resource ARN、環境変数の文字列一致 | 破線 + 凡例。既定では非表示にもできる |

  推定した辺は、根拠を説明 .md に一覧で載せる。
- **A4 変数と条件を評価する**
  - Terraform: tfvars、`*.auto.tfvars`、default、単純な locals
  - CloudFormation: Parameters の default、Conditions、`Fn::If`、`Fn::FindInMap`
  - 環境が複数ある場合は、最初に1回だけユーザーに確認する
- **A5 公開モジュールの要約表を持つ**
  - まず `terraform-aws-modules` の vpc／eks／rds／alb の4つから始める
  - ローカルモジュールは再帰的に読み込む
- **A6 網羅を保証する**
  - 入力の全リソースを「描画 / 統合先 / 非表示（規則ID） / 未知の型」のいずれかに分類し、`coverage.md` に出力する
  - 分類が漏れたリソースがあれば検証エラーにする

### B. 見やすさ
- **B1 配置の候補を複数作り、スコアで選ぶ**
  - 候補: 左右方向と上下方向、同じ階層の中での並び順
  - スコアの指標: 辺の交差数、折れ数、総延長、縦横比
- **B2 詳細度の違う3つのビューを出す**
  - 全体図、ネットワーク図、詳細図
  - 大きい構成は VPC 単位やスタック単位で図を分割する
- **B3 ラベルの付け方**
  - `Name` タグ → `name` 属性 → アドレスの順で採用する
  - 長いものは省略規則で縮める。日本語のラベルも選べるようにする

### C. 検証と評価
- **C1 既存ツールで検算する**: CloudFormation は `cfn-lint --build-graph`（MIT-0）の依存グラフと突き合わせ、差分をレポートする
- **C2 壊れたアイコンを自動検出する**: 辞書の全アイコンを1枚に描画し、画素のばらつきから空箱・黒・単色を判定する。draw.io を更新したら再実行する
- **C3 実在の構成で試験する**（評価フェーズで実施）: `terraform-aws-modules` の examples と、aws-samples の CloudFormation テンプレートを数本使う
- **C4 変異テスト**（評価フェーズで実施）: 入力に機械的な変更を加え、図がそれに追従するかを確認する
- **C5 決定論的な出力**
  - ID はリソースのアドレスから作り、出力の順序を固定する
  - 同じ入力からは同じファイルが出るようにする（git で差分を見られるように）
- **C6 第三者による採点**: 最終の目視確認は、生成したエージェントとは別のサブエージェントが観点表で採点する

### 見送り
- 手で直した座標を、図を作り直したときに保持する機能（Agents365 の sync 相当）。第1版の対象外とする。

---

## 5. フェーズと完了基準

| # | 内容 | 完了基準 |
|---|---|---|
| 0 | ・ツールのインストール（venv、draw.io、mmdc）<br>・symlink の作成<br>・テスト用構成を5種類作る（3層 ALB/ECS/RDS、サーバーレス API GW/Lambda/DynamoDB、VPC+NAT+エンドポイント、モジュール利用、RAG）。それぞれ Terraform 版と CloudFormation 版を用意する<br>・各構成の正解 IR を作る<br>・アイコン辞書を生成し、壊れたアイコンを検出する（C2） | 正解 IR が第三者レビュー済み。辞書の生成と C2 が通る |
| 1 | ・IR スキーマを決める<br>・CloudFormation アダプタ: 短縮タグ、Ref／GetAtt／Sub（`${}`）／ImportValue／DependsOn、SAM の Events、cdk.out<br>・A4（CloudFormation 側の評価）<br>・C1（cfn-lint との突き合わせ） | テストが通る。cfn-lint との差分がすべて説明できる |
| 2 | ・Terraform アダプタ: plan JSON の `configuration` にある参照を優先し、なければ .tf<br>・count／for_each のうち値が決まらないものは「×N」として扱う<br>・A4（Terraform 側の評価）<br>・A5（4モジュール） | 同じ構成の Terraform 版と CloudFormation 版が同じ IR になる |
| 3 | 正規化: 型別の表、A1、A2、A3、A6、AZ の挿入、SG を辺に変換、B3 | 未分類が0件。正解 IR に対する再現率と適合率が基準を満たす |
| 4 | draw.io の出力と配置<br>・相対座標、辺と図形の2レイヤ、背景矩形<br>・B1、B2、C5<br>・ELK が入れ子のコンテナを保てるか試し、採否を決める | 重なりと貫通が0件。同じ入力を再実行してもバイト単位で同じになる |
| 5 | ・Mermaid の出力（アイコン付き版と GitHub 表示用版。ノードが多いときは flowchart に切り替える）<br>・PNG の書き出し<br>・validate.py（必要なら PostToolUse フックも） | 3形式とも生成でき、検証が通る |
| 6 | ・SKILL.md の作成<br>・評価: C3、C4、C6、3回実行したときのばらつき<br>・第三者レビューのサイクル | 評価基準を満たす（基準値はフェーズ0で決める）。README と NOTICE を整える |

### 進め方
- 実装はサブエージェントが行い、そのレビューは別のサブエージェントが第三者として行う（ほかのスキルと同じやり方）
- 区切りごとに HANDOFF.md を更新し、main へ反映する

---

## 6. 主な出典
- https://dev.classmethod.jp/articles/trial-and-error-aws-diagram-agent-skills/
- https://dev.classmethod.jp/articles/claude-code-awslabs-aws-architecture-diagram/
- https://dev.classmethod.jp/articles/claude-code-skill-aws-architecture-diagram/
- https://dev.classmethod.jp/articles/claude-code-trying-out-drawio-skill-for-aws-architecture/
- https://github.com/awslabs/agent-plugins/tree/main/plugins/deploy-on-aws
- https://github.com/vidanov/aws-architecture-diagram-skill
- https://github.com/jgraph/drawio-mcp
- https://github.com/Agents365-ai/drawio-skill
- https://github.com/oharu121/oharu-commands-skills-gems
- https://github.com/nirmal84/aws-arch-drawio-plugin
- https://github.com/patrickchugh/terravision（AGPL。参考は考え方のみ）
- https://github.com/cycloidio/inframap
- https://github.com/ljacobsson/cfn-diagram
- https://github.com/awslabs/diagram-as-code
- https://github.com/awslabs/aws-icons-for-plantuml
- https://blog.serverworks.co.jp/cfn-python
