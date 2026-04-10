"""事件数据模型定义"""
from dataclasses import dataclass, asdict, field
from typing import List, Dict, Optional, Any
from datetime import datetime
import json


@dataclass
class TimeInfo:
    """时间信息"""
    start_ts: str
    end_ts: str
    duration_ms: int


@dataclass
class SourceInfo:
    """事件来源信息"""
    device_id: str = "glasses_01"
    device_type: str = "smart_glasses"
    modality: str = "vision"
    channel: str = "front_camera"
    platform: str = "offline"


@dataclass
class ConfidenceInfo:
    """置信度信息"""
    detector_score: float
    quality_score: float
    completeness_score: float


@dataclass
class FaceEmbedding:
    """人脸编码"""
    model: str
    vector: List[float]
    vector_dim: int
    norm: str = "l2"


@dataclass
class FaceQuality:
    """人脸质量评估"""
    blur_score: float
    illumination_score: float
    pose_score: float
    overall_quality: float


@dataclass
class FaceDetectionPayload:
    """人脸检测事件 payload"""
    face_id_local: str
    bbox: List[float]  # normalized xywh
    bbox_format: str = "normalized_xywh"
    yaw_pitch_roll: List[float] = field(default_factory=list)
    visibility: str = "clear"
    face_quality: Optional[Dict[str, float]] = None
    face_embedding: Optional[Dict[str, Any]] = None


@dataclass
class PersonTrackPayload:
    """人物追踪事件 payload"""
    track_id: str
    face_event_ids: List[str] = field(default_factory=list)
    face_ids: List[str] = field(default_factory=list)
    track_stability: float = 0.0
    relative_position: str = "center"
    distance_bucket: str = "near"
    representative_embedding: Optional[Dict[str, Any]] = None


@dataclass
class SceneDetectionPayload:
    """场景检测事件 payload"""
    scene_label: str
    objects: List[str] = field(default_factory=list)
    ocr_texts: List[str] = field(default_factory=list)
    location_hint: str = "indoor_business_space"


@dataclass
class BaseEvent:
    """基础事件类"""
    event_id: str
    event_type: str
    subtype: str
    time: TimeInfo
    source: SourceInfo
    payload: Dict[str, Any]
    confidence: ConfidenceInfo

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            'event_id': self.event_id,
            'event_type': self.event_type,
            'subtype': self.subtype,
            'time': asdict(self.time),
            'source': asdict(self.source),
            'payload': self.payload if isinstance(self.payload, dict) else asdict(self.payload),
            'confidence': asdict(self.confidence)
        }

    def to_json(self) -> str:
        """转换为 JSON 字符串"""
        return json.dumps(self.to_dict(), ensure_ascii=False)


class FaceDetectionEvent(BaseEvent):
    """人脸检测事件 - 工厂方法"""
    def __init__(self, event_id, time, source, payload, confidence,
                 subtype="single_face"):
        super().__init__(
            event_id=event_id,
            event_type="face_detection",
            subtype=subtype,
            time=time,
            source=source,
            payload=payload,
            confidence=confidence
        )


class PersonTrackEvent(BaseEvent):
    """人物追踪事件 - 工厂方法"""
    def __init__(self, event_id, time, source, payload, confidence,
                 subtype="single_person_stable_track"):
        super().__init__(
            event_id=event_id,
            event_type="person_track",
            subtype=subtype,
            time=time,
            source=source,
            payload=payload,
            confidence=confidence
        )


class SceneDetectionEvent(BaseEvent):
    """场景检测事件 - 工厂方法"""
    def __init__(self, event_id, time, source, payload, confidence,
                 subtype="scene_detection"):
        super().__init__(
            event_id=event_id,
            event_type="scene_detection",
            subtype=subtype,
            time=time,
            source=source,
            payload=payload,
            confidence=confidence
        )


class SpeechSegmentEvent(BaseEvent):
    """语音片段事件 - 工厂方法"""
    def __init__(self, event_id, time, source, payload, confidence,
                 subtype="other_speech"):
        super().__init__(
            event_id=event_id,
            event_type="speech_segment",
            subtype=subtype,
            time=time,
            source=source,
            payload=payload,
            confidence=confidence
        )


@dataclass
class UIStateChangePayload:
    """UI 状态变化事件 payload"""
    app_name: str
    page_type: str
    thread_id: str = ""
    thread_title: str = ""
    input_box_focused: bool = False
    unread_count: int = 0


@dataclass
class NotificationPayload:
    """通知事件 payload"""
    app_name: str
    notification_type: str
    title: str
    preview_text: str = ""
    thread_id: str = ""
    priority_hint: str = "unknown"


class UIStateChangeEvent(BaseEvent):
    """UI 状态变化事件 - 工厂方法"""
    def __init__(self, event_id, time, source, payload, confidence,
                 subtype="chat_thread_opened"):
        super().__init__(
            event_id=event_id,
            event_type="ui_state_change",
            subtype=subtype,
            time=time,
            source=source,
            payload=payload,
            confidence=confidence
        )


class NotificationEvent(BaseEvent):
    """通知事件 - 工厂方法"""
    def __init__(self, event_id, time, source, payload, confidence,
                 subtype="message_notification"):
        super().__init__(
            event_id=event_id,
            event_type="notification_event",
            subtype=subtype,
            time=time,
            source=source,
            payload=payload,
            confidence=confidence
        )
