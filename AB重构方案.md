# A/B 层重构方案

## 1. 背景与问题

### 当前架构的核心缺陷

**人脸/声音识别不稳定：**
- A 层逐帧独立检测，模糊帧、侧脸产生噪声 embedding
- B 层用滑动均值 + 固定阈值做 cosine 匹配，对光照/角度变化鲁棒性差
- 没有 Re-ID 机制，同一人离开画面再回来会被分配新 track_id

**声音-人脸绑定失败：**
- 两者异步流，靠时间戳对齐，本质上是在"赌"说话时恰好有人脸
- 没有利用视觉信息（谁的嘴在动）
- 穿戴者自己的声音无法通过视觉绑定

### 新硬件条件
- GPU 服务器（A100），眼镜采集视频/音频后传输到服务器处理
- 近实时要求：端到端延迟 1-5s 可接受

---

## 2. 重构目标

1. 同一个人的人脸，在不同帧、不同光照、短暂离开后，始终映射到同一个 alias
2. 声音能够独立识别说话人身份（视野内无人脸时也能工作）
3. 声音与人脸能够可靠绑定到同一个 alias
4. 穿戴者自己的声音能被正确识别
5. 上层（C 层及以上）只感知稳定的 alias，不感知底层 track_id 变化

---

## 3. 整体架构

```
眼镜端
├── 视频流 ──→ 服务器
└── 音频流 ──→ 服务器

服务器（新 A 层）
├── 视频管道
│   ├── YOLOv8-face 人脸检测
│   ├── ByteTrack 人物追踪（track_id）
│   ├── ArcFace embedding 提取
│   ├── Re-ID 模块（track_id → alias 映射）
│   └── 嘴部 ROI 裁剪（供 ASD 使用）
├── 音频管道
│   ├── VAD 语音活动检测
│   ├── Whisper ASR 语音识别
│   └── WeSpeaker 声纹 embedding 提取
├── ASD 模块（Active Speaker Detection）
│   ├── 输入：嘴部 ROI 序列 + 音频帧
│   └── 输出：每个 track 的说话概率
└── 身份融合模块
    ├── 人脸 embedding → 注册库匹配
    ├── 声纹 embedding → 注册库匹配
    └── 输出：alias + 置信度

新 A 层输出事件 → a_events MQ

新 B 层（改动最小）
├── EventAggregator（保留）
├── SemanticGenerator（保留）
├── IdentityTracker（简化，alias 已由 A 层稳定输出）
└── 输出 → b_events MQ
```

---

## 4. 关键模块详解

### 4.1 人脸追踪与 Re-ID

**追踪：ByteTrack**
- 对消失的 track 保留缓冲期（默认 30 帧），短暂遮挡自动恢复
- 输出稳定的 track_id

**Re-ID 层（track_id → alias 映射）：**

```
新 track_id 出现
    ↓
提取 ArcFace embedding
    ↓
与 recently_lost_tracks（近 5 分钟内消失的 track）做 cosine 匹配
    ├── 相似度 > 0.7 → 继承旧 alias
    └── 相似度 < 0.7 → 与注册库匹配
            ├── 命中 → 分配注册人名
            └── 未命中 → 分配新临时 alias
```

`recently_lost_tracks` 时间窗口可配置，默认 5 分钟。

**alias 与 track_id 解耦原则：**
- A 层内部维护 `track_id → alias` 映射表
- 对外（B 层及以上）只暴露 alias，track_id 变化对上层透明

### 4.2 Active Speaker Detection（ASD）

**模型：Light-ASD**（工程友好，A100 上延迟 ~15ms/帧）

**工作原理：**
- 滑动窗口 0.5-1s，输入每个 track 的嘴部 ROI 序列 + 对应音频
- 输出每个 track 的说话概率 P(speaking)
- 说话人 = argmax P(t)

**作用：** 直接用视听同步性判断谁在说话，替代当前的时间戳对齐方案。

**局限与 fallback：**
- 嘴部遮挡（口罩、侧脸）→ fallback 到声纹匹配
- 多人同时说话 → 取概率最高的 track
- 穿戴者自己（摄像头看不到自己的脸）→ 见 4.4

### 4.3 双模态注册库

**结构：**
```json
{
  "person_id": "张三",
  "face_embeddings": [[...], [...], ...],
  "voice_embeddings": [[...], [...], ...],
  "is_wearer": false
}
```

**身份融合策略：**

| 可用模态 | 策略 |
|---|---|
| 人脸 + 声音 | 加权投票（face 权重 0.6，voice 权重 0.4） |
| 仅人脸 | 单模态识别 |
| 仅声音 | 单模态识别（视野内无人脸时） |
| 两者冲突 | 取置信度更高的，记录冲突日志供后续 alias 合并检查 |

**在线自动更新：**
- 高置信度识别后，将新 embedding 加入注册库（滑动窗口，保留最近 10 个高质量样本）
- 注册库随运行时间自动变好

### 4.4 穿戴者声音识别

**方案：声纹预注册 + 优先匹配**

```
每次音频片段到来
    ↓
优先与穿戴者声纹做 cosine 匹配
    ├── 相似度 > 阈值（0.75）→ 直接判定为穿戴者，跳过 ASD
    └── 相似度 < 阈值 → 走正常 ASD + 声纹匹配流程
```

穿戴者在注册库中标记 `"is_wearer": true`，系统启动时自动加载为优先匹配对象。

---

## 5. 注册库创建流程

### 5.1 离线注册脚本

**输入：**
- 人名
- 照片文件夹（5-10 张，不同角度/光照）
- 音频文件夹（3-5 段，每段 3-10s）

**流程：**
```
照片 → YOLOv8-face 检测 → 质量过滤（模糊/侧脸剔除）→ ArcFace 提取 → 存库
音频 → VAD 切段 → WeSpeaker 提取声纹 → 存库
```

**穿戴者注册：** 同上，额外设置 `is_wearer: true`，建议采集 10 段以上音频保证声纹质量。

### 5.2 注册库格式

使用 SQLite 存储，结构：

```sql
CREATE TABLE persons (
    person_id TEXT PRIMARY KEY,
    display_name TEXT,
    is_wearer INTEGER DEFAULT 0,
    created_at TEXT,
    updated_at TEXT
);

CREATE TABLE face_embeddings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id TEXT,
    vector BLOB,       -- numpy array 序列化
    quality REAL,
    created_at TEXT
);

CREATE TABLE voice_embeddings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id TEXT,
    vector BLOB,
    quality REAL,
    created_at TEXT
);
```

---

## 6. 新 A 层输出事件

重构后 A 层输出的事件类型简化，核心事件：

```json
{
  "event_id": "fc_xxx",
  "event_type": "person_speaking",
  "time": {"start_ts": "...", "end_ts": "..."},
  "source": {"device_id": "glasses_01"},
  "payload": {
    "alias": "alias_A",
    "person_id": "张三",
    "confidence": 0.92,
    "modality_used": "face+voice",
    "asr_text": "今天下午开会",
    "face_embedding": [...],
    "voice_embedding": [...]
  }
}
```

保留原有的 `scene_detection`、`ui_state_change`、`notification_event` 事件类型不变。

---

## 7. 新 B 层改动

B 层改动最小化：

| 组件 | 改动 |
|---|---|
| `IdentityTracker` | 大幅简化：alias 已由 A 层稳定输出，B 层只需维护 alias → person_id 的映射，不再做 embedding 匹配 |
| `EventAggregator` | 保留，逻辑不变 |
| `SemanticGenerator` | 完全不变 |
| `ContextManager` | 保留，逻辑不变 |

---

## 8. 模型清单

| 用途 | 模型 | 备注 |
|---|---|---|
| 人脸检测 | YOLOv8-face | 替换当前 YOLO |
| 人物追踪 | ByteTrack | 新增 |
| 人脸识别 | InsightFace buffalo_l（ArcFace R100） | 替换当前方案 |
| ASD | Light-ASD | 新增，核心模块 |
| 声纹识别 | WeSpeaker ECAPA-TDNN | 替换当前 audio_embedder |
| ASR | Whisper（保留） | 不变 |
| 场景分类 | CLIP + YOLOv8（保留） | 不变 |

---

## 9. 实施步骤

**第一步：注册库基础设施**
- 设计并实现 SQLite 注册库
- 实现离线注册脚本（人脸 + 声纹）
- 注册穿戴者

**第二步：视频管道重构**
- 集成 YOLOv8-face + ByteTrack
- 集成 InsightFace ArcFace
- 实现 Re-ID 模块（track_id → alias）

**第三步：音频管道重构**
- 集成 WeSpeaker 声纹提取
- 实现穿戴者优先匹配逻辑

**第四步：ASD 集成**
- 集成 Light-ASD
- 实现视音频同步送入 ASD 的管道
- 实现 fallback 逻辑（遮挡时退化到声纹匹配）

**第五步：身份融合模块**
- 实现双模态加权投票
- 实现冲突处理逻辑

**第六步：B 层简化**
- 简化 IdentityTracker
- 联调测试

---

## 10. 风险与应对

| 风险 | 应对 |
|---|---|
| 嘴部遮挡导致 ASD 失效 | fallback 到声纹单模态识别 |
| 注册库为空（陌生人场景） | 分配临时 alias，运行时积累 embedding，可事后补注册 |
| 视频/音频流同步偏差 | A 层统一时间戳对齐，允许 ±100ms 误差 |
| 多人同时说话 | 取 ASD 概率最高的 track，记录不确定性标志 |
