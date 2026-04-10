"""视觉管道核心模块"""

import cv2
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Set
import time

from ultralytics import YOLO
from src.vision.face_analyzer import FaceAnalyzer, FaceQualityAssessor
from src.core.event_generator import EventGenerator, EventSink, TrackInfo
from src.core.utils import crop_bbox, normalize_bbox, EventIDGenerator
import src.core.config as config


class TrackStateManager:
    """追踪状态管理器"""

    def __init__(self, min_track_age: int = 5):
        """
        初始化追踪管理器

        Args:
            min_track_age: 最小追踪帧数，达到此数才输出 person_track 事件
        """
        self.active_tracks = {}  # {track_id: TrackInfo}
        self.completed_tracks = []  # 已完成的追踪
        self.min_track_age = min_track_age

    def update(self, tracks: List[Dict], timestamp: datetime):
        """
        更新追踪状态

        Args:
            tracks: 当前帧的追踪结果
            timestamp: 时间戳
        """
        current_ids = set()

        # 更新活跃追踪
        for track in tracks:
            track_id = track["track_id"]
            current_ids.add(track_id)

            if track_id not in self.active_tracks:
                # 新追踪
                self.active_tracks[track_id] = TrackInfo(
                    track_id=track_id,
                    first_box=track["box"],
                    first_face_info=track.get("face_info"),
                    start_time=timestamp,
                )
            else:
                # 更新现有追踪
                self.active_tracks[track_id].update(
                    track["box"], track.get("face_info"), timestamp
                )

        # 识别丢失的追踪
        lost_ids = set(self.active_tracks.keys()) - current_ids

        for lost_id in lost_ids:
            track_info = self.active_tracks.pop(lost_id)
            # 如果追踪足够长，标记为完成
            if track_info.age >= self.min_track_age:
                self.completed_tracks.append(track_info)

    def pop_completed_tracks(self) -> List[TrackInfo]:
        """获取并清空已完成的追踪"""
        completed = self.completed_tracks
        self.completed_tracks = []
        return completed

    def get_active_track_count(self) -> int:
        """获取活跃追踪数量"""
        return len(self.active_tracks)


class SceneStateTracker:
    """两级场景变化检测器。

    第一级：每帧做廉价的 HSV 直方图对比，发现疑似变化时触发。
    第二级：触发后调用外部 CLIP 分类器，用冷却期防止频繁推理。
    """

    def __init__(self, change_threshold: float, cooldown_sec: float):
        self.change_threshold = change_threshold
        self.cooldown_sec = cooldown_sec
        self._ref_hist = None
        self._current_label: Optional[str] = None
        self._scene_start_ts: Optional[datetime] = None
        self._last_clip_time: float = 0.0

    def is_scene_changed(self, frame: np.ndarray) -> bool:
        """廉价变化检测：将帧缩小后对比 HSV 直方图相关性。"""
        small = cv2.resize(frame, (64, 64))
        hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
        hist = cv2.calcHist([hsv], [0, 1], None, [16, 16], [0, 180, 0, 256])
        cv2.normalize(hist, hist)

        if self._ref_hist is None:
            self._ref_hist = hist
            return True

        score = float(cv2.compareHist(self._ref_hist, hist, cv2.HISTCMP_CORREL))
        return score < self.change_threshold

    def cooldown_elapsed(self) -> bool:
        """冷却期是否已过（防止 CLIP 被频繁触发）。"""
        return time.time() - self._last_clip_time >= self.cooldown_sec

    def on_description(
        self, description: str, timestamp: datetime, objects: List[str]
    ) -> Optional[Dict]:
        """Florence-2 返回描述后更新状态。

        每次触发必然关闭上一个场景、开启新场景，
        去重由上游的直方图检测 + 冷却期保证。
        """
        self._last_clip_time = time.time()
        self._ref_hist = None  # 触发后重置参考帧

        completed = None
        if self._current_label is not None:
            completed = {
                "scene_label": self._current_label,
                "start_ts": self._scene_start_ts,
                "end_ts": timestamp,
                "objects": objects,
            }

        self._current_label = description
        self._scene_start_ts = timestamp
        return completed

    def flush(self, timestamp: datetime, objects: List[str]) -> Optional[Dict]:
        """视频结束时输出当前未关闭的场景。"""
        if self._current_label is not None:
            return {
                "scene_label": self._current_label,
                "start_ts": self._scene_start_ts,
                "end_ts": timestamp,
                "objects": objects,
            }
        return None


class VisionPipeline:
    """视觉处理管道"""

    def __init__(self, config_module=None, event_sink: Optional[EventSink] = None):
        """
        初始化视觉管道

        Args:
            config_module: 配置模块 (默认使用 src.config)
            event_sink: 外部传入的 EventSink（并行模式下与音频管道共享）；
                        None 时自动创建
        """
        if config_module is None:
            config_module = config

        self.config = config_module
        self.logger = self._setup_logger()

        self.logger.info("初始化视觉管道...")

        # 初始化检测和编码模块
        self.yolo_model = None
        self.face_analyzer = None
        # 跳帧缓存：{track_id: {'face_info': ..., 'last_frame': int}}
        self.face_cache = {}
        # 人脸去重：记录每个 track_id 最后一次输出事件时的 embedding
        self.last_emitted_embeddings = {}

        # 场景分类模块（按需加载）
        self.scene_classifier = None
        self.scene_tracker = None
        self._scene_objects: Set[str] = set()  # 当前场景积累的 YOLO 物体

        # 初始化事件处理
        self.event_generator = EventGenerator(device_id=config_module.DEVICE_ID)
        self.event_sink = (
            event_sink
            if event_sink is not None
            else EventSink(output_file=config_module.EVENT_OUTPUT_FILE)
        )

        # 初始化追踪管理
        self.track_manager = TrackStateManager(
            min_track_age=config_module.MIN_TRACK_AGE
        )

        # 加载模型
        self._load_models()

        self.logger.info("视觉管道初始化完成")

    def _setup_logger(self):
        """设置日志"""
        from src.core.utils import setup_logger

        return setup_logger(log_file=self.config.LOG_FILE, level=self.config.LOG_LEVEL)

    def _load_models(self):
        """加载所有模型"""
        self.logger.info("加载 YOLO 模型...")
        try:
            self.yolo_model = YOLO(self.config.YOLO_MODEL)
            self.logger.info(f"{self.config.YOLO_MODEL} 模型加载成功")
        except Exception as e:
            self.logger.error(f"{self.config.YOLO_MODEL}模型加载失败: {e}")
            raise

        self.logger.info("加载人脸分析模型 (insightface)...")
        try:
            self.face_analyzer = FaceAnalyzer(
                model_name=self.config.FACE_EMBEDDER_MODEL,
                device=self.config.FACE_EMBEDDER_DEVICE,
            )
            self.logger.info("人脸分析模型加载成功")
        except Exception as e:
            self.logger.error(f"人脸分析模型加载失败: {e}")
            raise

        if self.config.ENABLE_SCENE_CLASSIFICATION:
            self.logger.info(f"加载场景描述模型 (Florence-2)...")
            try:
                from src.vision.scene_classifier import SceneClassifier

                self.scene_classifier = SceneClassifier(
                    model_dir=self.config.FLORENCE2_MODEL_DIR, device=self.config.DEVICE
                )
                self.scene_tracker = SceneStateTracker(
                    change_threshold=self.config.SCENE_CHANGE_THRESHOLD,
                    cooldown_sec=self.config.SCENE_CHANGE_COOLDOWN_SEC,
                )
                self.logger.info("场景描述模型加载成功")
            except Exception as e:
                self.logger.warning(f"场景描述模型加载失败，场景检测已禁用: {e}")
                self.scene_classifier = None
                self.scene_tracker = None

    def process_video(
        self,
        video_path: str,
        max_frames: Optional[int] = None,
        start_time: Optional[datetime] = None,
    ):
        """
        处理视频文件

        Args:
            video_path: 视频文件路径
            max_frames: 最大处理帧数 (None = 全部)
            start_time: 时间轴基准（并行模式下由外部传入以对齐音频时间戳）；
                        None 时自动用 datetime.now()
        """
        self.logger.info(f"开始处理视频: {video_path}")

        # 打开视频
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            self.logger.error(f"无法打开视频文件: {video_path}")
            raise IOError(f"Cannot open video: {video_path}")

        # 获取视频信息
        fps = int(cap.get(cv2.CAP_PROP_FPS))
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        self.logger.info(
            f"视频信息: {frame_width}x{frame_height}, {fps} FPS, {total_frames} 帧"
        )

        frame_count = 0
        proc_start = time.time()
        # 时间轴基准：外部传入时对齐音频，否则用当前时刻
        video_start_time: datetime = (
            start_time if start_time is not None else datetime.now()
        )

        try:
            while True:
                ret, frame = cap.read()
                if not ret:
                    break

                frame_count += 1

                if max_frames and frame_count > max_frames:
                    break

                # 用视频时间（帧序号 / 视频帧率）计算时间戳，与音频偏移量对齐
                video_offset_sec = (frame_count - 1) / fps
                timestamp = video_start_time + timedelta(seconds=video_offset_sec)

                # 快线路：人体检测和追踪
                tracks = self._detect_and_track(frame, frame_width, frame_height)

                # 快线路：人脸检测和编码（含跳帧缓存）
                tracks_with_faces = self._detect_and_embed_faces(
                    frame, tracks, frame_width, frame_height, frame_count
                )

                # 生成 face_detection 事件（缓存帧不重复生成）
                for track in tracks_with_faces:
                    fi = track.get("face_info")
                    if fi and not fi.get("from_cache"):
                        track_id = track["track_id"]
                        embedding = fi["embedding"]

                        # 去重检查：只在新人脸或特征变化显著时输出事件
                        if self._should_emit_face_event(track_id, embedding):
                            event = self.event_generator.generate_face_detection_event(
                                face_info=fi,
                                track_id=track_id,
                                timestamp=timestamp,
                                frame_width=frame_width,
                                frame_height=frame_height,
                            )
                            self.logger.info(f"\n{'='*70}\n>>> VISION DETECTED: Face | track_id={track_id} | confidence={fi['confidence']:.3f} | quality={fi['quality']['overall_quality']:.3f}\n{'='*70}")
                            self.event_sink.write_event(event)
                            # 保存向量数组用于后续比较
                            self.last_emitted_embeddings[track_id] = np.array(embedding['vector'])

                # 更新追踪管理器
                self.track_manager.update(tracks_with_faces, timestamp)

                # 输出已完成的追踪事件
                if self.config.ENABLE_PERSON_TRACK_EVENT:
                    completed_tracks = self.track_manager.pop_completed_tracks()
                    for track_info in completed_tracks:
                        event = self.event_generator.generate_person_track_event(
                            track_info=track_info, timestamp=timestamp
                        )
                        self.logger.info(f"\n{'='*70}\n>>> VISION DETECTED: PersonTrack | track_id={track_info.track_id} | age={track_info.age} | faces={len(track_info.face_event_ids)}\n{'='*70}")
                        self.event_sink.write_event(event)

                # 场景检测（两级触发）
                if self.scene_tracker is not None:
                    if (
                        self.scene_tracker.is_scene_changed(frame)
                        and self.scene_tracker.cooldown_elapsed()
                    ):
                        description = self.scene_classifier.describe(frame)
                        completed = self.scene_tracker.on_description(
                            description, timestamp, list(self._scene_objects)
                        )
                        self._scene_objects.clear()
                        if completed:
                            event = self.event_generator.generate_scene_detection_event(
                                completed
                            )
                            scene_objs = completed.get('objects', [])
                            self.logger.info(f"\n{'='*70}\n>>> VISION DETECTED: Scene | label={description} | objects={scene_objs}\n{'='*70}")
                            self.event_sink.write_event(event)
                            self.logger.info(f"场景描述: {description}")

                # 显示进度
                if frame_count % 30 == 0:
                    elapsed = time.time() - proc_start
                    fps_actual = frame_count / elapsed
                    remaining = (
                        (total_frames - frame_count) / fps_actual
                        if fps_actual > 0
                        else 0
                    )
                    self.logger.info(
                        f"处理进度: {frame_count}/{total_frames} "
                        f"({frame_count / total_frames * 100:.1f}%), "
                        f"当前 FPS: {fps_actual:.1f}, "
                        f"活跃追踪: {self.track_manager.get_active_track_count()}, "
                        f"预计剩余时间: {remaining:.0f}s"
                    )

        finally:
            cap.release()
            last_video_ts = video_start_time + timedelta(
                seconds=(frame_count - 1) / fps if fps > 0 else 0
            )

            # 输出剩余的追踪事件
            if self.config.ENABLE_PERSON_TRACK_EVENT:
                for track_info in self.track_manager.active_tracks.values():
                    if track_info.age >= self.track_manager.min_track_age:
                        event = self.event_generator.generate_person_track_event(
                            track_info=track_info, timestamp=last_video_ts
                        )
                        self.event_sink.write_event(event)

            # 输出当前未关闭的场景事件
            if self.scene_tracker is not None:
                completed = self.scene_tracker.flush(
                    timestamp=last_video_ts, objects=list(self._scene_objects)
                )
                if completed:
                    event = self.event_generator.generate_scene_detection_event(
                        completed
                    )
                    self.event_sink.write_event(event)

            elapsed = time.time() - proc_start
            self.logger.info(
                f"视频处理完成! "
                f"总耗时: {elapsed:.1f}s, "
                f"平均 FPS: {frame_count / elapsed:.1f}, "
                f"生成事件: {self.event_sink.event_count}"
            )

    def _should_emit_face_event(self, track_id: int, embedding_dict: Dict) -> bool:
        """
        判断是否应该为该 track_id 输出新的 face_detection 事件

        Args:
            track_id: 追踪 ID
            embedding_dict: 人脸 embedding 字典（含 vector 字段）

        Returns:
            True 表示应该输出事件（新人脸或特征变化显著）
        """
        if track_id not in self.last_emitted_embeddings:
            return True

        current_vec = np.array(embedding_dict['vector'])
        last_vec = self.last_emitted_embeddings[track_id]
        similarity = float(np.dot(current_vec, last_vec))
        return similarity < self.config.FACE_CHANGE_THRESHOLD

    def _detect_and_track(
        self, frame: np.ndarray, frame_width: int, frame_height: int
    ) -> List[Dict]:
        """
        人体检测和追踪

        Args:
            frame: 输入帧
            frame_width: 帧宽度
            frame_height: 帧高度

        Returns:
            追踪结果列表
        """
        results = self.yolo_model.track(
            frame,
            persist=True,
            verbose=False,
            tracker=self.config.TRACKER_CONFIG,
            conf=self.config.YOLO_CONF_THRESHOLD,
            iou=self.config.YOLO_IOU_THRESHOLD,
        )

        tracks = []
        if results[0].boxes is not None and results[0].boxes.id is not None:
            boxes = results[0].boxes.xyxy.cpu().numpy()
            track_ids = results[0].boxes.id.int().cpu().tolist()
            confidences = results[0].boxes.conf.cpu().tolist()
            classes = results[0].boxes.cls.int().cpu().tolist()

            for box, track_id, conf, cls_id in zip(
                boxes, track_ids, confidences, classes
            ):
                x1, y1, x2, y2 = box
                x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)

                # 收集非人物体，供场景事件 payload 使用
                if cls_id != 0 and cls_id in self.yolo_model.names:
                    self._scene_objects.add(self.yolo_model.names[cls_id])

                tracks.append(
                    {
                        "track_id": int(track_id),
                        "box": (x1, y1, x2, y2),
                        "confidence": float(conf),
                        "face_info": None,
                    }
                )

        return tracks

    def _detect_and_embed_faces(
        self,
        frame: np.ndarray,
        tracks: List[Dict],
        frame_width: int,
        frame_height: int,
        frame_count: int = 0,
    ) -> List[Dict]:
        """
        在完整帧上做人脸检测，然后与追踪框关联。
        已有缓存且未过期的 track_id 直接复用上一次结果，不重新调用 insightface。
        """
        interval = self.config.FACE_REEMBED_INTERVAL

        # 判断哪些 track_id 需要重新检测
        needs_redetect = any(
            track["track_id"] not in self.face_cache
            or frame_count - self.face_cache[track["track_id"]]["last_frame"]
            >= interval
            for track in tracks
        )

        if needs_redetect:
            all_faces = self.face_analyzer.analyze_frame(frame)
            matched = self.face_analyzer.match_faces_to_tracks(all_faces, tracks)
        else:
            matched = {}

        # 清理已消失的 track_id 的缓存和 embedding 记录
        active_ids = {t["track_id"] for t in tracks}
        for tid in list(self.face_cache.keys()):
            if tid not in active_ids:
                del self.face_cache[tid]
        for tid in list(self.last_emitted_embeddings.keys()):
            if tid not in active_ids:
                del self.last_emitted_embeddings[tid]

        for track in tracks:
            track_id = track["track_id"]
            cache = self.face_cache.get(track_id)

            # 判断是否使用新检测结果
            if track_id in matched:
                face = matched[track_id]
                if face["quality"]["overall_quality"] >= self.config.MIN_FACE_QUALITY:
                    face_info = {
                        "id": f"face_{int(time.time() * 1000)}_{track_id}",
                        "bbox": face["bbox"],
                        "bbox_norm": face["bbox_norm"],
                        "confidence": face["confidence"],
                        "quality": face["quality"],
                        "yaw_pitch_roll": face["yaw_pitch_roll"],
                        "embedding": face["embedding"],
                        "event_id": None,
                    }
                    self.face_cache[track_id] = {
                        "face_info": face_info,
                        "last_frame": frame_count,
                    }
                    track["face_info"] = face_info
                    continue

            # 使用缓存（即使缓存也会持续向 TrackInfo 汇报，但不会产生新 face_detection 事件）
            if cache:
                cached_info = dict(cache["face_info"])
                cached_info["from_cache"] = True
                track["face_info"] = cached_info

        return tracks
