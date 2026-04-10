# -*- coding: utf-8 -*-
"""
Pending Pool
实现延迟队列（挂起池）机制
"""

import logging
import uuid
from datetime import datetime, timedelta
from typing import List, Tuple, Optional

import config
from models import PendingItem, Opportunity, ExecutionPayload, DecisionResult
from memory_wm import WorkingMemory
from decision_engine import get_decision_engine, DecisionEngine

logger = logging.getLogger(__name__)


class PendingPool:
    """
    延迟队列（挂起池）

    - 入池条件: 0 < Utility <= 0.5
    - 重估触发: 每当D层WM（PM或EB）发生滚动更新时
    - 重估逻辑: 保持Imp和Rel_his不变，重新计算Rel_wm, Ci, Cd
    - 出池/销毁:
        - Utility > 0.5: 出池，发给E层
        - Utility <= 0: 直接丢弃
        - 超过TTL (30分钟): 丢弃
    """

    def __init__(self):
        self.items: List[PendingItem] = []
        self.decision_engine: Optional[DecisionEngine] = None

    def _get_decision_engine(self) -> DecisionEngine:
        """延迟获取决策引擎，避免循环依赖"""
        if self.decision_engine is None:
            self.decision_engine = get_decision_engine()
        return self.decision_engine

    def try_add(
        self,
        opportunity: Opportunity,
        utility: float,
        cached_imp: float,
        cached_rel_his: float
    ) -> bool:
        """
        尝试将Opportunity加入延迟队列

        Args:
            opportunity: 机会事件
            utility: 当前效用值
            cached_imp: 缓存的重要性得分
            cached_rel_his: 缓存的历史相关性

        Returns:
            是否成功加入
        """
        # 检查是否符合入池条件
        if utility <= 0 or utility > config.UTILITY_THRESHOLD:
            logger.debug(f"Utility {utility:.3f} 不在入池范围 (0, {config.UTILITY_THRESHOLD}]")
            return False

        # 创建延迟项
        pending_item = PendingItem(
            opportunity=opportunity,
            utility=utility,
            deferred_at=datetime.now(),
            ttl_expired_at=datetime.now() + timedelta(minutes=config.PENDING_TTL_MINUTES),
            cached_imp=cached_imp,
            cached_rel_his=cached_rel_his
        )

        self.items.append(pending_item)
        logger.info(
            f"PendingPool: 加入延迟队列 [{opportunity.opportunity_id}] '{opportunity.trigger.summary[:30]}...' "
            f"(Utility={utility:.3f}, TTL={config.PENDING_TTL_MINUTES}分钟, 当前队列: {len(self.items)})"
        )

        return True

    def on_wm_update(
        self,
        wm: WorkingMemory
    ) -> Tuple[List[DecisionResult], List[PendingItem]]:
        """
        WM更新时的重估触发

        Args:
            wm: 工作记忆

        Returns:
            (提升执行的项列表, 过期丢弃的项列表)
        """
        promoted = []
        expired = []

        # 1. 检查TTL过期
        items_to_remove = []
        for item in self.items:
            if item.is_expired():
                items_to_remove.append(item)
                expired.append(item)
                logger.info(
                    f"PendingPool: TTL过期丢弃 [{item.opportunity.opportunity_id}] '{item.opportunity.trigger.summary[:30]}...'"
                )

        for item in items_to_remove:
            self.items.remove(item)

        # 2. 重新估计剩余项的效用
        items_to_promote = []
        items_to_discard = []

        for item in self.items:
            new_utility, breakdown = self._get_decision_engine().recalculate_utility_for_pending(
                cached_imp=item.cached_imp,
                cached_rel_his=item.cached_rel_his,
                opportunity=item.opportunity,
                wm=wm
            )

            old_utility = item.utility
            item.utility = new_utility

            logger.info(
                f"PendingPool: 重估 [{item.opportunity.opportunity_id}] "
                f"Utility: {old_utility:.3f} -> {new_utility:.3f}"
            )

            if new_utility > config.UTILITY_THRESHOLD:
                # 可以出池执行
                items_to_promote.append(item)
                payload = self._create_payload(item, wm)
                result = DecisionResult(
                    action="EXECUTE",
                    utility=new_utility,
                    utility_breakdown=breakdown,
                    payload=payload,
                    reason=f"重估后效用 {new_utility:.3f} > 阈值 {config.UTILITY_THRESHOLD}，从延迟队列提升执行"
                )
                promoted.append(result)

            elif new_utility <= 0:
                # 应该丢弃
                items_to_discard.append(item)
                logger.info(
                    f"PendingPool: 重估后丢弃 [{item.opportunity.opportunity_id}] (Utility={new_utility:.3f} <= 0)"
                )

        # 从队列中移除提升和丢弃的项
        for item in items_to_promote:
            self.items.remove(item)
        for item in items_to_discard:
            self.items.remove(item)

        return promoted, expired

    def _create_payload(
        self,
        pending_item: PendingItem,
        wm: WorkingMemory
    ) -> ExecutionPayload:
        """创建执行载荷"""
        from embedding import get_embedding_engine

        opportunity = pending_item.opportunity
        embedding_engine = get_embedding_engine()

        # 获取最相关的EB组块
        best_chunk = wm.eb.get_best_matching_chunk(
            embedding_engine.encode(opportunity.trigger.summary)
        )
        current_episode = best_chunk.summary if best_chunk else None

        # 构建 llm_context
        llm_context = {
            "user_persona": opportunity.context.tier1_persona.critical_facts if opportunity.context.tier1_persona else {},
            "historical_memories": [m.memory_text for m in opportunity.context.tier2_memories] if opportunity.context.tier2_memories else [],
            "recent_events": [e.summary for e in opportunity.context.tier3_events] if opportunity.context.tier3_events else [],
            "current_cognitive_episode": current_episode
        }

        # 构建 payload
        payload = {
            "semantic_type": opportunity.trigger.semantic_type,
            "resolved_entity_id": opportunity.trigger.resolved_entity_id,
            "trigger_summary": opportunity.trigger.summary
        }

        return ExecutionPayload(
            plan_id=f"plan_{uuid.uuid4().hex[:8]}",
            opportunity_id=opportunity.opportunity_id,
            payload=payload,
            llm_context=llm_context,
            d_layer_decision="deferred_execute"
        )

    def remove_expired(self) -> List[PendingItem]:
        """
        移除过期的项

        Returns:
            被移除的项列表
        """
        expired = [item for item in self.items if item.is_expired()]
        for item in expired:
            self.items.remove(item)
            logger.info(
                f"PendingPool: TTL过期移除 [{item.opportunity.opportunity_id}] '{item.opportunity.trigger.summary[:30]}...'"
            )
        return expired

    def get_count(self) -> int:
        """获取队列中的项数"""
        return len(self.items)

    def is_empty(self) -> bool:
        """检查队列是否为空"""
        return len(self.items) == 0

    def get_state_summary(self) -> dict:
        """获取状态摘要"""
        return {
            "count": len(self.items),
            "items": [
                {
                    "opportunity_id": item.opportunity.opportunity_id,
                    "summary": item.opportunity.trigger.summary[:40] + "..."
                    if len(item.opportunity.trigger.summary) > 40
                    else item.opportunity.trigger.summary,
                    "utility": round(item.utility, 3),
                    "deferred_at": item.deferred_at.strftime("%H:%M:%S"),
                    "ttl_remaining_seconds": max(
                        0,
                        int((item.ttl_expired_at - datetime.now()).total_seconds())
                    )
                }
                for item in self.items
            ]
        }

    def clear(self):
        """清空队列"""
        self.items.clear()
        logger.info("PendingPool: 队列已清空")
