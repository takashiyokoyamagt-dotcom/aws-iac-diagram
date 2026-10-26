## 3. 辺

```json
{"id": "alb/demo-alb->ecs_service/demo-app", "from": "alb/demo-alb", "to": "ecs_service/demo-app",
 "kind": "request", "label": "HTTP 8080", "confidence": "derived"}
```

| フィールド | 必須 | 内容 |
|---|---|---|
| `id` | ○ | `<from>-><to>` |
| `from`, `to` | ○ | ノードの id。**向きはデータ（要求）の流れ**で、参照の向きではない（A2） |
| `kind` | ○ | `request`（同期の呼び出し・HTTP）／`event`（非同期の通知・イベント・ストリーム・発行）／`data`（データストアの読み書き）／`route`（ルートテーブルによる経路）／`network`（SG で通信が許されているだけで、他の根拠が無いもの） |
| `label` | ○ | 空文字ならラベルなし。書式は `edge-rules.md` の「ラベル」 |
| `confidence` | ○ | `confirmed`（直接の参照）／`derived`（関係リソースの変換 A1、SG からの導出、型の定義から決まる値）／`inferred`（IAM の Resource ARN、文字列の一致）。A3 |
| `note` | | 判断理由 |

- 順序付きの組（from, to）ごとに辺は1本（E-MERGE）。根拠が複数あるときは、確信度は強い方、`kind` と `label` は規則の優先順で決める。
- 自己ループは作らない。
- 入れ子（parent）は辺にしない。
