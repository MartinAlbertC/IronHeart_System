"""
ASD（Active Speaker Detection）封装模块
基于 Light-ASD，判断视频中每个人脸 track 是否在说话

输入：
  - 视频帧序列中每个 track 的嘴部 ROI（灰度，112x112）
  - 对应时间段的音频（16kHz float32）
输出：
  - {track_id: speaking_probability}
"""
import sys
import numpy as np
from pathlib import Path
from typing import Dict, List, Tuple

# Light-ASD 路径
LIGHT_ASD_DIR = Path(__file__).parent.parent.parent.parent / "models" / "Light-ASD"
WEIGHT_PATH = LIGHT_ASD_DIR / "weight" / "pretrain_AVA_CVPR.model"


class ASDModule:
    """Light-ASD 推理封装，滑动窗口模式"""

    def __init__(self, device: str = "cuda", weight_path: str = str(WEIGHT_PATH)):
        import torch
        self.device = torch.device(device if torch.cuda.is_available() else "cpu")
        self._model = self._load_model(weight_path)

    def _load_model(self, weight_path: str):
        import torch
        sys.path.insert(0, str(LIGHT_ASD_DIR))
        from model.Model import ASD_Model
        from loss import lossAV

        model = ASD_Model().to(self.device)
        weights = torch.load(weight_path, map_location=self.device)
        # 权重可能包含在 'model' key 下
        state = weights.get('model', weights)
        model.load_state_dict(state, strict=False)
        model.eval()

        self._loss_av = lossAV().to(self.device)
        return model

    def predict(self, face_frames: Dict[int, np.ndarray],
                audio: np.ndarray, fps: float = 25.0) -> Dict[int, float]:
        """
        Args:
            face_frames: {track_id: (T, 112, 112) uint8 灰度帧序列}
            audio: float32 PCM，16kHz，与 face_frames 时间对齐
            fps: 视频帧率

        Returns:
            {track_id: speaking_probability (0~1)}
        """
        import torch

        if not face_frames:
            return {}

        audio_feat = self._extract_audio_feat(audio, fps)  # (T*4, 13)
        results = {}

        with torch.no_grad():
            for track_id, frames in face_frames.items():
                T = len(frames)
                if T == 0:
                    results[track_id] = 0.0
                    continue

                # 视觉特征：(1, T, 112, 112)
                vis = torch.FloatTensor(frames).unsqueeze(0).to(self.device)

                # 音频特征对齐到 T 帧
                max_audio = T * 4
                af = audio_feat[:max_audio]
                if af.shape[0] < max_audio:
                    af = np.pad(af, ((0, max_audio - af.shape[0]), (0, 0)), 'wrap')
                aud = torch.FloatTensor(af).unsqueeze(0).to(self.device)  # (1, T*4, 13)

                audio_emb = self._model.forward_audio_frontend(aud)
                visual_emb = self._model.forward_visual_frontend(vis)
                out_av = self._model.forward_audio_visual_backend(audio_emb, visual_emb)

                # 取说话概率（softmax 第1类）
                import torch.nn.functional as F
                prob = F.softmax(self._loss_av.FC(out_av), dim=1)[:, 1]
                results[track_id] = float(prob.mean().cpu())

        return results

    @staticmethod
    def _extract_audio_feat(audio: np.ndarray, fps: float) -> np.ndarray:
        """提取 MFCC 特征，与 Light-ASD dataLoader 保持一致"""
        import python_speech_features
        # 转为 int16
        audio_int16 = (audio * 32768).clip(-32768, 32767).astype(np.int16)
        feat = python_speech_features.mfcc(
            audio_int16, 16000, numcep=13,
            winlen=0.025 * 25 / fps,
            winstep=0.010 * 25 / fps
        )
        return feat  # (N, 13)


def extract_mouth_roi(frame: np.ndarray, bbox: Tuple,
                      landmarks=None, size: int = 112) -> np.ndarray:
    """
    从帧中裁剪嘴部区域并缩放到 size x size 灰度图。
    若无 landmark，用人脸 bbox 下半部分估算嘴部位置。
    """
    import cv2
    x1, y1, x2, y2 = [int(v) for v in bbox]
    h = y2 - y1
    w = x2 - x1

    if landmarks is not None and len(landmarks) >= 5:
        # insightface 5点：左眼、右眼、鼻尖、左嘴角、右嘴角
        mouth_pts = landmarks[3:5]
        mx = int(np.mean(mouth_pts[:, 0]))
        my = int(np.mean(mouth_pts[:, 1]))
        half = int(w * 0.3)
        mx1, my1 = max(0, mx - half), max(0, my - half)
        mx2, my2 = min(frame.shape[1], mx + half), min(frame.shape[0], my + half)
    else:
        # 估算：bbox 下 1/3 区域
        mx1, my1 = x1, y1 + h * 2 // 3
        mx2, my2 = x2, y2

    crop = frame[my1:my2, mx1:mx2]
    if crop.size == 0:
        crop = frame[y1:y2, x1:x2]

    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if len(crop.shape) == 3 else crop
    return cv2.resize(gray, (size, size))
