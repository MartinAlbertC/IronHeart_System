"""音频管道核心模块"""
import logging
import time
from datetime import datetime, timedelta
from typing import Optional

import numpy as np

from src.core import config
from src.audio.audio_vad import VoiceActivityDetector, SpeechSegment
from src.audio.audio_asr import SpeechRecognizer
from src.audio.audio_embedder import VoiceEmbedder
from src.core.event_generator import EventGenerator, EventSink
from src.core.utils import setup_logger


class AudioPipeline:
    """
    音频管道：从视频文件提取音轨 → VAD → ASR + 声纹 → SpeechSegmentEvent

    使用方式：
        pipeline = AudioPipeline()
        pipeline.process_video("data/xxx.mp4")
    """

    def __init__(
        self,
        device: str = config.DEVICE,
        output_file: str = config.EVENT_OUTPUT_FILE,
        log_file: str = config.AUDIO_LOG_FILE,
        append: bool = False,
        event_sink: Optional[EventSink] = None,
    ):
        self.device = device
        self.output_file = output_file
        self.logger = setup_logger(log_file)

        self.vad: Optional[VoiceActivityDetector] = None
        self.asr: Optional[SpeechRecognizer] = None
        self.embedder: Optional[VoiceEmbedder] = None

        self.event_generator = EventGenerator(device_id=config.DEVICE_ID)
        # 优先使用外部传入的共享 EventSink（并行模式），否则自建
        if event_sink is not None:
            self.event_sink = event_sink
            self._owns_sink = False   # 不负责关闭，由调用方统一管理
        else:
            self.event_sink = EventSink(output_file, append=append)
            self._owns_sink = True

        self._turn_index = 0

        # 注册库（声纹身份识别）
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
        from shared.registry import PersonRegistry
        self._registry = PersonRegistry()

    # ------------------------------------------------------------------
    # 模型加载
    # ------------------------------------------------------------------

    def _load_models(self):
        self.logger.info("加载 VAD 模型（Silero-VAD）...")
        self.vad = VoiceActivityDetector()
        self.logger.info("VAD 加载完成")

        self.logger.info("加载 ASR 模型（FunASR SenseVoice）...")
        self.asr = SpeechRecognizer(device="cuda")
        self.logger.info("ASR 加载完成")

        self.logger.info("加载声纹模型（WeSpeaker ResNet34）...")
        self.embedder = VoiceEmbedder()
        self.logger.info("声纹模型加载完成")

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------

    def process_video(self, video_path: str, max_segments: Optional[int] = None,
                      start_time: Optional[datetime] = None):
        """
        从视频文件提取音轨并处理，输出 SpeechSegmentEvent。

        Args:
            video_path: 视频文件路径
            max_segments: 最多处理语音段数（None=全部，用于测试）
        """
        self._load_models()

        self.logger.info(f"提取音轨：{video_path}")
        audio = self._extract_audio(video_path)
        # 时间轴基准：外部传入时与视觉管道对齐，否则用当前时刻
        audio_start_time = start_time if start_time is not None else datetime.now()
        self.logger.info(
            f"音频提取完成，时长 {len(audio)/config.AUDIO_SAMPLE_RATE:.1f}s，"
            f"采样率 {config.AUDIO_SAMPLE_RATE}Hz"
        )

        self.logger.info("开始 VAD 检测...")
        t0 = time.time()
        segments = self.vad.process(audio)
        self.logger.info(
            f"VAD 完成，检测到 {len(segments)} 段语音，耗时 {time.time()-t0:.2f}s"
        )

        if max_segments is not None:
            segments = segments[:max_segments]
            self.logger.info(f"限制处理前 {max_segments} 段")

        speech_count = 0
        for seg in segments:
            event = self._process_segment(seg, audio_start_time)
            if event is not None:
                self.event_sink.write_event(event)
                speech_count += 1
                self.logger.info(
                    f"[{speech_count}] {seg.start_sec:.1f}s-{seg.end_sec:.1f}s "
                    f"({seg.end_sec - seg.start_sec:.1f}s): {event.payload['text'][:50]}"
                )

        self.event_sink.close() if self._owns_sink else None
        self.logger.info(f"音频管道完成，共输出 {speech_count} 个 SpeechSegmentEvent")

    # ------------------------------------------------------------------
    # 窗口模式接口（供 UnifiedPipeline 调用）
    # ------------------------------------------------------------------

    def process_audio_slice(self, audio: np.ndarray, start_time: datetime) -> list:
        """
        处理一段音频切片，返回语音段列表（不含 alias，由 UnifiedPipeline 填入）。

        Args:
            audio: 16kHz float32 音频片段
            start_time: 该片段对应的绝对起始时间

        Returns:
            list of segment_info dict（含 text/voice_embedding/start_ts/end_ts 等，alias=None）
        """
        if self.vad is None:
            self._load_models()

        segments = self.vad.process(audio)
        results = []
        for seg in segments:
            asr_result = self.asr.transcribe(seg.audio)
            text = asr_result.get("text", "")
            if not text:
                continue
            voice_embedding = self.embedder.extract(seg.audio)
            volume = float(np.sqrt(np.mean(seg.audio ** 2)))
            duration_sec = seg.end_sec - seg.start_sec
            self._turn_index += 1
            results.append({
                "text": text,
                "language": asr_result.get("language", "zh"),
                "speech_event": asr_result.get("speech_event", "unknown"),
                "start_ts": start_time + timedelta(seconds=seg.start_sec),
                "end_ts": start_time + timedelta(seconds=seg.end_sec),
                "volume": round(min(1.0, volume * 10), 4),
                "speech_rate": round(len(text) / duration_sec if duration_sec > 0 else 0.0, 2),
                "voice_embedding": voice_embedding,
                "turn_index": self._turn_index,
                "alias": None,
            })
        return results

    # ------------------------------------------------------------------
    # 单段处理
    # ------------------------------------------------------------------

    def _process_segment(self, seg: SpeechSegment, audio_start_time: datetime):
        """对一段语音做 ASR + 声纹提取，返回 SpeechSegmentEvent"""
        audio = seg.audio

        # ASR
        asr_result = self.asr.transcribe(audio)
        text = asr_result["text"]
        if not text:
            return None  # 空文本跳过

        # Enhanced logging: recognized speech
        self.logger.info(f"\n{'='*70}\n>>> AUDIO DETECTED: Speech | text={text[:100]} | language={asr_result.get('language', 'zh')}\n{'='*70}")

        # 声纹 embedding
        voice_embedding = self.embedder.extract(audio)

        # 声纹身份识别：穿戴者优先，再查注册库
        emb_vec = np.array(voice_embedding['vector'], dtype=np.float32)
        if self._registry.match_wearer_voice(emb_vec):
            alias = self._registry.get_wearer_id() or 'wearer'
        else:
            result = self._registry.match_voice(emb_vec)
            if result:
                alias = result[0]
                # 高置信度匹配，自动更新注册库
                if result[1] >= 0.7:
                    self._registry.add_voice_embedding(alias, emb_vec, quality=float(result[1]))
            else:
                import uuid
                alias = f"stranger_{uuid.uuid4().hex[:8]}"
                self._registry.register_person(alias, f"陌生人_{alias[-8:]}", is_wearer=False)
                self._registry.add_voice_embedding(alias, emb_vec)

        # 音量（RMS）
        volume = float(np.sqrt(np.mean(audio ** 2)))

        # 语速（字/秒，仅中文有意义）
        duration_sec = seg.end_sec - seg.start_sec
        speech_rate = len(text) / duration_sec if duration_sec > 0 else 0.0

        self._turn_index += 1
        segment_info = {
            "text": text,
            "language": asr_result["language"],
            "speech_event": asr_result.get("speech_event", "unknown"),
            "start_ts": audio_start_time + timedelta(seconds=seg.start_sec),
            "end_ts": audio_start_time + timedelta(seconds=seg.end_sec),
            "volume": round(min(1.0, volume * 10), 4),
            "speech_rate": round(speech_rate, 2),
            "voice_embedding": voice_embedding,
            "turn_index": self._turn_index,
            "alias": alias,
        }

        return self.event_generator.generate_speech_segment_event(segment_info)

    # ------------------------------------------------------------------
    # 音轨提取
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_audio(video_path: str) -> np.ndarray:
        """
        用 ffmpeg 从视频/音频文件提取 16kHz 单声道 float32 PCM。

        Returns:
            audio_array (float32 numpy)
        """
        import subprocess
        cmd = [
            "ffmpeg", "-i", video_path,
            "-f", "f32le",
            "-ac", "1",
            "-ar", str(config.AUDIO_SAMPLE_RATE),
            "-",
            "-loglevel", "error",
        ]
        result = subprocess.run(cmd, capture_output=True)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg 提取音轨失败: {result.stderr.decode()}")
        return np.frombuffer(result.stdout, dtype=np.float32).copy()
