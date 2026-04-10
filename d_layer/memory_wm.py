# -*- coding: utf-8 -*-
"""
Working Memory Module
实现感知记忆 (PM) 和情景缓冲区 (EB)
"""

import logging
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

import numpy as np

import config
from models import PMItem, EBChunk, Opportunity
from embedding import get_embedding_engine, EmbeddingEngine
from doubao_client import get_doubao_client, DoubaoClient, ChunkAssignmentResult

logger = logging.getLogger(__name__)


class PerceptionMemory:
    """
    感知记忆 (Perception Memory, PM)

    - 容量: 7个槽位
    - 进入机制: 余弦相似度 > 0.95 则刷新时间戳，否则作为新项进入
    - 退出机制: 满7个时，踢走综合得分 S 最低的项
      S = 0.3 * Recency + 0.4 * Relevance_wm + 0.3 * Importance
    """

    def __init__(self, embedding_engine: EmbeddingEngine):
        self.items: List[PMItem] = []
        self.embedding_engine = embedding_engine
        self._changed = False
        self._next_id = 0

    @property
    def changed(self) -> bool:
        """检查PM是否在最近操作中发生了变化"""
        return self._changed

    def reset_changed_flag(self):
        """重置变化标志"""
        self._changed = False

    def is_full(self) -> bool:
        """检查PM是否已满"""
        return len(self.items) >= config.PM_CAPACITY

    def add_item(self, content: str, embedding: Optional[np.ndarray] = None) -> Tuple[bool, Optional[int]]:
        """
        添加新的感知项

        Args:
            content: 感知内容
            embedding: 可选的预计算embedding

        Returns:
            (是否成功添加, 添加/更新的项ID)
        """
        self._changed = False

        if embedding is None:
            embedding = self.embedding_engine.encode(content)

        # 检查是否与现有项相似度 > 0.95
        for item in self.items:
            similarity = self.embedding_engine.cosine_similarity(embedding, item.embedding)
            if similarity > config.PM_SIMILARITY_THRESHOLD:
                # 刷新时间戳
                old_time = item.timestamp
                item.timestamp = datetime.now()
                item.recency_score = 1.0
                self._changed = True
                logger.info(f"PM: 刷新项 [{item.id}] 时间戳 (相似度: {similarity:.3f})")
                return True, item.id

        # 作为新项添加
        if self.is_full():
            # 需要先驱逐一项
            evicted = self._evict_lowest()
            if evicted:
                logger.info(f"PM: 驱逐最低得分项 [{evicted.id}] (得分: {evicted.calculate_score():.3f})")

        # 创建新项
        new_item = PMItem(
            id=self._next_id,
            content=content,
            embedding=embedding,
            timestamp=datetime.now(),
            recency_score=1.0,
            relevance_score=0.5,
            importance_score=0.5
        )
        self._next_id += 1
        self.items.append(new_item)
        self._changed = True

        logger.info(f"PM: 添加新项 [{new_item.id}] '{content[:30]}...' (当前: {len(self.items)}/{config.PM_CAPACITY})")
        return True, new_item.id

    def _evict_lowest(self) -> Optional[PMItem]:
        """驱逐综合得分最低的项"""
        if not self.items:
            return None

        lowest_item = min(self.items, key=lambda x: x.calculate_score())
        self.items.remove(lowest_item)
        return lowest_item

    def update_scores(self, relevance_calculator=None, importance_calculator=None):
        """
        更新所有项的得分

        Args:
            relevance_calculator: 计算相关性得分的函数
            importance_calculator: 计算重要性得分的函数
        """
        now = datetime.now()

        for item in self.items:
            # 更新新近度得分 (指数衰减，30分钟衰减到0.5)
            age_seconds = (now - item.timestamp).total_seconds()
            item.recency_score = max(0.1, np.exp(-age_seconds / 1800))  # 30分钟半衰期

            # 更新相关性得分
            if relevance_calculator:
                item.relevance_score = relevance_calculator(item)

            # 更新重要性得分
            if importance_calculator:
                item.importance_score = importance_calculator(item)

    def get_all_embeddings(self) -> Optional[np.ndarray]:
        """获取所有项的embedding矩阵"""
        if not self.items:
            return None
        return np.array([item.embedding for item in self.items])

    def get_slot_scores(self) -> List[float]:
        """获取所有槽位的得分列表"""
        return [item.calculate_score() for item in self.items]

    def get_min_slot_score(self) -> float:
        """获取最低槽位得分"""
        if not self.items:
            return 0.0
        return min(item.calculate_score() for item in self.items)

    def get_state_summary(self) -> dict:
        """获取PM状态摘要"""
        return {
            "count": len(self.items),
            "capacity": config.PM_CAPACITY,
            "items": [
                {
                    "id": item.id,
                    "content": item.content[:40] + "..." if len(item.content) > 40 else item.content,
                    "score": round(item.calculate_score(), 3),
                    "age_seconds": round((datetime.now() - item.timestamp).total_seconds(), 1)
                }
                for item in self.items
            ]
        }


class EpisodicBuffer:
    """
    情景缓冲区 (Episodic Buffer, EB)

    - 容量: 4个组块
    - 进入机制: 新项进入PM后，由LLM判定归属或新开组块
    - 退出机制: 满4个时，基于组块内均分剔除最弱组块
    """

    def __init__(
        self,
        embedding_engine: EmbeddingEngine,
        doubao_client: DoubaoClient
    ):
        self.chunks: List[EBChunk] = []
        self.embedding_engine = embedding_engine
        self.doubao_client = doubao_client
        self._changed = False
        self._next_id = 0

    @property
    def changed(self) -> bool:
        """检查EB是否在最近操作中发生了变化"""
        return self._changed

    def reset_changed_flag(self):
        """重置变化标志"""
        self._changed = False

    def is_full(self) -> bool:
        """检查EB是否已满"""
        return len(self.chunks) >= config.EB_CAPACITY

    def process_new_pm(self, pm: PerceptionMemory, new_pm_id: int, new_content: str = None) -> Optional[int]:
        """
        处理新的PM项，分配到组块

        Args:
            pm: 感知记忆对象
            new_pm_id: 新添加/刷新的PM项ID
            new_content: 实际新进入的内容（可能与PM项内容不同，当相似度>0.95时）

        Returns:
            分配到的组块ID
        """
        self._changed = False

        # 找到PM项
        new_pm_item = next((item for item in pm.items if item.id == new_pm_id), None)
        if not new_pm_item:
            logger.warning(f"EB: 未找到PM项 [{new_pm_id}]")
            return None

        # 使用传入的新内容，如果没有则使用PM项的内容
        content_for_llm = new_content if new_content is not None else new_pm_item.content

        # 调用LLM判断归属
        result: ChunkAssignmentResult = self.doubao_client.assign_chunk(
            new_pm_content=content_for_llm,  # 使用实际新进入的内容
            existing_chunks=self.chunks
        )

        if result.is_new_chunk:
            # 需要新建组块
            if self.is_full():
                # 驱逐最弱组块
                evicted = self._evict_weakest(pm.items)
                if evicted:
                    logger.info(f"EB: 驱逐最弱组块 [{evicted.id}] (均分: {evicted.avg_score:.3f})")

            # 创建新组块
            new_chunk = EBChunk(
                id=self._next_id,
                summary=result.updated_summary,
                member_ids=[new_pm_id],
                embedding=self.embedding_engine.encode(result.updated_summary),
                avg_score=new_pm_item.calculate_score()
            )
            self._next_id += 1
            self.chunks.append(new_chunk)
            self._changed = True

            logger.info(f"EB: 创建新组块 [{new_chunk.id}] '{new_chunk.summary}' (当前: {len(self.chunks)}/{config.EB_CAPACITY})")
            return new_chunk.id

        else:
            # 添加到现有组块
            target_chunk = next(
                (c for c in self.chunks if c.id == result.assigned_chunk_id),
                None
            )
            if target_chunk:
                if new_pm_id not in target_chunk.member_ids:
                    target_chunk.member_ids.append(new_pm_id)
                target_chunk.summary = result.updated_summary
                target_chunk.embedding = self.embedding_engine.encode(result.updated_summary)
                target_chunk.update_avg_score(pm.items)
                self._changed = True

                logger.info(f"EB: 将PM项 [{new_pm_id}] 加入组块 [{target_chunk.id}] '{target_chunk.summary}'")
                return target_chunk.id

        return None

    def _evict_weakest(self, pm_items: List[PMItem]) -> Optional[EBChunk]:
        """驱逐平均得分最低的组块"""
        if not self.chunks:
            return None

        # 更新所有组块的平均得分
        for chunk in self.chunks:
            chunk.update_avg_score(pm_items)

        # 找到最弱组块
        weakest = min(self.chunks, key=lambda c: c.avg_score)
        self.chunks.remove(weakest)
        return weakest

    def get_best_matching_chunk(self, embedding: np.ndarray) -> Optional[EBChunk]:
        """
        获取与给定embedding最匹配的组块

        Args:
            embedding: 查询向量

        Returns:
            最匹配的组块，如果没有则返回None
        """
        if not self.chunks:
            return None

        best_chunk = None
        best_similarity = -1

        for chunk in self.chunks:
            if chunk.embedding is not None:
                similarity = self.embedding_engine.cosine_similarity(embedding, chunk.embedding)
                if similarity > best_similarity:
                    best_similarity = similarity
                    best_chunk = chunk

        return best_chunk

    def get_max_similarity(self, embedding: np.ndarray) -> float:
        """获取与给定embedding的最大相似度"""
        chunk = self.get_best_matching_chunk(embedding)
        if chunk and chunk.embedding is not None:
            return self.embedding_engine.cosine_similarity(embedding, chunk.embedding)
        return 0.0

    def get_state_summary(self) -> dict:
        """获取EB状态摘要"""
        return {
            "count": len(self.chunks),
            "capacity": config.EB_CAPACITY,
            "chunks": [
                {
                    "chunk_id": chunk.chunk_id,
                    "summary": chunk.summary,
                    "member_count": len(chunk.member_pm_ids),
                    "avg_score": round(chunk.avg_score, 3)
                }
                for chunk in self.chunks
            ]
        }


class WorkingMemory:
    """
    工作记忆 (Working Memory, WM)
    组合 PM 和 EB
    """

    def __init__(self):
        self.embedding_engine = get_embedding_engine()
        self.doubao_client = get_doubao_client()

        self.pm = PerceptionMemory(self.embedding_engine)
        self.eb = EpisodicBuffer(self.embedding_engine, self.doubao_client)

    def process_opportunity(self, opportunity: Opportunity) -> bool:
        """
        处理一个新的Opportunity，更新PM和EB

        Args:
            opportunity: 机会事件

        Returns:
            是否发生了变化
        """
        wm_changed = False

        # 使用 trigger.summary 作为内容
        content = opportunity.trigger.summary

        # 获取 embedding (如果已计算则使用，否则计算)
        embedding = opportunity.embedding
        if embedding is None:
            embedding = self.embedding_engine.encode(content)

        # 添加到PM
        pm_success, pm_id = self.pm.add_item(
            content=content,
            embedding=embedding
        )

        if pm_success and self.pm.changed:
            wm_changed = True

            # 如果PM变化，处理EB
            # 注意：传入实际的content，因为当相似度>0.95时，PM刷新现有项，但EB需要知道新进入的内容
            if pm_id is not None:
                self.eb.process_new_pm(self.pm, pm_id, new_content=content)
                if self.eb.changed:
                    wm_changed = True

        # 更新PM得分
        self.pm.update_scores()

        return wm_changed

    def get_state_summary(self) -> dict:
        """获取完整WM状态摘要"""
        return {
            "pm": self.pm.get_state_summary(),
            "eb": self.eb.get_state_summary()
        }

    def is_wm_changed(self) -> bool:
        """检查WM是否发生变化"""
        return self.pm.changed or self.eb.changed

    def reset_changed_flags(self):
        """重置所有变化标志"""
        self.pm.reset_changed_flag()
        self.eb.reset_changed_flag()
