"""VAD（人声检测）模块 - 基于 Silero-VAD"""
import numpy as np
from typing import List, Tuple, Optional
from dataclasses import dataclass

from src.core import config


@dataclass
class SpeechSegment:
    """一段连续语音"""
    start_sample: int     # 在整段音频中的起始采样点
    end_sample: int       # 结束采样点
    audio: np.ndarray     # float32 PCM，值域 [-1, 1]
    start_sec: float      # 段落开始时间（秒，相对于音频起点）
    end_sec: float        # 段落结束时间（秒）


class VoiceActivityDetector:
    """
    Silero-VAD 封装。

    用法（流式模拟）：
        vad = VoiceActivityDetector()
        segments = vad.process(audio_float32)   # 一次性处理整段 PCM
    """

    def __init__(
        self,
        sample_rate: int = config.AUDIO_SAMPLE_RATE,
        chunk_samples: int = config.AUDIO_CHUNK_SAMPLES,
        onset: float = config.VAD_ONSET_THRESHOLD,
        offset: float = config.VAD_OFFSET_THRESHOLD,
        min_speech_ms: int = config.VAD_MIN_SPEECH_MS,
        min_silence_ms: int = config.VAD_MIN_SILENCE_MS,
        max_speech_ms: int = config.VAD_MAX_SPEECH_MS,
    ):
        self.sample_rate = sample_rate
        self.chunk_samples = chunk_samples
        self.onset = onset
        self.offset = offset
        self.min_speech_samples = int(sample_rate * min_speech_ms / 1000)
        self.min_silence_samples = int(sample_rate * min_silence_ms / 1000)
        self.max_speech_samples = int(sample_rate * max_speech_ms / 1000)

        self._model, self._utils = self._load_model()

    def _load_model(self):
        import torch
        model, utils = torch.hub.load(
            repo_or_dir='snakers4/silero-vad',
            model='silero_vad',
            force_reload=False,
            trust_repo=True,
        )
        model.eval()
        return model, utils

    def process(self, audio: np.ndarray) -> List[SpeechSegment]:
        """
        对一段 float32 PCM 音频做 VAD，返回所有语音段。

        Args:
            audio: float32 numpy 数组，值域 [-1, 1]，单声道，16kHz

        Returns:
            语音段列表
        """
        import torch

        self._model.reset_states()

        n = len(audio)
        speech_probs = []

        # 逐 chunk 推理
        for start in range(0, n, self.chunk_samples):
            chunk = audio[start: start + self.chunk_samples]
            if len(chunk) < self.chunk_samples:
                # 末尾不足一个 chunk，补零
                chunk = np.pad(chunk, (0, self.chunk_samples - len(chunk)))
            tensor = torch.from_numpy(chunk).unsqueeze(0)  # (1, chunk_samples)
            with torch.no_grad():
                prob = self._model(tensor, self.sample_rate).item()
            speech_probs.append(prob)

        # 将逐 chunk 概率转换为语音段（onset/offset 滞后逻辑）
        segments = self._probs_to_segments(speech_probs, audio)
        return segments

    def _probs_to_segments(
        self, probs: List[float], audio: np.ndarray
    ) -> List[SpeechSegment]:
        """将逐 chunk 语音概率序列转换为 SpeechSegment 列表"""
        segments: List[SpeechSegment] = []
        in_speech = False
        speech_start = 0
        silence_count = 0  # 连续静音 chunk 数

        silence_chunks = max(1, self.min_silence_samples // self.chunk_samples)
        min_speech_chunks = max(1, self.min_speech_samples // self.chunk_samples)

        speech_chunk_count = 0

        for i, prob in enumerate(probs):
            sample_pos = i * self.chunk_samples

            if not in_speech:
                if prob >= self.onset:
                    in_speech = True
                    speech_start = sample_pos
                    silence_count = 0
                    speech_chunk_count = 1
            else:
                if prob >= self.offset:
                    silence_count = 0
                    speech_chunk_count += 1
                else:
                    silence_count += 1
                    if silence_count >= silence_chunks:
                        # 语音段结束
                        speech_end = sample_pos  # 静音开始位置作为结束点
                        in_speech = False

                        if speech_chunk_count >= min_speech_chunks:
                            seg_audio = audio[speech_start:speech_end]
                            segments.append(SpeechSegment(
                                start_sample=speech_start,
                                end_sample=speech_end,
                                audio=seg_audio,
                                start_sec=speech_start / self.sample_rate,
                                end_sec=speech_end / self.sample_rate,
                            ))

                        silence_count = 0
                        speech_chunk_count = 0

                # 强制切割过长语音段
                if in_speech:
                    speech_len = sample_pos - speech_start + self.chunk_samples
                    if speech_len >= self.max_speech_samples:
                        speech_end = speech_start + self.max_speech_samples
                        seg_audio = audio[speech_start:speech_end]
                        segments.append(SpeechSegment(
                            start_sample=speech_start,
                            end_sample=speech_end,
                            audio=seg_audio,
                            start_sec=speech_start / self.sample_rate,
                            end_sec=speech_end / self.sample_rate,
                        ))
                        speech_start = speech_end
                        speech_chunk_count = 0

        # 处理末尾未关闭的语音段
        if in_speech and speech_chunk_count >= min_speech_chunks:
            speech_end = len(audio)
            seg_audio = audio[speech_start:speech_end]
            segments.append(SpeechSegment(
                start_sample=speech_start,
                end_sample=speech_end,
                audio=seg_audio,
                start_sec=speech_start / self.sample_rate,
                end_sec=speech_end / self.sample_rate,
            ))

        return segments
