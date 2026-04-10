"""全局配置文件"""

import os
from pathlib import Path

# 项目根路径（config.py 在 src/core/ 下，需要向上两级到达项目根目录）
PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
MODELS_DIR = PROJECT_ROOT / "models"
OUTPUT_DIR = PROJECT_ROOT / "outputs"

# 创建输出目录
OUTPUT_DIR.mkdir(exist_ok=True)

# ============= 设备配置 =============
DEVICE = "cuda"  # cuda 或 cpu
DEVICE_ID = "glasses_01"
DEVICE_TYPE = "smart_glasses"

# ============= 视频配置 =============
VIDEO_FPS = 30

# ============= 快线路配置 =============

# YOLOv8 配置
YOLO_MODEL = str(PROJECT_ROOT / "yolo26n.pt")
YOLO_CONF_THRESHOLD = 0.5
YOLO_IOU_THRESHOLD = 0.45

# BoTSort 跟踪器配置
TRACKER_CONFIG = str(PROJECT_ROOT / "botsort_custom.yaml")
MIN_TRACK_AGE = 5  # 最少持续帧数才输出 person_track 事件
ENABLE_PERSON_TRACK_EVENT = False  # 是否输出 person_track 事件

# 人脸检测配置
FACE_DETECTOR_BACKEND = "mediapipe"  # mediapipe 或 retinaface
FACE_CONF_THRESHOLD = 0.6
MIN_FACE_QUALITY = 0.5
# 跳帧 embedding：同一 track_id 每隔 N 帧才重新调用 insightface
# 期间直接复用上一次的人脸信息
FACE_REEMBED_INTERVAL = 15

# 人脸编码配置
FACE_EMBEDDER_MODEL = "arcface_r50"  # arcface_r50 或 arcface_mobilenet
FACE_EMBEDDER_DEVICE = DEVICE
FACE_EMBEDDING_DIM = 512
FACE_EMBEDDING_NORM = "l2"

# 人脸去重配置
# 余弦相似度阈值：低于此值认为人脸特征发生显著变化（如正脸→侧脸），才输出新事件
FACE_CHANGE_THRESHOLD = 0.75

# 人脸批处理
FACE_BATCH_SIZE = 16

# ============= 中线路配置 =============

# 场景描述配置（两级触发：廉价直方图变化检测 + 按需 Florence-2 推理）
ENABLE_SCENE_CLASSIFICATION = True
FLORENCE2_MODEL_DIR = str(PROJECT_ROOT / "models/AI-ModelScope/Florence-2-base")
SCENE_CHANGE_THRESHOLD = 0.75  # 直方图相关性低于此值视为场景疑似变化
SCENE_CHANGE_COOLDOWN_SEC = 5.0  # 两次 Florence-2 推理之间的最小间隔（秒）

ENABLE_OCR = False

# ============= 音频管道配置 =============

# 音频基础参数
AUDIO_SAMPLE_RATE = 16000  # 采样率（VAD/ASR/声纹均要求 16kHz）
AUDIO_CHUNK_MS = 32  # 对应 Silero-VAD 的 512 samples@16kHz

# VAD 参数
AUDIO_CHUNK_SAMPLES = 512  # Silero-VAD 严格要求 512 samples@16kHz（32ms）
VAD_ONSET_THRESHOLD = 0.5  # 语音段开始概率阈值
VAD_OFFSET_THRESHOLD = 0.35  # 语音段结束概率阈值
VAD_MIN_SPEECH_MS = 300  # 最短语音段（毫秒），过短的忽略
VAD_MIN_SILENCE_MS = 700  # 连续静音超过此时长认定段落结束（700ms 避免把歌词/慢语速切成碎片）
VAD_MAX_SPEECH_MS = 30000  # 最长语音段（毫秒），超长则强制切割

# ASR 参数
ASR_MODEL = "iic/SenseVoiceSmall"  # FunASR SenseVoice 模型（效果优于 paraformer-zh）
ASR_MODEL_DIR = str(MODELS_DIR / "funasr")  # 本地缓存目录（首次自动下载）

# 声纹参数
VOICE_EMBEDDER_MODEL_PATH = str(
    MODELS_DIR / "wespeaker/wespeaker-cnceleb-resnet34-LM/cnceleb_resnet34_LM.onnx"
)
VOICE_EMBEDDING_DIM = 256
VOICE_EMBEDDING_MODEL_NAME = "wespeaker_cnceleb_resnet34"

# ============= 事件输出配置 =============
EVENT_OUTPUT_FILE = str(OUTPUT_DIR / "events.jsonl")
ENABLE_DB_OUTPUT = False

# ============= 飞书管道配置 =============
FEISHU_APP_ID = ""
FEISHU_APP_SECRET = ""
FEISHU_BOT_MODE = "websocket"      # websocket 或 webhook
FEISHU_WEBHOOK_PORT = 8080         # webhook 模式监听端口
FEISHU_VERIFICATION_TOKEN = ""     # webhook 模式验证 token
FEISHU_ENCRYPT_KEY = ""            # webhook 模式加密 key

# ============= 日志配置 =============
LOG_LEVEL = "INFO"
LOG_FILE = str(OUTPUT_DIR / "vision_pipeline.log")
AUDIO_LOG_FILE = str(OUTPUT_DIR / "audio_pipeline.log")
FEISHU_LOG_FILE = str(OUTPUT_DIR / "feishu_pipeline.log")

# ============= 调试配置 =============
DEBUG_MODE = False
SAVE_VISUALIZATION = False
VISUALIZATION_OUTPUT = str(OUTPUT_DIR / "output_with_detections.mp4")
