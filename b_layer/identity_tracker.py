import numpy as np

from typing import Dict, List, Optional, Tuple

from datetime import datetime, timezone




class IdentityTracker:

    def __init__(self, db_path: str, threshold: float = 0.75,
                 min_sample_quality: float = 0.5,
                 merge_similarity_threshold: float = 0.85):
        self.db_path = db_path
        self.face_threshold = threshold
        self.min_sample_quality = min_sample_quality
        self.merge_similarity_threshold = merge_similarity_threshold

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



    def match_or_create(self, embedding: List[float], modality: str,
                        quality: float = None, timestamp=None) -> str:
        """
        匹配或创建实体。

        匹配策略（按优先级）：
        1. 同模态匹配（face→face_mean, voice→voice_mean）
        2. 高相似度合并（> merge_similarity_threshold）
        3. 创建新alias
        """
        embedding_array = np.array(embedding, dtype=np.float32)
        timestamp_float = self._to_unix(timestamp)

        base_threshold = self.face_threshold if modality == 'face' else self.voice_threshold

        # ── Step 1: 同模态匹配 ──
        best_match: Optional[Tuple[str, float]] = None
        best_score = 0.0

        for alias_id, person in self.persons.items():
            mean_key = f'{modality}_embedding_mean'
            if person.get(mean_key) is None:
                continue

            score = self._cosine_similarity(embedding_array, person[mean_key])

            # 时序加成：该人物最近活跃则降低匹配阈值
            effective_threshold = base_threshold
            if timestamp_float is not None and person.get('last_seen') is not None:
                time_gap = timestamp_float - person['last_seen']
                if 0 <= time_gap <= self.active_window_sec:
                    effective_threshold -= self.active_threshold_boost

            if score > best_score:
                best_score = score
                best_match = (alias_id, effective_threshold)

        if best_match and best_score > best_match[1]:
            self._update_person(best_match[0], embedding_array, modality, quality, timestamp_float)
            return best_match[0]

        # ── Step 2: 高相似度合并 ──
        for alias_id, person in self.persons.items():
            mean_key = f'{modality}_embedding_mean'
            mean = person.get(mean_key)
            if mean is not None:
                score = self._cosine_similarity(embedding_array, mean)
                if score > self.merge_similarity_threshold:
                    self._merge_into_alias(alias_id, embedding_array, modality, quality, timestamp_float)
                    return alias_id

        # ── Step 3: 创建新人 ──
        return self._create_person(embedding_array, modality, quality, timestamp_float)



    def _update_person(self, alias_id: str, embedding: np.ndarray, modality: str,
                       quality: float = None, timestamp: float = None):
        self._update_person_only(alias_id, embedding, modality, quality, timestamp)

    def _update_person_only(self, alias_id: str, embedding: np.ndarray, modality: str,
                             quality: float = None, timestamp: float = None):
        """
        更新已有 alias 的 embedding（不创建新alias）。
        用于窗口级解析时，已确认alias归属的情况。
        """
        person = self.persons[alias_id]
        emb_key = f'{modality}_embeddings'
        mean_key = f'{modality}_embedding_mean'

        person[emb_key].append((embedding, quality))

        if len(person[emb_key]) > self.max_samples:
            idx = min(range(len(person[emb_key])),
                      key=lambda i: person[emb_key][i][1] if person[emb_key][i][1] is not None else 0.5)
            person[emb_key].pop(idx)

        valid = [(e, q) for e, q in person[emb_key]
                 if q is not None and q >= self.min_sample_quality]

        if valid:
            weights = np.array([q for _, q in valid])
            weights /= weights.sum()
            vectors = np.array([e for e, _ in valid])
            person[mean_key] = np.average(vectors, axis=0, weights=weights).astype(np.float32)
        else:
            vectors = np.array([e for e, _ in person[emb_key]])
            person[mean_key] = np.mean(vectors, axis=0).astype(np.float32)

        if timestamp is not None:
            person['last_seen'] = timestamp

        return person


    def _merge_into_alias(self, target_alias: str, new_embedding: np.ndarray,
                          modality: str, quality: float = None, timestamp: float = None):
        """
        将新样本合并到已有 alias（而非创建新的）。
        等价于把新样本当作该 alias 的匹配结果进行处理。
        """
        person = self.persons[target_alias]
        emb_key = f'{modality}_embeddings'
        mean_key = f'{modality}_embedding_mean'

        # 入滑动窗口
        person[emb_key].append((new_embedding, quality))
        if len(person[emb_key]) > self.max_samples:
            idx = min(range(len(person[emb_key])),
                      key=lambda i: person[emb_key][i][1] if person[emb_key][i][1] is not None else 0.5)
            person[emb_key].pop(idx)

        # 重新计算均值
        valid = [(e, q) for e, q in person[emb_key]
                 if q is not None and q >= self.min_sample_quality]

        if valid:
            weights = np.array([q for _, q in valid])
            weights /= weights.sum()
            vectors = np.array([e for e, _ in valid])
            person[mean_key] = np.average(vectors, axis=0, weights=weights).astype(np.float32)
        else:
            vectors = np.array([e for e, _ in person[emb_key]])
            person[mean_key] = np.mean(vectors, axis=0).astype(np.float32)

        if timestamp is not None:
            person['last_seen'] = timestamp



    def _create_person(self, embedding: np.ndarray, modality: str,
                       quality: float = None, timestamp: float = None) -> str:
        alias_id = f"alias_{chr(65 + self.next_alias_id)}"
        self.next_alias_id += 1

        self.persons[alias_id] = {
            'face_embeddings': [(embedding, quality)] if modality == 'face' else [],
            'face_embedding_mean': embedding if modality == 'face' else None,
            'voice_embeddings': [(embedding, quality)] if modality == 'voice' else [],
            'voice_embedding_mean': embedding if modality == 'voice' else None,
            'last_seen': timestamp,
        }
        return alias_id



    def merge_aliases(self, keep: str, absorb: str):
        """
        将 absorb alias 合并到 keep alias。
        keep 和 absorb 必须是同一个人（由调用方保证）。
        合并后 absorb 不再存在，其所有 embeddings 合并到 keep。
        """
        if keep not in self.persons or absorb not in self.persons:
            return
        if keep == absorb:
            return

        keep_person = self.persons[keep]
        abs_person = self.persons[absorb]

        # 合并 face embeddings
        for emb, q in abs_person['face_embeddings']:
            keep_person['face_embeddings'].append((emb, q))
        # 合并 voice embeddings
        for emb, q in abs_person['voice_embeddings']:
            keep_person['voice_embeddings'].append((emb, q))

        # 裁剪到 max_samples（保留高质量）
        for emb_key in ['face_embeddings', 'voice_embeddings']:
            if len(keep_person[emb_key]) > self.max_samples:
                keep_person[emb_key].sort(key=lambda x: x[1] if x[1] is not None else 0.5)
                keep_person[emb_key] = keep_person[emb_key][-self.max_samples:]

        # 重新计算均值
        for modality in ['face', 'voice']:
            emb_key = f'{modality}_embeddings'
            mean_key = f'{modality}_embedding_mean'
            valid = [(e, q) for e, q in keep_person[emb_key]
                     if q is not None and q >= self.min_sample_quality]
            if valid:
                weights = np.array([q for _, q in valid])
                weights /= weights.sum()
                vectors = np.array([e for e, _ in valid])
                keep_person[mean_key] = np.average(vectors, axis=0, weights=weights).astype(np.float32)
            else:
                vectors = np.array([e for e, _ in keep_person[emb_key]])
                keep_person[mean_key] = np.mean(vectors, axis=0).astype(np.float32)

        # 更新时间
        if abs_person.get('last_seen') is not None:
            if keep_person.get('last_seen') is None or \
               abs_person['last_seen'] > keep_person['last_seen']:
                keep_person['last_seen'] = abs_person['last_seen']

        # 删除 absorb
        del self.persons[absorb]



    def get_state_summary(self) -> Dict:
        """返回当前所有 alias 的简要状态，用于日志输出"""
        summary = {}
        for alias_id, person in self.persons.items():
            summary[alias_id] = {
                'face_samples': len(person['face_embeddings']),
                'voice_samples': len(person['voice_embeddings']),
                'has_face': person.get('face_embedding_mean') is not None,
                'has_voice': person.get('voice_embedding_mean') is not None,
                'last_seen': person.get('last_seen'),
            }
        return summary
