import json

import numpy as np

from typing import Dict, List, Optional, Tuple

from datetime import datetime, timezone





class IdentityTracker:

    def __init__(self, db_path: str, threshold: float = 0.75):

        self.db_path = db_path

        self.face_threshold = threshold

        self.voice_threshold = 0.70

        self.persons: Dict[str, Dict] = {}

        self.next_alias_id = 0



        # 活跃窗口（秒）：窗口内再次出现的人物降低匹配门槛

        self.active_window_sec = 30.0

        self.active_threshold_boost = 0.05



        # 每个人最多保留的 embedding 样本数（滑动窗口）

        self.max_samples = 10



    def _cosine_similarity(self, a: np.ndarray, b: np.ndarray) -> float:

        return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))



    def _to_unix(self, timestamp) -> Optional[float]:

        """将 ISO 8601 字符串或 float 统一转为 Unix 时间戳（秒）"""

        if timestamp is None:

            return None

        if isinstance(timestamp, (int, float)):

            return float(timestamp)

        if isinstance(timestamp, str):

            ts = timestamp.rstrip('Z')

            try:

                dt = datetime.fromisoformat(ts)

            except ValueError:

                return None

            if dt.tzinfo is None:

                dt = dt.replace(tzinfo=timezone.utc)

            return dt.timestamp()

        return None



    def match_or_create(self, embedding: List[float], modality: str, timestamp=None) -> str:

        embedding_array = np.array(embedding, dtype=np.float32)

        timestamp = self._to_unix(timestamp)  # 统一转为 float

        base_threshold = self.face_threshold if modality == 'face' else self.voice_threshold



        best_match: Optional[Tuple[str, float]] = None  # (alias_id, effective_threshold)

        best_score = 0.0



        for alias_id, person in self.persons.items():

            mean_key = f'{modality}_embedding_mean'

            if person.get(mean_key) is None:

                continue



            score = self._cosine_similarity(embedding_array, person[mean_key])



            # 时序加成：该人物最近活跃则降低匹配阈值

            effective_threshold = base_threshold

            if timestamp is not None and person.get('last_seen') is not None:

                time_gap = timestamp - person['last_seen']

                if 0 <= time_gap <= self.active_window_sec:

                    effective_threshold -= self.active_threshold_boost



            if score > best_score:

                best_score = score

                best_match = (alias_id, effective_threshold)



        if best_match and best_score > best_match[1]:

            alias_id = best_match[0]

            self._update_person(alias_id, embedding_array, modality, timestamp)

            return alias_id

        else:

            return self._create_person(embedding_array, modality, timestamp)



    def _update_person(self, alias_id: str, embedding: np.ndarray, modality: str, timestamp: float = None):

        person = self.persons[alias_id]

        emb_key = f'{modality}_embeddings'

        mean_key = f'{modality}_embedding_mean'



        # 滑动窗口：保留最近 max_samples 个样本

        person[emb_key].append(embedding)

        if len(person[emb_key]) > self.max_samples:

            person[emb_key].pop(0)



        # 由当前窗口内所有样本重新计算均值（比增量均值更稳健）

        person[mean_key] = np.mean(person[emb_key], axis=0)



        if timestamp is not None:

            person['last_seen'] = timestamp



    def _create_person(self, embedding: np.ndarray, modality: str, timestamp: float = None) -> str:

        alias_id = f"alias_{chr(65 + self.next_alias_id)}"

        self.next_alias_id += 1

        self.persons[alias_id] = {

            'face_embeddings': [embedding] if modality == 'face' else [],

            'face_embedding_mean': embedding if modality == 'face' else None,

            'voice_embeddings': [embedding] if modality == 'voice' else [],

            'voice_embedding_mean': embedding if modality == 'voice' else None,

            'last_seen': timestamp,

        }

        return alias_id
