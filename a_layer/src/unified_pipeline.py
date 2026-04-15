"""
统一帧驱动管道（v2）

以视频帧为时钟，视觉、音频、ASD 在同一循环内协同处理：
  每 window_size 帧：
    1. 视觉处理 → {track_id: alias}
    2. 音频处理 → 语音段列表
    3. ASD 结果决定 speech alias（直接来自 Re-ID，不依赖时间对齐）
    4. 输出 face_detection / speech_segment 事件（天然对齐）
"""
import sys
import time
import numpy as np
import cv2
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core import config as _config
from src.core.event_generator import EventSink, EventGenerator
from src.vision.vision_pipeline import VisionPipeline
from src.audio.audio_pipeline import AudioPipeline


class UnifiedPipeline:

    def __init__(self, video_path: str, window_size: int = 25,
                 event_sink: Optional[EventSink] = None):
        self.video_path = video_path
        self.window_size = window_size

        self.event_sink = event_sink or EventSink(
            output_file=str(Path(__file__).parent.parent.parent / "outputs" / "a_events_backup.jsonl"),
            append=False,
        )

        self.vision = VisionPipeline(event_sink=self.event_sink)
        self.audio = AudioPipeline(event_sink=self.event_sink)
        self.audio._load_models()

        self._full_audio: Optional[np.ndarray] = None
        self._sr = 16000

    def process(self, max_frames: Optional[int] = None,
                start_time: Optional[datetime] = None):
        # 预提取完整音频
        self._full_audio = VisionPipeline._extract_audio(self.video_path)

        cap = cv2.VideoCapture(self.video_path)
        if not cap.isOpened():
            raise IOError(f"Cannot open video: {self.video_path}")

        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        video_start = start_time or datetime.now()

        frame_count = 0
        window_frames = []
        t0 = time.time()

        try:
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                frame_count += 1
                if max_frames and frame_count > max_frames:
                    break

                window_frames.append(frame)

                if len(window_frames) == self.window_size:
                    self._process_window(window_frames, frame_count - self.window_size,
                                         fps, video_start)
                    window_frames = []

            # 处理剩余帧
            if window_frames:
                self._process_window(window_frames,
                                     frame_count - len(window_frames),
                                     fps, video_start)
        finally:
            cap.release()
            elapsed = time.time() - t0
            print(f"[UnifiedPipeline] 完成 | 帧数={frame_count} | 耗时={elapsed:.1f}s")

    def _get_audio_slice(self, frame_start: int, frame_end: int, fps: float) -> np.ndarray:
        if self._full_audio is None or len(self._full_audio) == 0:
            return np.zeros(0, dtype=np.float32)
        t_start = frame_start / fps
        t_end = frame_end / fps
        return self._full_audio[int(t_start * self._sr): int(t_end * self._sr)]

    def _process_window(self, frames: list, frame_start: int,
                        fps: float, video_start: datetime):
        frame_end = frame_start + len(frames)
        window_start_time = video_start + timedelta(seconds=frame_start / fps)
        audio_slice = self._get_audio_slice(frame_start, frame_end, fps)

        # 1. 视觉处理（含 ASD 推理）
        vision_result = self.vision.process_window(frames, frame_start, fps, audio_slice,
                                                    video_start=video_start)
        track_alias = vision_result['track_alias']
        speaker_track_id = vision_result['speaker_track_id']

        # 2. 输出 face 事件（已在 process_window 内生成，直接写入 sink）
        for event in vision_result['face_events']:
            self.event_sink.write_event(event)

        # 3. 音频处理（VAD + ASR + 声纹）
        if len(audio_slice) < 1600:  # < 0.1s，跳过
            return
        segments = self.audio.process_audio_slice(audio_slice, window_start_time)

        # 4. ASD 结果决定 speech alias
        for seg in segments:
            if speaker_track_id is not None and speaker_track_id in track_alias:
                seg['alias'] = track_alias[speaker_track_id]
            elif track_alias:
                # ASD 无结果但有人脸：取第一个 alias（独白场景兜底）
                seg['alias'] = next(iter(track_alias.values()))
            else:
                # 无人脸：fallback 到声纹匹配
                seg['alias'] = self._voice_fallback(seg.get('voice_embedding'))

            event = self.audio.event_generator.generate_speech_segment_event(seg)
            self.event_sink.write_event(event)

    def _voice_fallback(self, voice_embedding) -> str:
        if voice_embedding is None:
            return 'unknown'
        try:
            from shared.registry import PersonRegistry
            if not hasattr(self, '_registry'):
                self._registry = PersonRegistry()
            emb_vec = np.array(voice_embedding['vector'], dtype=np.float32)
            result = self._registry.match_voice(emb_vec)
            if result:
                return result[0]
        except Exception:
            pass
        return 'unknown'
