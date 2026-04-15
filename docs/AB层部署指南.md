# IronHeart AB 层部署指南

本文档说明 IronHeart 系统 AB 层（感知层 + 语义聚合层）的完整环境配置流程。

---

## 一、系统环境

### 1.1 基础依赖

**Python 版本：3.10+**

**系统依赖（Ubuntu/Debian）：**

```bash
sudo apt-get update
sudo apt-get install -y \
    ffmpeg \           # 音视频提取
    libgl1-mesa-glx \  # OpenCV GL依赖
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    pkg-config
```

**CUDA：推荐 11.8 或 12.x，配合 PyTorch 2.0+ 使用 GPU 加速。**

---

## 二、Python 包

### 2.1 核心依赖

```bash
# PyTorch（建议先安装 GPU 版）
pip install torch>=2.0.0 torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118

# 基础科学计算
pip install numpy>=1.24.0 opencv-python>=4.8.0 Pillow>=9.0.0

# AB层核心依赖
pip install ultralytics>=8.0.0 \
    insightface>=0.7.3 \
    onnxruntime-gpu>=1.15.0 \
    transformers>=4.41.2 \
    tokenizers>=0.21.0 \
    openai-whisper>=1.0.0 \
    python-speech-features \
    silero-vad \
    sentence-transformers>=2.2.0 \gpu
    pydantic>=2.0.0 \
    requests
```

### 2.2 B层依赖

```bash
pip install psycopg2-binary>=2.9.0 \
    "psycopg[binary]>=3.1.0" \
    pgvector>=0.2.0
```

B层语义生成依赖 LLM API（DeepSeek / OpenAI 兼容接口），`config.json` 中配置。

### 2.3 模型相关的自动下载

以下模型在首次运行时会自动下载（需网络连接）：

| 模型                        | 下载方式                         | 首次使用位置  |
| ------------------------- | ---------------------------- | ------- |
| Silero-VAD                | `pip install silero-vad` 自动带 | VAD 初始化 |
| FunASR SenseVoice         | HuggingFace 自动下载             | ASR 初始化 |
| InsightFace (arcface_r50) | 首次调用时自动下载                    | 人脸编码    |
| moondream2                | 首次调用时自动下载                    | 场景分类    |

---

## 三、模型文件

项目内模型位于 `models/` 目录，需手动下载或从原项目获取的如下：

### 3.1 目录结构

```
models/
├── yolo26n.pt                        # YOLOv26 人体检测（Ultralytics 自动下载）
├── botsort_custom.yaml                # BoTSort 跟踪器配置
├── Light-ASD/                         # Active Speaker Detection
│   ├── weight/
│   │   └── pretrain_AVA_CVPR.model   # Light-ASD 预训练权重
│   └── ...
├── wespeaker/                         # 声纹识别
│   └── wespeaker-cnceleb-resnet34-LM/
│       ├── cnceleb_resnet34_LM.onnx  # WeSpeaker ONNX 模型
│       └── ...
└── AI-ModelScope/                     # 场景分类（可选，scene_event 关闭时不需要）
    └── Florence-2-base/
        └── ...
```

### 3.2 逐项说明

#### YOLOv26 人体检测模型

**下载方式：**

```bash
# 方法1：通过 ultralytics 自动下载
python -c "from ultralytics import YOLO; YOLO('yolov26n.pt')"
# 将自动下载 yolov26n.pt 到 ~/.ultralytics/

# 方法2：手动下载（项目使用 yolo26n.pt）
wget https://github.com/ultralytics/assets/releases/download/v0.0.0/yolov26n.pt
# 重命名为 yolo26n.pt 放入 models/ 或修改 config.py 中的 YOLO_MODEL 路径
```

> 项目实际使用 `models/yolo26n.pt`（YOLOv26 nano 模型）。如果使用其他版本，需修改 `a_layer/config.py` 中的 `YOLO_MODEL`。

#### BoTSort 跟踪器配置

`models/botsort_custom.yaml` 内容如下（已在项目中，无需额外下载）：

```yaml
tracker_type: botsort
tracker_config:
  track_high_thresh: 0.5
  track_low_thresh: 0.1
  new_track_thresh: 0.6
  track_buffer: 30
  match_thresh: 0.8
  aspect_ratio_high_thresh: 1.6
  aspect_ratio_low_thresh: 0.4
  min_box_area: 10
  mot20: False
```

#### Light-ASD 权重

**下载地址：** [Light-ASD GitHub](https://github.com/Junhua-Liao/Light-ASD)

```bash
cd models
git clone https://github.com/Junhua-Liao/Light-ASD.git
```

#### WeSpeaker 声纹模型

**下载地址：** [WeSpeaker GitHub](https://github.com/wenetspeaker/wespeaker)

```bash
# 克隆仓库
git clone https://github.com/wenetspeaker/wespeaker.git /tmp/wespeaker
# 导出 ONNX 模型（需要参照 wespeaker 文档导出）
# 或从 ModelScope 下载
```

项目使用 `wespeaker-cnceleb-resnet34-LM` 模型（ONNX 格式）。如无现成模型，可将声纹识别降级为声纹注册库匹配模式（使用 ASR 管道中的 `funasr` 声纹特征替代）。

#### FunASR SenseVoice（ASR）

首次调用 `AudioPipeline` 时自动从 HuggingFace 下载：

```
Model: iic/SenseVoiceSmall
Cache: ~/.cache/huggingface/ 或指定目录
```

如需手动下载：

```bash
pip install modelscope
python -c "from modelscope.hub.snapshot_download import snapshot_download; snapshot_download('iic/SenseVoiceSmall', cache_dir='./models/funasr')"
```

#### moondream2 场景分类模型（可选）

`a_layer/config.py` 中 `ENABLE_SCENE_CLASSIFICATION = False`，默认关闭。如需开启，首次调用时自动下载 `vikhyatk/moondream2`。

---

## 四、配置文件

### 4.1 根目录 config.json

```json
{
    "llm_api_url": "https://api.deepseek.com/chat/completions",
    "llm_api_key": "your-api-key-here",
    "model": "deepseek-chat",
    "temperature": 0.7,
    "max_tokens": 256,
    "timeout": 30,
    "identity": {
        "face_similarity_threshold": 0.60,
        "min_sample_quality": 0.40,
        "merge_similarity_threshold": 0.70
    },
    "aggregation": {
        "min_window_seconds": 2.0,
        "max_window_seconds": 30.0,
        "person_change_delay": 1.0
    }
}
```

> `llm_api_url` 和 `llm_api_key` 必须配置，否则语义摘要使用默认值"事件聚合"。

### 4.2 A层 config.py

路径：`a_layer/config.py`

主要需要确认的路径项（已有默认值，如模型文件路径不同请修改）：

| 配置项                           | 默认值                                             | 说明                   |
| ----------------------------- | ----------------------------------------------- | -------------------- |
| `YOLO_MODEL`                  | `models/yolo26n.pt`                             | YOLO 模型路径            |
| `TRACKER_CONFIG`              | `models/botsort_custom.yaml`                    | BoTSort 配置路径         |
| `FACE_EMBEDDER_MODEL`         | `arcface_r50`                                   | InsightFace 人脸编码模型   |
| `VOICE_EMBEDDER_MODEL_PATH`   | `models/wespeaker/.../cnceleb_resnet34_LM.onnx` | 声纹 ONNX 路径           |
| `ENABLE_SCENE_CLASSIFICATION` | `False`                                         | 场景分类默认关闭             |
| `DEVICE`                      | `cuda`                                          | GPU 加速，CPU 时改为 `cpu` |

---

## 五、本地注册（可选）

对于已知人员（穿戴者或常客），可预先注册人脸和声纹，省去陌生人分配流程：

```bash
cd /mnt/b/Desktop/workspace/IronHeart_System

# 注册穿戴者人脸
python a_layer/register.py --id zhangsan --name 张三 \
    --faces /path/to/face_images/ \
    --voices /path/to/voice_clips/ \
    --wearer

# 查看已注册人员
python a_layer/register.py --list
```

注册后人脸图片放入 `data/faces/{person_id}/`，声纹放入 `data/voices/{person_id}/`。

---

## 六、运行

### 6.1 启动 A 层（感知层）

```bash
cd /mnt/b/Desktop/workspace/IronHeart_System
python a_layer/run.py --video /path/to/video.mp4
# 可选：--max-frames 3000 限制处理帧数
```

输出：

- 事件文件：`outputs/a_events_backup.jsonl`
- A层日志：`logs/a_layer.log`

### 6.2 启动 B 层（语义聚合层）

```bash
cd /mnt/b/Desktop/workspace/IronHeart_System
python b_layer/run.py
```

B 层订阅 A 层 MQ 队列（`a_events`），输出语义事件到 `b_events` 队列。

**MQ 依赖：** 需要消息队列服务（RabbitMQ/Redis），配置在 `shared/mq_client.py`。

### 6.3 完整流程（通过 MQTT 事件总线）

```bash
# 终端1：启动 A 层
python a_layer/run.py --video /path/to/video.mp4

# 终端2：启动 B 层
python b_layer/run.py
```

---

## 七、常见问题

### 7.1 InsightFace 下载失败

国内网络访问 HuggingFace/MetaInsight 可能受限，设置镜像：

```bash
export HF_ENDPOINT=https://hf-mirror.com
```

或在代码中：

```python
import os
os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'
```

### 7.2 GPU 内存不足

减小 `a_layer/config.py` 中的 `FACE_BATCH_SIZE`，或切换到 CPU：

```python
DEVICE = "cpu"
FACE_EMBEDDER_DEVICE = "cpu"
```

### 7.3 Silero-VAD 加载失败

Silero-VAD 依赖 PyTorch，请确保 `torch` 已正确安装（GPU 版需 CUDA 对应）。

### 7.4 声纹模型缺失

如果 `wespeaker-cnceleb-resnet34-LM.onnx` 不可用，A 层会自动降级到声纹注册库匹配模式（依赖 FunASR 内置声纹特征），不影响基本功能。

### 7.5 开启场景分类

将 `a_layer/config.py` 中：

```python
ENABLE_SCENE_CLASSIFICATION = True
```

> 注意：场景分类使用 moondream2，权重约 1-2GB，首次调用时自动下载。
