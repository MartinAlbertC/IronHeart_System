"""事件生成和输出模块"""
import json
import os
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional
import numpy as np

# Setup shared logger access for outbound event logging
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
try:
    from shared.logger import setup_logger, log_event_outbound
    _shared_logger = setup_logger("a_layer")
except ImportError:
    _shared_logger = None
    log_event_outbound = None

from src.core.schemas import (
    BaseEvent, FaceDetectionEvent, PersonTrackEvent, SceneDetectionEvent,
    SpeechSegmentEvent, UIStateChangeEvent, NotificationEvent,
    TimeInfo, SourceInfo, ConfidenceInfo, FaceDetectionPayload, PersonTrackPayload,
    SceneDetectionPayload
)
from src.core.utils import EventIDGenerator, timestamp_to_iso, normalize_bbox


class EventGenerator:
    """事件生成器"""

    def __init__(self, device_id: str = "glasses_01"):
        """
        初始化事件生成器

        Args:
            device_id: 设备 ID
        """
        self.device_id = device_id
        self.id_generator = EventIDGenerator()

    def generate_face_detection_event(self, face_info: Dict, track_id: int,
                                      timestamp: datetime, frame_width: int,
                                      frame_height: int) -> FaceDetectionEvent:
        """
        生成 FaceDetectionEvent

        Args:
            face_info: 人脸信息
            track_id: 追踪 ID
            timestamp: 时间戳
            frame_width: 帧宽度
            frame_height: 帧高度

        Returns:
            FaceDetectionEvent
        """
        event_id = self.id_generator.generate('fc')
        ts_iso = timestamp_to_iso(timestamp)

        time_info = TimeInfo(
            start_ts=ts_iso,
            end_ts=ts_iso,
            duration_ms=0
        )

        source_info = SourceInfo(device_id=self.device_id)

        confidence_info = ConfidenceInfo(
            detector_score=face_info['confidence'],
            quality_score=face_info['quality']['overall_quality'],
            completeness_score=0.95
        )

        payload = {
            'face_id_local': face_info['id'],
            'track_id': track_id,
            'alias': face_info.get('alias'),
            'bbox': face_info['bbox_norm'],
            'bbox_format': 'normalized_xywh',
            'yaw_pitch_roll': face_info.get('yaw_pitch_roll', [0.0, 0.0, 0.0]),
            'visibility': 'clear',
            'face_quality': face_info['quality'],
            'face_embedding': face_info['embedding']
        }

        event = FaceDetectionEvent(
            event_id=event_id,
            time=time_info,
            source=source_info,
            payload=payload,
            confidence=confidence_info
        )

        # 记录事件 ID 到 face_info，供后续 PersonTrackEvent 引用
        face_info['event_id'] = event_id

        return event

    def generate_person_track_event(self, track_info: 'TrackInfo',
                                    timestamp: datetime) -> PersonTrackEvent:
        """
        生成 PersonTrackEvent

        Args:
            track_info: 追踪信息
            timestamp: 时间戳

        Returns:
            PersonTrackEvent
        """
        event_id = self.id_generator.generate('pt')
        start_ts = timestamp_to_iso(track_info.start_time)
        end_ts = timestamp_to_iso(track_info.end_time)
        duration_ms = int((track_info.end_time - track_info.start_time).total_seconds() * 1000)

        time_info = TimeInfo(
            start_ts=start_ts,
            end_ts=end_ts,
            duration_ms=duration_ms
        )

        source_info = SourceInfo(device_id=self.device_id)

        # 计算平均置信度和质量评分
        confidences = [f['confidence'] for f in track_info.face_infos if f]
        quality_scores = [f['quality']['overall_quality'] for f in track_info.face_infos if f]

        confidence_info = ConfidenceInfo(
            detector_score=float(np.mean(confidences)) if confidences else 0.0,
            quality_score=float(np.mean(quality_scores)) if quality_scores else 0.0,
            completeness_score=0.95
        )

        # 获取最佳人脸作为代表性编码
        best_face = track_info.get_best_face()

        representative_embedding = None
        if best_face:
            representative_embedding = {
                'model': best_face['embedding']['model'],
                'vector': best_face['embedding']['vector'],
                'vector_dim': best_face['embedding']['vector_dim'],
                'norm': best_face['embedding']['norm'],
                'source_event_id': best_face['event_id']
            }

        payload = {
            'track_id': f'track_person_{track_info.track_id:03d}',
            'face_event_ids': track_info.face_event_ids,
            'face_ids': [f['id'] for f in track_info.face_infos if f],
            'track_stability': float(min(1.0, track_info.age / 30)),
            'relative_position': track_info.relative_position,
            'distance_bucket': 'near',
            'representative_embedding': representative_embedding
        }

        event = PersonTrackEvent(
            event_id=event_id,
            time=time_info,
            source=source_info,
            payload=payload,
            confidence=confidence_info
        )

        return event

    def generate_scene_detection_event(self, completed_scene: Dict) -> SceneDetectionEvent:
        """
        生成 SceneDetectionEvent。

        Args:
            completed_scene: 已结束场景的描述，字段：
                scene_label (str)      - 场景标签
                start_ts (datetime)    - 场景开始时间
                end_ts (datetime)      - 场景结束时间
                confidence (float)     - CLIP 分类置信度
                objects (List[str])    - YOLO 检测到的非人物体列表
                location_hint (str)    - 位置提示（可选）

        Returns:
            SceneDetectionEvent
        """
        event_id = self.id_generator.generate('sc')
        start_ts = timestamp_to_iso(completed_scene['start_ts'])
        end_ts = timestamp_to_iso(completed_scene['end_ts'])
        duration_ms = int(
            (completed_scene['end_ts'] - completed_scene['start_ts']).total_seconds() * 1000
        )

        time_info = TimeInfo(
            start_ts=start_ts,
            end_ts=end_ts,
            duration_ms=duration_ms
        )

        source_info = SourceInfo(device_id=self.device_id)

        confidence_info = ConfidenceInfo(
            detector_score=completed_scene.get('confidence', 1.0),
            quality_score=0.9,
            completeness_score=0.85
        )

        payload = {
            'scene_label': completed_scene['scene_label'],
            'objects': completed_scene.get('objects', []),
            'ocr_texts': [],
            'location_hint': completed_scene.get('location_hint', 'unknown'),
        }

        return SceneDetectionEvent(
            event_id=event_id,
            subtype="generated_description",
            time=time_info,
            source=source_info,
            payload=payload,
            confidence=confidence_info
        )

    def generate_speech_segment_event(self, segment: Dict) -> SpeechSegmentEvent:
        """
        生成 SpeechSegmentEvent。

        Args:
            segment: 语音段信息，字段：
                text (str)              - ASR 识别文本
                language (str)          - 识别语言
                start_ts (datetime)     - 段落开始时间
                end_ts (datetime)       - 段落结束时间
                volume (float)          - 平均音量（0-1）
                voice_embedding (dict)  - 声纹 embedding（含 model/vector/vector_dim/norm）
                turn_index (int)        - 本次会话中第几段话

        Returns:
            SpeechSegmentEvent
        """
        event_id = self.id_generator.generate('sp')
        start_ts = timestamp_to_iso(segment['start_ts'])
        end_ts = timestamp_to_iso(segment['end_ts'])
        duration_ms = int(
            (segment['end_ts'] - segment['start_ts']).total_seconds() * 1000
        )

        time_info = TimeInfo(
            start_ts=start_ts,
            end_ts=end_ts,
            duration_ms=duration_ms
        )

        source_info = SourceInfo(
            device_id=self.device_id,
            modality="audio",
            channel="microphone"
        )

        confidence_info = ConfidenceInfo(
            detector_score=segment.get('asr_confidence', 0.9),
            quality_score=segment.get('volume', 0.5),
            completeness_score=0.9
        )

        payload = {
            'text': segment['text'],
            'language': segment.get('language', 'zh'),
            'speech_event': segment.get('speech_event', 'unknown'),
            'speaker_tag': 'speaker_unknown',
            'speaker_role_hint': 'unknown',
            'turn_index': segment.get('turn_index', 0),
            'audio_features': {
                'volume': round(segment.get('volume', 0.0), 4),
                'speech_rate': round(segment.get('speech_rate', 0.0), 4),
            },
            'voice_embedding': segment.get('voice_embedding'),
        }

        return SpeechSegmentEvent(
            event_id=event_id,
            time=time_info,
            source=source_info,
            payload=payload,
            confidence=confidence_info
        )

    def generate_ui_state_change_event(self, ui_info: Dict) -> UIStateChangeEvent:
        """
        生成 UIStateChangeEvent。

        Args:
            ui_info: UI 状态信息，字段：
                subtype (str)             - 子类型，如 chat_thread_opened
                app_name (str)            - 应用名，如 Feishu
                page_type (str)           - 页面类型
                thread_id (str)           - 会话 ID（可选）
                thread_title (str)        - 会话标题（可选）
                input_box_focused (bool)  - 输入框是否聚焦（可选）
                unread_count (int)        - 未读数（可选）
                timestamp (datetime)      - 事件时间（可选，默认 now）

        Returns:
            UIStateChangeEvent
        """
        event_id = self.id_generator.generate('ui')
        ts = ui_info.get('timestamp', datetime.now())
        ts_iso = timestamp_to_iso(ts)

        time_info = TimeInfo(
            start_ts=ts_iso,
            end_ts=ts_iso,
            duration_ms=0
        )

        source_info = SourceInfo(
            device_id=self.device_id,
            modality="ui",
            channel="foreground_app",
            platform="feishu",
        )

        confidence_info = ConfidenceInfo(
            detector_score=ui_info.get('detector_score', 0.98),
            quality_score=1.0,
            completeness_score=0.95
        )

        payload = {
            'app_name': ui_info.get('app_name', 'Feishu'),
            'page_type': ui_info.get('page_type', 'unknown'),
            'thread_id': ui_info.get('thread_id', ''),
            'thread_title': ui_info.get('thread_title', ''),
            'input_box_focused': ui_info.get('input_box_focused', False),
            'unread_count': ui_info.get('unread_count', 0),
        }

        return UIStateChangeEvent(
            event_id=event_id,
            subtype=ui_info.get('subtype', 'chat_thread_opened'),
            time=time_info,
            source=source_info,
            payload=payload,
            confidence=confidence_info
        )

    def generate_notification_event(self, notif_info: Dict) -> NotificationEvent:
        """
        生成 NotificationEvent。

        Args:
            notif_info: 通知信息，字段：
                subtype (str)             - 子类型，如 message_notification
                app_name (str)            - 应用名，如 Feishu
                notification_type (str)   - 通知类型，如 dm_message
                title (str)               - 通知标题（发送者名称等）
                preview_text (str)        - 预览文本（消息摘要）
                thread_id (str)           - 会话 ID（可选）
                priority_hint (str)       - 优先级提示（可选）
                timestamp (datetime)      - 事件时间（可选，默认 now）

        Returns:
            NotificationEvent
        """
        event_id = self.id_generator.generate('nt')
        ts = notif_info.get('timestamp', datetime.now())
        ts_iso = timestamp_to_iso(ts)

        time_info = TimeInfo(
            start_ts=ts_iso,
            end_ts=ts_iso,
            duration_ms=0
        )

        source_info = SourceInfo(
            device_id=self.device_id,
            modality="system_signal",
            channel="notification_center",
            platform="feishu",
        )

        confidence_info = ConfidenceInfo(
            detector_score=notif_info.get('detector_score', 0.99),
            quality_score=1.0,
            completeness_score=0.93
        )

        payload = {
            'app_name': notif_info.get('app_name', 'Feishu'),
            'notification_type': notif_info.get('notification_type', 'unknown'),
            'title': notif_info.get('title', ''),
            'preview_text': notif_info.get('preview_text', ''),
            'thread_id': notif_info.get('thread_id', ''),
            'priority_hint': notif_info.get('priority_hint', 'unknown'),
        }

        return NotificationEvent(
            event_id=event_id,
            subtype=notif_info.get('subtype', 'message_notification'),
            time=time_info,
            source=source_info,
            payload=payload,
            confidence=confidence_info
        )


class EventSink:
    """事件输出"""

    def __init__(self, output_file: str, append: bool = False):
        """
        初始化事件输出

        Args:
            output_file: 输出文件路径
            append: True 时追加写入（用于集成测试多管道合并输出），False 时清空重写
        """
        self.output_file = output_file
        os.makedirs(os.path.dirname(output_file), exist_ok=True)

        if not append and os.path.exists(output_file):
            os.remove(output_file)

        self.file_handle = open(output_file, 'a', encoding='utf-8')
        self.event_count = 0
        self._lock = threading.Lock()
        self._mq_client = None  # MQ 推送客户端（懒加载）

    def write_event(self, event: BaseEvent) -> str:
        """
        写入事件（线程安全）+ 推送到 MQ

        Args:
            event: 事件对象

        Returns:
            event_id
        """
        event_dict = event.to_dict()
        event_json = json.dumps(event_dict, ensure_ascii=False)
        with self._lock:
            self.file_handle.write(event_json + '\n')
            self.file_handle.flush()
            self.event_count += 1

        # MQ 推送（懒加载，失败不影响文件写入）
        if self._mq_client is None:
            try:
                from shared.mq_client import MQClient
                self._mq_client = MQClient()
            except Exception:
                self._mq_client = False  # 标记为不可用
        if self._mq_client:
            try:
                self._mq_client.publish("a_events", event_dict)
            except Exception:
                pass

        # Enhanced logging: complete outbound event
        if _shared_logger and log_event_outbound:
            log_event_outbound(_shared_logger, "B", "PerceptionEvent", event_dict)

        return event.event_id

    def close(self):
        """关闭输出文件"""
        if self.file_handle:
            self.file_handle.close()

    def __del__(self):
        """析构函数"""
        self.close()


class TrackInfo:
    """追踪信息"""

    def __init__(self, track_id: int, first_box: tuple, first_face_info: Optional[Dict],
                 start_time: datetime):
        """
        初始化追踪信息

        Args:
            track_id: 追踪 ID
            first_box: 第一个检测框 (x1, y1, x2, y2)
            first_face_info: 第一个人脸信息
            start_time: 开始时间
        """
        self.track_id = track_id
        self.start_time = start_time
        self.end_time = start_time
        self.boxes = [first_box]
        self.face_infos = [first_face_info]
        self.face_event_ids = []
        self.age = 1
        self.quality_scores = []
        self.last_center = self._calc_center(first_box)
        self.relative_position = "center"

    def update(self, box: tuple, face_info: Optional[Dict], timestamp: datetime):
        """
        更新追踪信息

        Args:
            box: 新检测框
            face_info: 新人脸信息
            timestamp: 当前时间
        """
        self.boxes.append(box)
        self.face_infos.append(face_info)
        if face_info:
            self.quality_scores.append(face_info['quality']['overall_quality'])
            if 'event_id' in face_info:
                self.face_event_ids.append(face_info['event_id'])

        self.age += 1
        self.end_time = timestamp
        self.last_center = self._calc_center(box)
        self._update_relative_position()

    def get_best_face(self) -> Optional[Dict]:
        """获取质量最好的人脸"""
        if not self.face_infos:
            return None

        best_idx = 0
        best_quality = 0.0
        for i, face in enumerate(self.face_infos):
            if face:
                quality = face['quality']['overall_quality']
                if quality > best_quality:
                    best_quality = quality
                    best_idx = i

        return self.face_infos[best_idx]

    def _calc_center(self, box: tuple) -> tuple:
        """计算检测框中心"""
        x1, y1, x2, y2 = box
        return ((x1 + x2) / 2, (y1 + y2) / 2)

    def _update_relative_position(self):
        """更新相对位置"""
        # 基于平均 x 坐标
        centers_x = [c[0] for c in [self._calc_center(b) for b in self.boxes]]
        if centers_x:
            avg_x = np.mean(centers_x)
            # 假设图像宽度为 640
            frame_width = 640
            if avg_x < frame_width / 3:
                self.relative_position = "left"
            elif avg_x > frame_width * 2 / 3:
                self.relative_position = "right"
            else:
                self.relative_position = "center"
