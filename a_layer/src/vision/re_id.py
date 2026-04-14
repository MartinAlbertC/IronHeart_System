"""
Re-ID 模块：track_id → alias 稳定映射

职责：
- 维护 track_id → alias 映射表
- track_id 丢失后，通过 ArcFace embedding 匹配恢复 alias
- 与注册库对接，已知人直接返回 person_id 作为 alias
"""
import time
import numpy as np
from typing import Dict, Optional, Tuple
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from shared.registry import PersonRegistry


class ReIDModule:
    """
    track_id → alias 稳定映射器。

    三层策略：
    1. track_id 仍存活 → 直接返回已有 alias
    2. track_id 消失后重新出现 → embedding 匹配 recently_lost，恢复旧 alias
    3. 确认新人 → 与注册库匹配（已知人）或分配新临时 alias
    """

    def __init__(self, registry: PersonRegistry,
                 lost_ttl_sec: float = 300.0,
                 face_threshold: float = 0.5):
        self.registry = registry
        self.lost_ttl_sec = lost_ttl_sec      # lost track 保留时长（秒）
        self.face_threshold = face_threshold

        # track_id → alias
        self._track_to_alias: Dict[int, str] = {}
        # alias → embedding mean（用于 Re-ID 匹配）
        self._alias_embeddings: Dict[str, np.ndarray] = {}
        # 最近消失的 track：alias → {embedding, lost_at}
        self._lost_tracks: Dict[str, Dict] = {}

        self._next_alias_idx = 0

    # ─────────────────────────────────────────────────────────────
    # 主接口
    # ─────────────────────────────────────────────────────────────

    def resolve(self, track_id: int, embedding: np.ndarray) -> str:
        """
        给定 track_id 和当前帧的 face embedding，返回稳定的 alias。
        """
        # 1. 已有映射，直接更新 embedding 均值并返回
        if track_id in self._track_to_alias:
            alias = self._track_to_alias[track_id]
            self._update_embedding(alias, embedding)
            return alias

        # 2. 新 track_id：先尝试从 lost_tracks 恢复
        alias = self._match_lost(embedding)

        # 3. 没有匹配的 lost track：查注册库
        if alias is None:
            result = self.registry.match_face(embedding, threshold=self.face_threshold)
            if result:
                alias = result[0]  # person_id 作为 alias
                # 高置信度匹配，自动更新注册库
                if result[1] >= 0.7:
                    self.registry.add_face_embedding(alias, embedding, quality=float(result[1]))
            else:
                alias = self._new_alias()

        self._track_to_alias[track_id] = alias
        self._update_embedding(alias, embedding)
        # 新陌生人：把首帧 embedding 写入注册库
        if alias.startswith("stranger_"):
            self.registry.add_face_embedding(alias, embedding)
        # 从 lost 中移除（已恢复）
        self._lost_tracks.pop(alias, None)
        return alias

    def mark_lost(self, track_id: int):
        """track_id 消失时调用，将其移入 lost_tracks 缓冲"""
        alias = self._track_to_alias.pop(track_id, None)
        if alias and alias in self._alias_embeddings:
            self._lost_tracks[alias] = {
                "embedding": self._alias_embeddings[alias].copy(),
                "lost_at": time.time(),
            }
        self._evict_expired()

    # ─────────────────────────────────────────────────────────────
    # 内部
    # ─────────────────────────────────────────────────────────────

    def _match_lost(self, embedding: np.ndarray) -> Optional[str]:
        self._evict_expired()
        best_alias, best_score = None, 0.0
        for alias, info in self._lost_tracks.items():
            score = _cosine(embedding, info["embedding"])
            if score > best_score:
                best_score = score
                best_alias = alias
        if best_alias and best_score >= self.face_threshold:
            return best_alias
        return None

    def _update_embedding(self, alias: str, embedding: np.ndarray):
        if alias not in self._alias_embeddings:
            self._alias_embeddings[alias] = embedding.copy()
        else:
            # 指数移动平均，平滑更新
            self._alias_embeddings[alias] = (
                0.7 * self._alias_embeddings[alias] + 0.3 * embedding
            )
            norm = np.linalg.norm(self._alias_embeddings[alias])
            if norm > 1e-8:
                self._alias_embeddings[alias] /= norm

    def _new_alias(self) -> str:
        import uuid
        alias = f"stranger_{uuid.uuid4().hex[:8]}"
        self._next_alias_idx += 1
        # 自动写入注册库，display_name 为 "陌生人_xxxx"
        self.registry.register_person(alias, f"陌生人_{alias[-8:]}", is_wearer=False)
        return alias
        return alias

    def _evict_expired(self):
        now = time.time()
        expired = [a for a, info in self._lost_tracks.items()
                   if now - info["lost_at"] > self.lost_ttl_sec]
        for a in expired:
            del self._lost_tracks[a]


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))
