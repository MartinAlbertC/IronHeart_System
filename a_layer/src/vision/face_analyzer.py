"""人脸分析模块 - 基于 insightface，同时完成检测和编码"""
import cv2
import numpy as np
from typing import List, Dict, Optional, Tuple


class FaceAnalyzer:
    """
    人脸分析器 - 使用 insightface 同时完成：
    - 人脸检测 (bbox + 置信度)
    - 人脸关键点
    - 人脸 embedding
    """

    def __init__(self, model_name: str = "arcface_r50", device: str = "cpu"):
        self.model_name = model_name
        self.device = device
        self.embedding_dim = 512

        try:
            import insightface
            providers = ['CUDAExecutionProvider'] if device == "cuda" else ['CPUExecutionProvider']
            # 只启用检测和识别，跳过关键点/性别年龄模型
            self.model = insightface.app.FaceAnalysis(
                providers=providers,
                allowed_modules=['detection', 'recognition']
            )
            ctx_id = 0 if device == "cuda" else -1
            self.model.prepare(ctx_id=ctx_id, det_size=(640, 640))
        except ImportError:
            raise ImportError("insightface 未安装，请运行: pip install insightface onnxruntime")

    def analyze_frame(self, frame: np.ndarray) -> List[Dict]:
        """
        在完整帧上检测所有人脸并计算 embedding。

        Args:
            frame: 完整输入帧 (BGR)

        Returns:
            人脸列表，每个包含：
            {
                'bbox': (x1, y1, x2, y2),       # 像素坐标
                'bbox_norm': [x, y, w, h],        # 归一化 xywh
                'confidence': float,
                'yaw_pitch_roll': [0, 0, 0],
                'embedding': {'model', 'vector', 'vector_dim', 'norm'},
                'quality': {'blur_score', 'illumination_score', 'pose_score', 'overall_quality'}
            }
        """
        if frame is None or frame.size == 0:
            return []

        h, w = frame.shape[:2]

        try:
            faces = self.model.get(frame)
        except Exception as e:
            return []

        results = []
        for face in faces:
            x1, y1, x2, y2 = [int(v) for v in face.bbox]
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(w, x2), min(h, y2)

            if x2 <= x1 or y2 <= y1:
                continue

            face_crop = frame[y1:y2, x1:x2]
            quality = FaceQualityAssessor.assess(face_crop)

            if face.embedding is not None:
                vec = face.embedding / (np.linalg.norm(face.embedding) + 1e-8)
                embedding = {
                    'model': self.model_name,
                    'vector': vec.tolist(),
                    'vector_dim': len(vec),
                    'norm': 'l2'
                }
            else:
                embedding = {
                    'model': self.model_name,
                    'vector': np.zeros(self.embedding_dim).tolist(),
                    'vector_dim': self.embedding_dim,
                    'norm': 'l2'
                }

            results.append({
                'bbox': (x1, y1, x2, y2),
                'bbox_norm': [x1 / w, y1 / h, (x2 - x1) / w, (y2 - y1) / h],
                'confidence': float(face.det_score) if face.det_score is not None else 0.9,
                'yaw_pitch_roll': [0.0, 0.0, 0.0],
                'embedding': embedding,
                'quality': quality
            })

        return results

    def match_faces_to_tracks(self, faces: List[Dict],
                              tracks: List[Dict]) -> Dict[int, Dict]:
        """
        将人脸检测结果与追踪框关联（IoU 匹配）。

        Args:
            faces: analyze_frame 返回的人脸列表
            tracks: {'track_id', 'box': (x1,y1,x2,y2)} 列表

        Returns:
            {track_id: face_info} 字典
        """
        matched = {}

        for track in tracks:
            track_id = track['track_id']
            tx1, ty1, tx2, ty2 = track['box']
            best_face = None
            best_iou = 0.0

            for face in faces:
                fx1, fy1, fx2, fy2 = face['bbox']
                # 计算人脸中心点是否在追踪框内（宽松匹配）
                cx = (fx1 + fx2) / 2
                cy = (fy1 + fy2) / 2
                if tx1 <= cx <= tx2 and ty1 <= cy <= ty2:
                    iou = _calc_iou((tx1, ty1, tx2, ty2), (fx1, fy1, fx2, fy2))
                    if iou > best_iou or best_face is None:
                        best_iou = iou
                        best_face = face

            if best_face is not None:
                matched[track_id] = best_face

        return matched

    @staticmethod
    def cosine_distance(vec1: List[float], vec2: List[float]) -> float:
        v1, v2 = np.array(vec1), np.array(vec2)
        return 1.0 - float(np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2) + 1e-8))


def _calc_iou(box1: Tuple, box2: Tuple) -> float:
    """计算两个 bbox 的 IoU"""
    x1 = max(box1[0], box2[0])
    y1 = max(box1[1], box2[1])
    x2 = min(box1[2], box2[2])
    y2 = min(box1[3], box2[3])

    inter = max(0, x2 - x1) * max(0, y2 - y1)
    if inter == 0:
        return 0.0

    a1 = (box1[2] - box1[0]) * (box1[3] - box1[1])
    a2 = (box2[2] - box2[0]) * (box2[3] - box2[1])
    return inter / (a1 + a2 - inter + 1e-8)


class FaceQualityAssessor:
    """人脸质量评估"""

    @staticmethod
    def assess(face_crop: np.ndarray) -> Dict:
        if face_crop is None or face_crop.size == 0:
            return {'blur_score': 0.0, 'illumination_score': 0.0,
                    'pose_score': 1.0, 'overall_quality': 0.0}

        blur = FaceQualityAssessor._calc_blur(face_crop)
        illumination = FaceQualityAssessor._calc_illumination(face_crop)
        overall = blur * 0.5 + illumination * 0.5

        return {
            'blur_score': float(blur),
            'illumination_score': float(illumination),
            'pose_score': 1.0,
            'overall_quality': float(overall)
        }

    @staticmethod
    def _calc_blur(face_crop: np.ndarray) -> float:
        gray = cv2.cvtColor(face_crop, cv2.COLOR_BGR2GRAY)
        return float(min(cv2.Laplacian(gray, cv2.CV_64F).var() / 5000, 1.0))

    @staticmethod
    def _calc_illumination(face_crop: np.ndarray) -> float:
        gray = cv2.cvtColor(face_crop, cv2.COLOR_BGR2GRAY)
        mean = np.mean(gray) / 255.0
        return float(max(1.0 - abs(mean - 0.5) * 2, 0.0))

