# IranHeart API 接口文档

Base URL: `http://localhost:8000`

> **通用响应格式**: 除 `/health` 和直接定义的 Tier2/Tier3/Entity 接口外，所有接口统一使用 `ok()` 封装：
> ```json
> { "code": 0, "data": { ... }, "message": "success" }
> ```
> 错误时：`{"code": 40001, "data": null, "message": "错误描述"}`

> **CMD 格式**: 以下 curl 命令均为 Windows CMD 单行格式（JSON 内双引号用 `\"` 转义）。Git Bash / PowerShell 可去掉 `\"` 改用单引号。

---

## 1. 健康检查

```
GET /health
```

```cmd
curl -s http://localhost:8000/health
```

**响应**:
```json
{ "status": "ok", "service": "c_layer_api" }
```

---

## 2. 系统状态

### GET /api/status

```cmd
curl -s http://localhost:8000/api/status
```

**响应** (`data` 字段):
| 字段 | 类型 | 说明 |
|------|------|------|
| `state` | string | 主状态：`SLEEPING` / `WORKING` / `ORGANIZING` |
| `states` | string[] | 所有当前激活的状态 |
| `queues` | object | 各队列积压消息数，如 `{"opportunities": 2}` |
| `video_processing` | object\|null | 视频处理状态 |
| `reflecting` | bool | 是否正在反思 |
| `layer_status` | object | 各层运行状态 |
| `updated_at` | string | ISO 时间戳 |

**状态切换规则**:
- **SLEEPING**: 队列为空 且 未在反思
- **WORKING**: 队列中有积压消息 或 视频正在处理
- **ORGANIZING**: 反思进行中（`_reflecting = True`）

### WebSocket /api/status/ws

每 2 秒推送系统状态（同上 `data` 结构），支持客户端发送 `{"type": "ping"}` 心跳。

---

## 3. 用户指令

### POST /api/command

```cmd
curl -s -X POST http://localhost:8000/api/command -H "Content-Type: application/json" -d "{\"text\": \"提醒我下午3点开会\"}"
```

**请求体** (Pydantic `CommandRequest`):
| 字段 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `text` | string | 是 | — | 指令内容 |
| `type` | string | 否 | `"text"` | 指令类型：`text` / `voice` |

**响应** (`data`):
```json
{
  "command_id": "cmd_20260423_164500_a2b269",
  "status": "processing",
  "message": "指令已接收，正在生成行动卡片"
}
```

**说明**: 指令走 `command_opportunities` → `command_execution_plans` 优先路径，跳过 D 层决策引擎排队。

---

## 4. 视频上传

### POST /api/video/upload

```cmd
curl -s -X POST http://localhost:8000/api/video/upload -F "file=@D:\path\to\video.mp4" -F "source=camera"
```

**请求体** (multipart/form-data):
| 字段 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `file` | file | 是 | — | 视频文件（仅 .mp4） |
| `source` | string | 否 | `"camera"` | 来源标识 |

**响应** (`data`):
```json
{
  "job_id": "job_20260423_154343_08f75c",
  "status": "processing",
  "file_size_mb": 50.6,
  "created_at": "2026-04-23 15:43:43.710114"
}
```

### GET /api/video/status/{job_id}

```cmd
curl -s http://localhost:8000/api/video/status/job_20260423_154343_08f75c
```

**路径参数**: `job_id`

**响应** (`data`):
```json
{
  "job_id": "...",
  "status": "completed",
  "file_size_mb": 50.6,
  "events_generated": 0,
  "created_at": "2026-04-23 15:43:43.710114",
  "completed_at": null
}
```

**错误**: `code: 40401` — 任务不存在

### GET /api/video/jobs

```cmd
curl -s "http://localhost:8000/api/video/jobs?page=1&page_size=10"
```

**查询参数**:
| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `page` | int | 1 | 页码 |
| `page_size` | int | 10 | 每页数量 |

**响应** (`data`):
```json
{
  "total": 4,
  "page": 1,
  "page_size": 10,
  "jobs": [ { "job_id": "...", "status": "...", ... } ]
}
```

---

## 5. 行动卡片

### GET /api/actions

```cmd
curl -s "http://localhost:8000/api/actions?status=pending&page_size=20"
```
```cmd
curl -s "http://localhost:8000/api/actions?source=command"
```
```cmd
curl -s "http://localhost:8000/api/actions?source=pipeline&page_size=5"
```
```cmd
curl -s "http://localhost:8000/api/actions?status=all"
```

**查询参数**:
| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `status` | string | `"pending"` | `pending` / `confirmed` / `rejected` / `all` |
| `source` | string | `"all"` | `pipeline` / `command` / `all` |
| `page` | int | 1 | 页码 |
| `page_size` | int | 20 | 每页数量 |

**响应** (`data`):
```json
{
  "total": 29,
  "actions": [
    {
      "id": "act_1776933906749_rojo3x",
      "source": "command",
      "type": "calendar",
      "title": "calendar+voice_feedback 建议",
      "content": "...",
      "confidence": 0.8,
      "status": "pending",
      "context": { "trigger_summary": "..." },
      "created_at": "2026-04-23 08:45:06.749000"
    }
  ]
}
```

### PUT /api/actions/{action_id}

确认或拒绝行动卡片。

```cmd
curl -s -X PUT http://localhost:8000/api/actions/act_1776933906749_rojo3x -H "Content-Type: application/json" -d "{\"decision\": \"confirmed\"}"
```
```cmd
curl -s -X PUT http://localhost:8000/api/actions/act_1776930425152_ciesyg -H "Content-Type: application/json" -d "{\"decision\": \"rejected\"}"
```

**请求体**:
| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `decision` | string | 是 | `confirmed` 或 `rejected` |

**响应** (`data`):
```json
{ "id": "act_1776933906749_rojo3x", "status": "confirmed", "executed_at": "2026-04-23T16:47:16.003680" }
```

**错误**: `code: 40401` — 行动卡片不存在 | `code: 40001` — decision 值无效

### WebSocket /api/actions/ws

E 层产出行动卡片时实时推送 `{"type": "new_action", "data": <action_dict>}`，支持 `{"type": "ping"}` 心跳（30 秒超时）。

---

## 6. 用户画像 (Tier1)

### GET /api/tier1/{user_id}

```cmd
curl -s http://localhost:8000/api/tier1/default_user
```

**响应** (`data`):
```json
{
  "user_id": "default_user",
  "critical_facts": {
    "preferences": [ { "id": "...", "text": "...", "source": "system|user" } ],
    "habits": [],
    "health_constraints": [],
    "core_goals": [],
    "relationships": []
  },
  "updated_at": "2026-04-23T16:46:00.000000"
}
```

> 未找到用户时返回空画像（5 个空分类），而非 404。

### PUT /api/tier1/{user_id}

添加、更新或删除画像条目。

**请求体**:
| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `category` | string | 是 | `preferences` / `habits` / `health_constraints` / `core_goals` / `relationships` |
| `action` | string | 是 | `add` / `update` / `delete` |
| `item` | object | 是 | 见下表 |

**action 与 item 对应关系**:

| action | item 必填字段 | 说明 |
|--------|-------------|------|
| `add` | `{ "text": "..." }` | id 和 source 自动生成 |
| `update` | `{ "id": "...", "text": "..." }` | 更新文本内容，id 不变 |
| `delete` | `{ "id": "..." }` | 按 id 删除条目 |

**示例**:

添加：
```cmd
curl -s -X PUT http://localhost:8000/api/tier1/default_user -H "Content-Type: application/json" -d "{\"category\": \"preferences\", \"action\": \"add\", \"item\": {\"text\": \"喜欢喝茶\"}}"
```

更新：
```cmd
curl -s -X PUT http://localhost:8000/api/tier1/default_user -H "Content-Type: application/json" -d "{\"category\": \"preferences\", \"action\": \"update\", \"item\": {\"id\": \"user_e7d55919\", \"text\": \"喜欢喝咖啡\"}}"
```

删除：
```cmd
curl -s -X PUT http://localhost:8000/api/tier1/default_user -H "Content-Type: application/json" -d "{\"category\": \"preferences\", \"action\": \"delete\", \"item\": {\"id\": \"user_e7d55919\"}}"
```

**错误**: `code: 40001` — 无效分类/操作/缺少字段 | `code: 40401` — 条目 id 不存在

---

## 7. 反思系统

### GET /api/reflect/config

```cmd
curl -s http://localhost:8000/api/reflect/config
```

**响应** (`data`):
```json
{
  "schedule_times": ["00:00", "14:00", "20:00"],
  "max_daily_reflections": 3,
  "min_interval_minutes": 60,
  "today_reflection_count": 1,
  "last_reflection_at": "2026-04-23"
}
```

### PUT /api/reflect/config

向后兼容——覆盖为单个调度时间点。

```cmd
curl -s -X PUT http://localhost:8000/api/reflect/config -H "Content-Type: application/json" -d "{\"schedule_time\": \"02:00\"}"
```

**请求体**:
| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `schedule_time` | string | 是 | 格式 `HH:MM`，覆盖所有已有时间点 |

**响应** (`data`): `{ "schedule_times": ["02:00"] }`

### POST /api/reflect/schedule

添加一个调度时间点。

```cmd
curl -s -X POST http://localhost:8000/api/reflect/schedule -H "Content-Type: application/json" -d "{\"time\": \"14:00\"}"
```

**请求体**:
| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `time` | string | 是 | 格式 `HH:MM` |

**错误**: `code: 40001` — 时间已存在 / 超过 max_daily_reflections 上限 / 格式错误

### DELETE /api/reflect/schedule

删除一个调度时间点。

```cmd
curl -s -X DELETE http://localhost:8000/api/reflect/schedule -H "Content-Type: application/json" -d "{\"time\": \"14:00\"}"
```

**请求体**:
| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `time` | string | 是 | 格式 `HH:MM` |

**错误**: `code: 40001` — 时间不存在

### POST /api/reflect/trigger

手动触发反思，不受最大次数和最小间隔限制。

```cmd
curl -s -X POST http://localhost:8000/api/reflect/trigger -H "Content-Type: application/json" -d "{\"enable_tier1_llm\": true}"
```

**请求体**:
| 字段 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `enable_tier1_llm` | bool | 否 | `true` | 是否启用 Tier1 LLM 更新 |

**响应** (`data`):
```json
{
  "triggered": true,
  "message": "反思已完成",
  "tier2_written": 5,
  "labels_updated": 3,
  "tier1_updated": true
}
```

**错误**: `code: 40901` — 反思正在进行中

### GET /api/reflect/history

```cmd
curl -s "http://localhost:8000/api/reflect/history?page=1&page_size=10"
```

**查询参数**:
| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `page` | int | 1 | 页码 |
| `page_size` | int | 10 | 每页数量 |

**响应** (`data`):
```json
{
  "total": 7,
  "records": [
    {
      "id": 7,
      "triggered_at": "2026-04-23 08:24:48.586711",
      "trigger_type": "auto",
      "tier3_events": 44,
      "tier2_written": 17,
      "labels_updated": 1,
      "names_updated": 0,
      "tier1_updated": true,
      "duration_seconds": 145
    }
  ]
}
```

> `trigger_type` 取值：`manual`（手动触发）/ `auto`（调度器自动触发）

---

## 8. 记忆查询

### GET /api/tier2/{entity_id}

获取长期记忆。

```cmd
curl -s http://localhost:8000/api/tier2/entity_0001?limit=10
```

**路径参数**: `entity_id`
**查询参数**: `limit` (int, 默认 10)

**响应** (直接返回数组，无 `ok()` 封装):
```json
[
  { "memory_id": "...", "memory_text": "...", "base_importance": 0.8, "created_at": "..." }
]
```

### GET /api/tier3/recent

获取短期事件。

```cmd
curl -s "http://localhost:8000/api/tier3/recent?limit=20"
```

**查询参数**: `limit` (int, 默认 20)

**响应** (直接返回数组，无 `ok()` 封装):
```json
[
  {
    "semantic_event_id": "...",
    "resolved_entity_id": "...",
    "start_ts": "...",
    "end_ts": "...",
    "semantic_type": "...",
    "summary": "...",
    "dialogue_act": "...",
    "platform_hint": "...",
    "ui_thread_hint": "...",
    "extra_slots_json": "..."
  }
]
```

### GET /api/entity/{entity_id}

获取实体信息。

```cmd
curl -s http://localhost:8000/api/entity/entity_0001
```

**错误**: 404 — 实体不存在 | 500 — 内部错误

### GET /api/entity/list

列出所有实体（不返回 embedding 向量）。

```cmd
curl -s http://localhost:8000/api/entity/list
```

**错误**: 500 — 内部错误

### GET /api/stats

全局统计。

```cmd
curl -s http://localhost:8000/api/stats
```

**响应**:
```json
{ "total_entities": 5, "with_face_embedding": 4, "with_voice_embedding": 1, "with_both": 5 }
```

---

## 常用测试流程

### 完整管线测试（视频 → 行动卡片）

```cmd
curl -s -X POST http://localhost:8000/api/video/upload -F "file=@D:\path\to\video.mp4" -F "source=camera"
```

等待约 30 秒后：

```cmd
curl -s "http://localhost:8000/api/actions?source=pipeline&page_size=5"
```

### 用户指令测试

```cmd
curl -s -X POST http://localhost:8000/api/command -H "Content-Type: application/json" -d "{\"text\": \"提醒我明天早上9点开会\"}"
```

等待约 15 秒后：

```cmd
curl -s "http://localhost:8000/api/actions?source=command&page_size=1"
```

### 优先级验证

```cmd
curl -s -X POST http://localhost:8000/api/video/upload -F "file=@D:\path\to\video.mp4"
```

视频处理期间立即发送：

```cmd
curl -s -X POST http://localhost:8000/api/command -H "Content-Type: application/json" -d "{\"text\": \"优先测试指令\"}"
```

查看结果：

```cmd
curl -s "http://localhost:8000/api/actions?status=all&page_size=5"
```
