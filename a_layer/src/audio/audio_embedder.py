"""声纹 Embedding 模块 - 基于 WeSpeaker ResNet34 ONNX"""
import numpy as np
from typing import Dict, List

from src.core import config


class VoiceEmbedder:
    """
    WeSpeaker cnceleb-resnet34 ONNX 推理封装。

    输入：float32 PCM numpy 数组（16kHz，单声道）
    输出：256 维 L2 归一化声纹向量（dict 格式，与 face_embedding 结构对齐）
    """

    def __init__(
        self,
        model_path: str = config.VOICE_EMBEDDER_MODEL_PATH,
        model_name: str = config.VOICE_EMBEDDING_MODEL_NAME,
        sample_rate: int = config.AUDIO_SAMPLE_RATE,
    ):
        import onnxruntime as ort
        self._sess = ort.InferenceSession(
            model_path, providers=["CPUExecutionProvider"]
        )
        self._input_name = self._sess.get_inputs()[0].name
        self._model_name = model_name
        self._sample_rate = sample_rate

        # Fbank 参数（与 wespeaker 训练配置一致）
        self._num_mel_bins = 80
        self._frame_length_ms = 25
        self._frame_shift_ms = 10

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    def extract(self, audio: np.ndarray) -> Dict:
        """
        从一段语音 PCM 提取声纹 embedding。

        Args:
            audio: float32 numpy 数组，值域 [-1, 1]，单声道，16kHz

        Returns:
            {
                'model': str,
                'vector': List[float],   # 256 维 L2 归一化
                'vector_dim': 256,
                'norm': 'l2'
            }
        """
        fbank = self._compute_fbank(audio)           # (T, 80)
        fbank = fbank[np.newaxis, :, :]              # (1, T, 80)
        emb = self._sess.run(None, {self._input_name: fbank})[0][0]  # (256,)
        emb = emb / (np.linalg.norm(emb) + 1e-8)    # L2 归一化

        return {
            "model": self._model_name,
            "vector": emb.tolist(),
            "vector_dim": len(emb),
            "norm": "l2",
        }

    # ------------------------------------------------------------------
    # 内部：80 维 Log-Mel Fbank 特征提取
    # ------------------------------------------------------------------

    def _compute_fbank(self, audio: np.ndarray) -> np.ndarray:
        """
        计算 80 维 Log-Mel Fbank 特征，与 wespeaker kaldi 风格一致。

        Args:
            audio: float32 [-1, 1]，16kHz 单声道

        Returns:
            (T, 80) float32 Fbank 矩阵
        """
        sr = self._sample_rate
        frame_len = int(sr * self._frame_length_ms / 1000)   # 400
        frame_shift = int(sr * self._frame_shift_ms / 1000)  # 160
        n_mels = self._num_mel_bins

        # 预加重
        pre_emphasis = 0.97
        emphasized = np.append(audio[0], audio[1:] - pre_emphasis * audio[:-1])

        # 分帧
        n_frames = 1 + (len(emphasized) - frame_len) // frame_shift
        if n_frames <= 0:
            n_frames = 1
            emphasized = np.pad(emphasized, (0, frame_len))

        frames = np.stack([
            emphasized[i * frame_shift: i * frame_shift + frame_len]
            for i in range(n_frames)
        ])  # (T, frame_len)

        # 加汉明窗
        frames *= np.hamming(frame_len)

        # FFT → 功率谱
        fft_size = 512
        power_spec = np.abs(np.fft.rfft(frames, n=fft_size)) ** 2  # (T, fft_size//2+1)

        # Mel 滤波器组
        mel_filters = self._mel_filterbank(sr, fft_size, n_mels)   # (n_mels, fft_size//2+1)
        mel_energy = np.dot(power_spec, mel_filters.T)               # (T, n_mels)

        # 取对数，加 1e-6 防止 log(0)
        log_mel = np.log(mel_energy + 1e-6)

        return log_mel.astype(np.float32)

    @staticmethod
    def _mel_filterbank(sr: int, fft_size: int, n_mels: int) -> np.ndarray:
        """构建 Mel 三角滤波器组，返回 (n_mels, fft_size//2+1)"""
        def hz_to_mel(hz):
            return 2595.0 * np.log10(1.0 + hz / 700.0)

        def mel_to_hz(mel):
            return 700.0 * (10.0 ** (mel / 2595.0) - 1.0)

        low_freq_mel = hz_to_mel(20)
        high_freq_mel = hz_to_mel(sr / 2)
        mel_points = np.linspace(low_freq_mel, high_freq_mel, n_mels + 2)
        hz_points = mel_to_hz(mel_points)

        bin_points = np.floor((fft_size + 1) * hz_points / sr).astype(int)
        n_fft_bins = fft_size // 2 + 1
        filters = np.zeros((n_mels, n_fft_bins))

        for m in range(1, n_mels + 1):
            f_left, f_center, f_right = bin_points[m - 1], bin_points[m], bin_points[m + 1]
            for k in range(f_left, f_center):
                if f_center != f_left:
                    filters[m - 1, k] = (k - f_left) / (f_center - f_left)
            for k in range(f_center, f_right):
                if f_right != f_center:
                    filters[m - 1, k] = (f_right - k) / (f_right - f_center)

        return filters
