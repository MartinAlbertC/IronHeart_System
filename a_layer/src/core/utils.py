"""工具函数"""
import logging
import numpy as np
from datetime import datetime
import os
from pathlib import Path


def setup_logger(log_file: str, level: str = "INFO") -> logging.Logger:
    """设置日志"""
    os.makedirs(os.path.dirname(log_file), exist_ok=True)

    logger = logging.getLogger("VisionPipeline")
    logger.setLevel(getattr(logging, level))

    # 文件处理器
    fh = logging.FileHandler(log_file, encoding='utf-8')
    fh.setLevel(getattr(logging, level))

    # 控制台处理器
    ch = logging.StreamHandler()
    ch.setLevel(getattr(logging, level))

    # 格式器
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    fh.setFormatter(formatter)
    ch.setFormatter(formatter)

    logger.addHandler(fh)
    logger.addHandler(ch)

    return logger


class EventIDGenerator:
    """事件 ID 生成器"""
    def __init__(self):
        self.counter = 0
        self.start_time = datetime.now()

    def generate(self, prefix: str) -> str:
        """
        生成唯一事件 ID

        Args:
            prefix: 事件类型前缀 (fc, pt, sc 等)

        Returns:
            event_id: 形如 evt_fc_20260312_143022_000001
        """
        self.counter += 1
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        return f'evt_{prefix}_{timestamp}_{self.counter:06d}'


def timestamp_to_iso(ts: datetime) -> str:
    """将 datetime 转换为 ISO 格式字符串"""
    return ts.isoformat() + 'Z'


def normalize_bbox(bbox: tuple, frame_height: int, frame_width: int) -> list:
    """
    将像素坐标的 bbox 转换为归一化坐标 [x, y, w, h]

    Args:
        bbox: (x1, y1, x2, y2) 像素坐标
        frame_height: 帧高度
        frame_width: 帧宽度

    Returns:
        [x_norm, y_norm, w_norm, h_norm] 归一化坐标
    """
    x1, y1, x2, y2 = bbox
    x = x1 / frame_width
    y = y1 / frame_height
    w = (x2 - x1) / frame_width
    h = (y2 - y1) / frame_height
    return [x, y, w, h]


def crop_bbox(frame, bbox, padding=10):
    """
    从帧中裁剪 bbox 区域

    Args:
        frame: 输入帧
        bbox: (x1, y1, x2, y2) 像素坐标
        padding: 裁剪时的扩展像素

    Returns:
        crop: 裁剪后的图像
    """
    x1, y1, x2, y2 = bbox
    h, w = frame.shape[:2]

    x1 = max(0, x1 - padding)
    y1 = max(0, y1 - padding)
    x2 = min(w, x2 + padding)
    y2 = min(h, y2 + padding)

    return frame[y1:y2, x1:x2]


def calculate_iou(bbox1, bbox2):
    """计算两个 bbox 的 IoU"""
    x1_min, y1_min, x1_max, y1_max = bbox1
    x2_min, y2_min, x2_max, y2_max = bbox2

    inter_xmin = max(x1_min, x2_min)
    inter_ymin = max(y1_min, y2_min)
    inter_xmax = min(x1_max, x2_max)
    inter_ymax = min(y1_max, y2_max)

    if inter_xmax < inter_xmin or inter_ymax < inter_ymin:
        return 0.0

    inter_area = (inter_xmax - inter_xmin) * (inter_ymax - inter_ymin)
    box1_area = (x1_max - x1_min) * (y1_max - y1_min)
    box2_area = (x2_max - x2_min) * (y2_max - y2_min)
    union_area = box1_area + box2_area - inter_area

    return inter_area / union_area if union_area > 0 else 0.0
