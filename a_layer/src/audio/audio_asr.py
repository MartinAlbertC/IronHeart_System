"""ASR 模块 - 基于 FunASR SenseVoice"""
import re
import numpy as np
from typing import Dict

from src.core import config

# SenseVoice 特殊标签匹配：<|zh|>, <|NEUTRAL|>, <|BGM|>, <|Speech|>, <|withitn|> 等
_SENSEVOICE_TAG_RE = re.compile(r'<\|[^|]*\|>')


class SpeechRecognizer:
    """
    FunASR SenseVoice 封装。

    输入：float32 PCM numpy 数组（16kHz，单声道）
    输出：{'text': str, 'language': str, 'speech_event': str}
    """

    def __init__(
        self,
        model: str = config.ASR_MODEL,
        device: str = "cpu",
    ):
        from funasr import AutoModel
        # 不挂 vad_model/punc_model：VAD 由 Silero 负责
        # SenseVoice 支持多语言，中文识别效果优于 paraformer-zh
        self._model = AutoModel(
            model=model,
            device=device,
            use_itn=True,
            disable_update=True,
        )

    def transcribe(self, audio: np.ndarray, sample_rate: int = config.AUDIO_SAMPLE_RATE) -> Dict:
        """
        对一段语音 PCM 进行识别。

        Args:
            audio: float32 numpy 数组，值域 [-1, 1]，单声道
            sample_rate: 采样率（默认 16000）

        Returns:
            {'text': str, 'language': str, 'speech_event': str}
        """
        result = self._model.generate(
            input=audio,
            batch_size_s=60,
        )

        raw_text = ""
        if result and len(result) > 0:
            raw_text = result[0].get("text", "").strip()

        # 提取 SenseVoice 标签中的语音事件类型（Speech / BGM 等）
        speech_event = "unknown"
        event_match = re.search(r'<\|(Speech|BGM|Music|Noise|Laughter|Applause)\|>', raw_text)
        if event_match:
            speech_event = event_match.group(1)

        # 剥离所有 <|...|> 标签，保留纯文本
        clean_text = _SENSEVOICE_TAG_RE.sub('', raw_text).strip()

        return {
            "text": clean_text,
            "language": "zh",
            "speech_event": speech_event,
        }
