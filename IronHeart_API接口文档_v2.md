# IronHeart 后端 API 接口文档

> **版本**：v2.0  
> **日期**：2026-04-23  
> **后端基础地址**：`http://{服务器IP}:8000`  
> **开发调试**：`http://localhost:8000`（手机与电脑连同一 WiFi，使用电脑局域网 IP）  
> **协议**：HTTP REST + WebSocket  
> **数据格式**：JSON  
> **字符编码**：UTF-8  
> **CORS**：已全局开启，允许所有来源

---

## 目录

1. [概述](#1-概述)
2. [通用约定](#2-通用约定)
3. [接口 1：视频上传](#3-接口-1视频上传)
4. [接口 2：系统状态查询与推送](#4-接口-2系统状态查询与推送)
5. [接口 3：反思配置与触发](#5-接口-3反思配置与触发)（含 6 个子接口）
6. [接口 4：Tier1 用户画像读写](#6-接口-4tier1-用户画像读写)
7. [接口 5：行动卡片（E 层输出）](#7-接口-5行动卡片e-层输出)
8. [接口 6：用户直接指令](#8-接口-6用户直接指令)
9. [辅助接口（已有）](#9-辅助接口已有)
10. [前端需要配合的部分](#10-前端需要配合的部分)
11. [调试指南](#11-调试指南)

---

## 1. 概述

### 系统架构

```
Android APP (Aether-Lens)
      │
      │  HTTP REST / WebSocket
      ▼
┌─────────────────────────────┐
│  API Gateway (FastAPI)       │
│  http://{IP}:8000            │
│                             │
│  ┌── 视频上传 → 启动A层      │
│  ├── 状态推送 (WebSocket)    │
│  ├── Tier1 画像读写          │
│  ├── 行动卡片 (E层输出)      │
│  ├── 用户指令 (C→E旁路)      │
│  └── 反思调度配置            │
└──────────────┬──────────────┘
               │ 内部消息队列 (TCP :6380)
    ┌──────────┼──────────────────┐
    A层   B层   C层   D层   E层
   按需   常驻  常驻  常驻  常驻
   启动
```

### 三种系统状态

| 状态 | 枚举值 | 含义 | 可共存 |
|------|--------|------|--------|
| 工作中 | `WORKING` | ABCDE 任一层有未处理数据 | 可与 ORGANIZING 共存 |
| 整理中 | `ORGANIZING` | C 层正在进行夜间反思 | 可与 WORKING 共存 |
| 休眠 | `SLEEPING` | 既不在工作中也不在整理中 | — |

---

## 2. 通用约定

### 响应格式

大部分接口统一返回 JSON：

**成功响应：**
```json
{
  "code": 0,
  "data": { ... },
  "message": "success"
}
```

**错误响应：**
```json
{
  "code": 40001,
  "data": null,
  "message": "视频文件不能为空"
}
```

> **例外**：`GET /health`、`GET /api/tier2/{entity_id}`、`GET /api/tier3/recent`、`GET /api/entity/{entity_id}`、`GET /api/entity/list`、`GET /api/stats` 直接返回原始数据或 HTTP 错误，**不使用 `ok()` 封装**。

### 错误码表

| 错误码 | 含义 |
|--------|------|
| 0 | 成功 |
| 40001 | 请求参数错误 |
| 40401 | 资源不存在 |
| 40901 | 资源冲突（如重复上传） |
| 50001 | 服务器内部错误 |
| 50301 | 后端服务未就绪 |

### 时间格式

所有时间字段使用 **ISO 8601** 格式：`"2026-04-22T23:59:59"`

### 分页

支持分页的接口使用 `page`（从1开始）和 `page_size`（默认20，最大100）参数。

---

## 3. 接口 1：视频上传

### 3.1 上传视频文件

前端将手机拍摄/选择的 MP4 文件上传到后端，后端接收后自动启动 A 层开始解析。

**请求：**

```
POST /api/video/upload
Content-Type: multipart/form-data
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| file | File | 是 | MP4 视频文件，最大 500MB |
| source | String | 否 | 来源标识，默认 `"camera"` |

**响应：**

```json
{
  "code": 0,
  "data": {
    "job_id": "job_20260422_235959_abc123",
    "status": "queued",
    "file_size_mb": 45.2,
    "created_at": "2026-04-22T23:59:59"
  },
  "message": "success"
}
```

`status` 可能的值：

| 值 | 含义 |
|----|------|
| `queued` | 排队中，等待前一个视频处理完 |
| `processing` | A 层正在解析视频 |
| `completed` | 处理完成 |
| `failed` | 处理失败 |

> 当前 `status` 在上传时直接返回 `"processing"`（不做排队）。

### 3.2 查询视频处理状态

```
GET /api/video/status/{job_id}
```

**响应：**

```json
{
  "code": 0,
  "data": {
    "job_id": "job_20260422_235959_abc123",
    "status": "completed",
    "file_size_mb": 45.2,
    "events_generated": 38,
    "created_at": "2026-04-22T23:59:59",
    "completed_at": "2026-04-23T00:15:55"
  },
  "message": "success"
}
```

> **注意**：当前版本不提供 `progress`、`total_frames`、`fps` 等实时进度字段。视频处理完成后 `status` 直接变为 `completed`。

### 3.3 查询历史任务列表

```
GET /api/video/jobs?page=1&page_size=10
```

**响应：**

```json
{
  "code": 0,
  "data": {
    "total": 5,
    "page": 1,
    "page_size": 10,
    "jobs": [
      {
        "job_id": "job_20260422_235959_abc123",
        "status": "completed",
        "file_size_mb": 45.2,
        "events_generated": 62,
        "created_at": "2026-04-22T23:59:59",
        "completed_at": "2026-04-23T00:15:55"
      }
    ]
  },
  "message": "success"
}
```

---

## 4. 接口 2：系统状态查询与推送

### 4.1 轮询查询状态

```
GET /api/status
```

**响应：**

```json
{
  "code": 0,
  "data": {
    "state": "WORKING",
    "states": ["WORKING"],
    "queues": {
      "a_events": 0,
      "b_events": 3,
      "opportunities": 0,
      "execution_plans": 1
    },
    "video_processing": {
      "has_active_job": true,
      "job_id": "job_20260422_235959_abc123",
      "progress": 52.1
    },
    "reflecting": false,
    "layer_status": {
      "broker": "running",
      "b_layer": "running",
      "c_layer": "running",
      "d_layer": "running",
      "e_layer": "running"
    },
    "updated_at": "2026-04-22T23:59:59"
  },
  "message": "success"
}
```

> `state` 为主状态值，前端可直接使用已有的 `WorkStatus` 枚举映射。  
> `states` 为数组（因为 WORKING 和 ORGANIZING 可共存）。

### 4.2 WebSocket 实时状态推送

```
WS /api/status/ws
```

**连接后自动推送（每 2 秒）：**

```json
{
  "state": "WORKING",
  "states": ["WORKING"],
  "queues": { "a_events": 0, "b_events": 3, "opportunities": 0, "execution_plans": 1 },
  "video_processing": { "has_active_job": true, "progress": 52.1 },
  "reflecting": false
}
```

**前端心跳：** 建议前端每 30 秒发送一次 `{"type": "ping"}`，服务端回复 `{"type": "pong"}`。连接断开后自动重连。

---

## 5. 接口 3：反思配置与触发

### 5.1 获取当前反思配置

```
GET /api/reflect/config
```

**响应：**

```json
{
  "code": 0,
  "data": {
    "schedule_times": ["00:00", "14:00", "20:00"],
    "max_daily_reflections": 3,
    "min_interval_minutes": 60,
    "today_reflection_count": 1,
    "last_reflection_at": "2026-04-23"
  },
  "message": "success"
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `schedule_times` | string[] | 每日自动反思的时间点列表，格式 `"HH:MM"`，按升序排列 |
| `max_daily_reflections` | int | 每日最大自动反思次数（当前固定 3，等于可设置的最大时间点数） |
| `min_interval_minutes` | int | 两次自动反思的最短间隔（分钟，当前固定 60） |
| `today_reflection_count` | int | 今日已执行的自动反思次数（手动触发不计入） |
| `last_reflection_at` | string\|null | 最近一次反思的日期 |

### 5.2 修改反思调度时间（向后兼容）

```
PUT /api/reflect/config
```

覆盖为**单个**调度时间点（清除所有已有时间点，仅保留一个）。

**请求体：**

```json
{
  "schedule_time": "23:30"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| schedule_time | String | 是 | 格式 `"HH:MM"`，24小时制 |

**响应：**

```json
{
  "code": 0,
  "data": { "schedule_times": ["23:30"] },
  "message": "success"
}
```

### 5.3 添加调度时间点

```
POST /api/reflect/schedule
```

在已有时间点列表中追加一个新时间点。时间点总数不能超过 `max_daily_reflections`。

**请求体：**

```json
{
  "time": "14:00"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| time | String | 是 | 格式 `"HH:MM"` |

**响应：**

```json
{
  "code": 0,
  "data": { "schedule_times": ["00:00", "14:00", "20:00"] },
  "message": "success"
}
```

**错误**：`code: 40001` — 时间已存在 / 超过 max_daily_reflections 上限 / 格式错误

### 5.4 删除调度时间点

```
DELETE /api/reflect/schedule
```

**请求体：**

```json
{
  "time": "14:00"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| time | String | 是 | 格式 `"HH:MM"` |

**响应：**

```json
{
  "code": 0,
  "data": { "schedule_times": ["00:00", "20:00"] },
  "message": "success"
}
```

**错误**：`code: 40001` — 时间不存在

### 5.5 手动触发反思

```
POST /api/reflect/trigger
```

手动触发不受 `max_daily_reflections` 和 `min_interval_minutes` 限制。

**请求体：**

```json
{
  "enable_tier1_llm": true
}
```

| 字段 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| enable_tier1_llm | Boolean | 否 | `true` | 是否启用 Tier1 LLM 更新 |

**响应：**

```json
{
  "code": 0,
  "data": {
    "triggered": true,
    "message": "反思已完成",
    "tier2_written": 12,
    "labels_updated": 1,
    "tier1_updated": true
  },
  "message": "success"
}
```

**错误**：`code: 40901` — 反思正在进行中

> **注意**：当前版本中此接口是**同步阻塞**的——反思在请求线程内执行，响应返回时反思已完成。因此无法通过 `/api/status` 的 `reflecting` 字段观察到 ORGANIZING 状态。自动反思由 `ReflectionScheduler` 在后台线程触发，此时可通过 `/api/status` 观察到。

### 5.6 查询反思历史

```
GET /api/reflect/history?page=1&page_size=10
```

**响应：**

```json
{
  "code": 0,
  "data": {
    "total": 5,
    "records": [
      {
        "id": 1,
        "triggered_at": "2026-04-22T00:00:12",
        "trigger_type": "auto",
        "tier3_events": 13,
        "tier2_written": 12,
        "labels_updated": 1,
        "names_updated": 0,
        "tier1_updated": true,
        "duration_seconds": 45
      }
    ]
  },
  "message": "success"
}
```

`trigger_type` 取值：

| 值 | 含义 |
|----|------|
| `auto` | 调度器自动触发（受 max_daily_reflections 和 min_interval_minutes 限制） |
| `manual` | 用户手动触发（不受限制） |

---

## 6. 接口 4：Tier1 用户画像读写

### 6.1 获取用户画像

```
GET /api/tier1/{user_id}
```

**响应：**

```json
{
  "code": 0,
  "data": {
    "user_id": "default_user",
    "critical_facts": {
      "preferences": [
        { "text": "偏好关注新兴事物和前沿科技视频", "source": "system" },
        { "text": "不喜欢吃辣", "source": "user" }
      ],
      "habits": [
        { "text": "习惯在深夜刷短视频，对不同颜色手机感兴趣", "source": "system" }
      ],
      "health_constraints": [],
      "core_goals": [
        { "text": "追求更具挑战性的表达方式", "source": "system" }
      ],
      "relationships": [
        { "text": "张三：同事", "source": "user" }
      ]
    },
    "updated_at": "2026-04-22T00:00:30"
  },
  "message": "success"
}
```

**`source` 字段说明：**

| 值 | 含义 |
|----|------|
| `system` | 后端 C 层夜间反思自动提取的条目，前端应标记为「系统整理」 |
| `user` | 用户在前端手动添加或修改的条目，前端应标记为「我添加的」 |

**前端画像分类映射：**

后端的 `critical_facts` 键对应前端的 `PortraitCard.category`：

| 后端键 | 前端 category | 含义 |
|--------|---------------|------|
| `preferences` | `LIKE` | 偏好/喜好 |
| `habits` | `ME` | 习惯/行为 |
| `health_constraints` | `NOTE` | 健康禁忌 |
| `core_goals` | `GOAL` | 目标/追求 |
| `relationships` | `BOND` | 人际关系 |

### 6.2 更新用户画像

此接口可操作所有条目（不区分 `source`），支持对系统提取和用户添加的条目进行增删改。

```
PUT /api/tier1/{user_id}
```

**请求体：**

```json
{
  "category": "preferences",
  "action": "add",
  "item": { "text": "喜欢打篮球" }
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| category | String | 是 | `preferences` / `habits` / `health_constraints` / `core_goals` / `relationships` |
| action | String | 是 | `add`（新增）/ `update`（修改）/ `delete`（删除） |
| item | Object | 是 | `{ "text": "...", "id": "..." }`（update/delete 需要 id） |

**新增条目 (`action: "add"`)：**

```json
{
  "category": "relationships",
  "action": "add",
  "item": { "text": "李四：大学同学" }
}
```

**修改条目 (`action: "update"`)：**

```json
{
  "category": "preferences",
  "action": "update",
  "item": { "id": "user_pref_001", "text": "非常喜欢打篮球，每周三次" }
}
```

**删除条目 (`action: "delete"`)：**

```json
{
  "category": "preferences",
  "action": "delete",
  "item": { "id": "user_pref_001" }
}
```

**响应：** 返回更新后的完整画像（同 6.1）。

---

## 7. 接口 5：行动卡片（E 层输出）

### 7.1 获取行动卡片列表

```
GET /api/actions?status=pending&page=1&page_size=20
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| status | String | 否 | `pending`（待处理）/ `confirmed`（已确认）/ `rejected`（已拒绝）/ `all`，默认 `pending` |
| source | String | 否 | `pipeline`（系统正常流水线）/ `command`（用户直接指令）/ `all`，默认 `all` |

**响应：**

```json
{
  "code": 0,
  "data": {
    "total": 3,
    "actions": [
      {
        "id": "act_20260422_001",
        "source": "pipeline",
        "type": "message",
        "title": "飞书消息草稿",
        "content": "向团队发送项目进度更新：\n\n各位好，Aether 项目第一阶段开发已完成 80%...",
        "confidence": 0.85,
        "status": "pending",
        "context": {
          "opportunity_id": "opp_abc123",
          "trigger_summary": "用户在讨论项目进度"
        },
        "created_at": "2026-04-22T23:59:59"
      },
      {
        "id": "act_20260422_002",
        "source": "command",
        "type": "task",
        "title": "整理对话要点",
        "content": "今天与张三的对话要点：\n1. 项目进度 80%\n2. 本周五完成核心功能",
        "confidence": 0.90,
        "status": "pending",
        "context": {
          "command_text": "帮我整理今天和张三的对话要点"
        },
        "created_at": "2026-04-22T23:55:00"
      }
    ]
  },
  "message": "success"
}
```

**`type` 字段与前端 `ActionCard.type` 对应：**

| 后端 type | 前端 ActionCard.type | 含义 |
|-----------|---------------------|------|
| `message` | `message` | 消息草稿（如飞书） |
| `approval` | `approval` | 审批/确认 |
| `notification` | `notification` | 通知/提醒 |
| `task` | `task` | 任务/待办 |
| `calendar` | `calendar` | 日历事件 |
| `voice_feedback` | `voice_feedback` | 语音反馈 |

### 7.2 确认/拒绝行动卡片

```
PUT /api/actions/{action_id}
```

**请求体：**

```json
{
  "decision": "confirmed"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| decision | String | 是 | `confirmed`（确认执行）/ `rejected`（拒绝） |

**响应：**

```json
{
  "code": 0,
  "data": {
    "id": "act_20260422_001",
    "status": "confirmed",
    "executed_at": "2026-04-23T00:01:00"
  },
  "message": "success"
}
```

### 7.3 WebSocket 实时推送新行动卡片

```
WS /api/actions/ws
```

**当有新行动卡片产生时推送：**

```json
{
  "type": "new_action",
  "data": {
    "id": "act_20260422_003",
    "source": "pipeline",
    "type": "notification",
    "title": "会议提醒",
    "content": "产品评审会议将在 30 分钟后开始",
    "confidence": 0.75,
    "created_at": "2026-04-23T00:05:00"
  }
}
```

---

## 8. 接口 6：用户直接指令

前端用户通过语音或文字输入指令，后端将其作为特殊语义事件，获取相关记忆后直接生成行动卡片（跳过 D 层决策排队，走优先队列 `command_opportunities` → `command_execution_plans`）。

```
POST /api/command
```

**请求体（Pydantic 模型）：**

```json
{
  "text": "帮我整理今天和张三讨论的要点",
  "type": "voice"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| text | String | 是 | 用户输入的指令文本 |
| type | String | 否 | `voice`（语音转文字）/ `text`（手动输入），默认 `"text"` |

**响应：**

```json
{
  "code": 0,
  "data": {
    "command_id": "cmd_20260422_001",
    "status": "processing",
    "message": "指令已接收，正在生成行动卡片"
  },
  "message": "success"
}
```

> 结果通过 `/api/actions/ws` 实时推送，也可通过 `GET /api/actions?source=command` 轮询获取。

---

## 9. 辅助接口（已有）

以下接口已在后端实现，可直接使用。

### 9.1 健康检查

```
GET /health
```

**响应：**

```json
{
  "status": "ok",
  "service": "c_layer_api"
}
```

### 9.2 获取身份列表

```
GET /api/entity/list
```

**响应：**

```json
[
  {
    "resolved_entity_id": "entity_0001",
    "labels": "视频创作者，新媒体研究",
    "face_embedding_count": 5,
    "voice_embedding_count": 8,
    "last_seen_at": "2026-04-22T23:50:00"
  }
]
```

> **注意**：此接口返回的实体列表中排除了 `face_embedding` 和 `voice_embedding` 向量数据（数据量过大）。当无数据时可能返回 500 错误。

### 9.3 获取单个身份详情

```
GET /api/entity/{entity_id}
```

### 9.4 获取 Tier2 长期记忆

```
GET /api/tier2/{entity_id}?limit=10
```

> **注意**：此接口直接返回数组，**不使用 `ok()` 封装**。

```json
[
  { "memory_id": "...", "memory_text": "...", "base_importance": 0.8, "created_at": "..." }
]
```

### 9.5 获取 Tier3 近期事件

```
GET /api/tier3/recent?limit=20
```

> **注意**：此接口直接返回数组，**不使用 `ok()` 封装**。

### 9.6 获取全局统计

```
GET /api/stats
```

**响应：**

```json
{
  "total_entities": 5,
  "with_face_embedding": 4,
  "with_voice_embedding": 1,
  "with_both": 5
}
```

> **注意**：此接口直接返回对象，**不使用 `ok()` 封装**。

---

## 10. 前端需要配合的部分（仅供参考，实际可根据前述内容自定）

### 10.1 需要添加的依赖

在 `app/build.gradle.kts` 中添加：

```kotlin
dependencies {
    // 网络请求
    implementation("com.squareup.retrofit2:retrofit:2.9.0")
    implementation("com.squareup.retrofit2:converter-gson:2.9.0")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("com.squareup.okhttp3:logging-interceptor:4.12.0")

    // WebSocket（OkHttp 已内置支持）

    // 文件上传（如需要更方便的 multipart）
    implementation("com.squareup.okhttp3:okhttp-urlconnection:4.12.0")
}
```

### 10.2 需要新建的文件

```
app/src/main/java/com/aether/app/
├── network/
│   ├── AetherApiService.kt       // Retrofit 接口定义
│   ├── ApiClient.kt              // OkHttpClient + Retrofit 单例
│   ├── ApiResponse.kt            // 通用响应包装类
│   └── WebSocketManager.kt       // WebSocket 连接管理
├── data/
│   ├── ActionCard.kt             // 扩展字段：source, confidence, context
│   ├── SystemStatus.kt           // 新增：系统状态数据类
│   ├── Tier1Portrait.kt          // 新增：画像数据类（含 source 标签）
│   ├── ReflectConfig.kt          // 新增：反思配置数据类
│   └── VideoJob.kt               // 新增：视频任务数据类
```

### 10.3 Retrofit 接口定义参考

```kotlin
interface AetherApiService {

    // === 接口 1：视频上传 ===
    @Multipart
    @POST("api/video/upload")
    suspend fun uploadVideo(
        @Part file: MultipartBody.Part,
        @Part("source") source: RequestBody? = null
    ): ApiResponse<VideoJob>

    @GET("api/video/status/{jobId}")
    suspend fun getVideoStatus(@Path("jobId") jobId: String): ApiResponse<VideoJob>

    @GET("api/video/jobs")
    suspend fun getVideoJobs(
        @Query("page") page: Int = 1,
        @Query("page_size") pageSize: Int = 10
    ): ApiResponse<PagedResult<VideoJob>>

    // === 接口 2：系统状态 ===
    @GET("api/status")
    suspend fun getSystemStatus(): ApiResponse<SystemStatus>

    // === 接口 3：反思配置 ===
    @GET("api/reflect/config")
    suspend fun getReflectConfig(): ApiResponse<ReflectConfig>

    @PUT("api/reflect/config")
    suspend fun updateReflectConfig(@Body config: ReflectConfigUpdate): ApiResponse<ReflectScheduleResult>

    @POST("api/reflect/schedule")
    suspend fun addReflectSchedule(@Body body: ReflectScheduleTime): ApiResponse<ReflectScheduleResult>

    @HTTP(method = "DELETE", path = "api/reflect/schedule", hasBody = true)
    suspend fun removeReflectSchedule(@Body body: ReflectScheduleTime): ApiResponse<ReflectScheduleResult>

    @POST("api/reflect/trigger")
    suspend fun triggerReflect(@Body body: Map<String, Boolean> = emptyMap()): ApiResponse<ReflectResult>

    // === 接口 4：Tier1 画像 ===
    @GET("api/tier1/{userId}")
    suspend fun getTier1(@Path("userId") userId: String = "default_user"): ApiResponse<Tier1Portrait>

    @PUT("api/tier1/{userId}")
    suspend fun updateTier1(
        @Path("userId") userId: String = "default_user",
        @Body update: Tier1Update
    ): ApiResponse<Tier1Portrait>

    // === 接口 5：行动卡片 ===
    @GET("api/actions")
    suspend fun getActions(
        @Query("status") status: String = "pending",
        @Query("source") source: String = "all",
        @Query("page") page: Int = 1,
        @Query("page_size") pageSize: Int = 20
    ): ApiResponse<PagedResult<ActionCard>>

    @PUT("api/actions/{actionId}")
    suspend fun updateAction(
        @Path("actionId") actionId: String,
        @Body decision: ActionDecision
    ): ApiResponse<ActionCard>

    // === 接口 6：用户指令 ===
    @POST("api/command")
    suspend fun sendCommand(@Body command: UserCommand): ApiResponse<CommandResult>

    // === 辅助接口（不使用 ok() 封装） ===
    @GET("health")
    suspend fun healthCheck(): HealthResponse

    @GET("api/entity/list")
    suspend fun getEntityList(): List<EntityInfo>

    @GET("api/stats")
    suspend fun getStats(): SystemStats
}
```

### 10.4 数据类定义参考

```kotlin
// === 通用响应 ===
data class ApiResponse<T>(
    val code: Int,
    val data: T?,
    val message: String
)

// === 系统状态 ===
data class SystemStatus(
    val state: String,              // "WORKING" | "ORGANIZING" | "SLEEPING"
    val states: List<String>,       // 可同时为 ["WORKING", "ORGANIZING"]
    val queues: Map<String, Int>,
    val videoProcessing: VideoProcessingInfo?,
    val reflecting: Boolean,
    val layerStatus: Map<String, String>,
    val updatedAt: String
)

data class VideoProcessingInfo(
    val hasActiveJob: Boolean,
    val jobId: String?,
    val progress: Double
)

// === 视频任务 ===
data class VideoJob(
    val jobId: String,
    val status: String,             // "queued" | "processing" | "completed" | "failed"
    val fileSizeMb: Double? = null,
    val eventsGenerated: Int? = null,
    val createdAt: String,
    val completedAt: String? = null
)

// === 反思配置 ===
data class ReflectConfig(
    val scheduleTimes: List<String>,  // ["HH:MM", ...]
    val maxDailyReflections: Int,
    val minIntervalMinutes: Int,
    val todayReflectionCount: Int,
    val lastReflectionAt: String?
)

data class ReflectConfigUpdate(
    val scheduleTime: String          // 向后兼容：覆盖为单个时间点
)

data class ReflectScheduleTime(
    val time: String                  // "HH:MM"
)

data class ReflectScheduleResult(
    val scheduleTimes: List<String>
)

// === Tier1 画像 ===
data class Tier1Portrait(
    val userId: String,
    val criticalFacts: CriticalFacts,
    val updatedAt: String
)

data class CriticalFacts(
    val preferences: List<PortraitItem> = emptyList(),
    val habits: List<PortraitItem> = emptyList(),
    val healthConstraints: List<PortraitItem> = emptyList(),
    val coreGoals: List<PortraitItem> = emptyList(),
    val relationships: List<PortraitItem> = emptyList()
)

data class PortraitItem(
    val id: String? = null,
    val text: String,
    val source: String              // "system" | "user"
)

data class Tier1Update(
    val category: String,
    val action: String,             // "add" | "update" | "delete"
    val item: PortraitItem
)

// === 行动卡片（扩展现有 ActionCard） ===
data class ActionCard(
    val id: String,
    val source: String,             // "pipeline" | "command"
    val type: String,               // "message" | "approval" | "notification" | "task" | "calendar" | "voice_feedback"
    val title: String,
    val content: String,
    val confidence: Double = 0.0,
    val status: String = "pending", // "pending" | "confirmed" | "rejected"
    val context: ActionContext? = null,
    val timestamp: Long
)

data class ActionContext(
    val opportunityId: String? = null,
    val triggerSummary: String? = null,
    val commandText: String? = null
)

data class ActionDecision(
    val decision: String            // "confirmed" | "rejected"
)

// === 用户指令 ===
data class UserCommand(
    val text: String,
    val type: String = "text"       // "voice" | "text"
)

data class CommandResult(
    val commandId: String,
    val status: String,
    val message: String
)
```

### 10.5 前端 UI 对接要点

#### (1) 状态展示

在设备状态区域展示后端系统状态：

```kotlin
// 已有 WorkStatus 枚举直接复用
// WORKING  → 显示"分析中"，用蓝色
// ORGANIZING → 显示"整理中"，用橙色
// SLEEPING → 显示"休眠"，用灰色
// WORKING + ORGANIZING → 两个都显示
```

建议通过 WebSocket `/api/status/ws` 实时更新，断线时降级为轮询 `GET /api/status`（每 5 秒）。

#### (2) 视频上传

在主界面添加一个入口（按钮/卡片），点击后：
1. 选择或拍摄视频
2. 调用 `POST /api/video/upload` 上传
3. 轮询 `GET /api/video/status/{jobId}` 查看处理状态
4. 完成后状态自动变为 WORKING → SLEEPING

#### (3) 画像管理

在个人空间页面（`PersonalSpaceScreen`）：
- 调用 `GET /api/tier1/{userId}` 获取画像
- 按 `source` 字段区分标签颜色：「系统整理」（`system`）和「我添加的」（`user`）
- 新增条目调用 `PUT /api/tier1/{userId}` with `action: "add"`
- 编辑/删除同理
- 所有条目均可编辑和删除（不区分 source）

#### (4) 行动卡片

在主界面卡片堆栈（`AetherWorkspaceScreen`）：
- 替换 `MockData.getCardList()` 为 `GET /api/actions?status=pending`
- 左滑拒绝 → `PUT /api/actions/{id}` with `decision: "rejected"`
- 右滑确认 → `PUT /api/actions/{id}` with `decision: "confirmed"`
- WebSocket `/api/actions/ws` 实时接收新卡片

#### (5) 用户指令

在语音输入（`WorkspaceCardStateHolder`）的 `onExecuteCommand(text)` 中：
- 调用 `POST /api/command`
- 结果通过 `/api/actions/ws` 推送回来

### 10.6 API 基地址配置

在登录/引导流程（`OnboardStep5Api`）或设置页面中，让用户输入后端地址：

```
http://192.168.1.100:8000
```

存储到 `UserPreferencesRepository` 中，供 `ApiClient` 读取。
