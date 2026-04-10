# -*- coding: utf-8 -*-
"""
Decision Engine
实现效用函数计算和决策逻辑
"""

import logging
import uuid
from datetime import datetime, timedelta
from typing import Optional, Tuple

import numpy as np

import config
from models import Opportunity, ExecutionPayload, DecisionResult
from memory_wm import WorkingMemory
from embedding import get_embedding_engine
from doubao_client import get_doubao_client

logger = logging.getLogger(__name__)


class DecisionEngine:
    """
    D层决策引擎

    效用函数:
    Utility = Value - Cost

    Value = W_IMP * Imp + W_HIS * Rel_his + W_WM * Rel_wm
    Cost = W_CI * Ci + W_CD * Cd

    决策规则:
    - Utility > 0.5: EXECUTE
    - 0 < Utility <= 0.5: DEFER
    - Utility <= 0: DISCARD
    """

    def __init__(self):
        self.embedding_engine = get_embedding_engine()
        self.doubao_client = get_doubao_client()

    def calculate_utility(
        self,
        opportunity: Opportunity,
        wm: WorkingMemory
    ) -> Tuple[float, dict]:
        """
        计算Opportunity的效用值

        Args:
            opportunity: 机会事件
            wm: 工作记忆

        Returns:
            (效用值, 效用分解详情)
        """
        breakdown = {}

        # ============================================================
        # 收益项 (Value)
        # ============================================================

        # 1. 重要性 (Imp) - 调用Doubao API
        imp = self._calculate_importance(opportunity)
        breakdown["Imp"] = round(imp, 3)

        # 2. 历史相关性 (Rel_his)
        rel_his = self._calculate_historical_relevance(opportunity)
        breakdown["Rel_his"] = round(rel_his, 3)

        # 3. WM相关性 (Rel_wm)
        rel_wm = self._calculate_wm_relevance(opportunity, wm)
        breakdown["Rel_wm"] = round(rel_wm, 3)

        # 计算Value
        value = (
            config.W_IMP * imp +
            config.W_HIS * rel_his +
            config.W_WM * rel_wm
        )
        breakdown["Value"] = round(value, 3)

        # ============================================================
        # 成本项 (Cost)
        # ============================================================

        # 4. 干扰成本 (Ci)
        ci = self._calculate_interference_cost(opportunity, wm)
        breakdown["Ci"] = round(ci, 3)

        # 5. 替换成本 (Cd)
        cd = self._calculate_displacement_cost(opportunity, wm)
        breakdown["Cd"] = round(cd, 3)

        # 计算Cost
        cost = config.W_CI * ci + config.W_CD * cd
        breakdown["Cost"] = round(cost, 3)

        # ============================================================
        # 最终效用
        # ============================================================
        utility = value - cost
        breakdown["Utility"] = round(utility, 3)

        logger.info(
            f"Utility计算: Value={value:.3f} (Imp={imp:.3f}, Rel_his={rel_his:.3f}, Rel_wm={rel_wm:.3f}) "
            f"- Cost={cost:.3f} (Ci={ci:.3f}, Cd={cd:.3f}) = {utility:.3f}"
        )

        return utility, breakdown

    def _calculate_importance(self, opportunity: Opportunity) -> float:
        """
        计算重要性得分
        调用Doubao API，结合Tier1画像和干预事件
        """
        # 获取Tier1文本
        tier1_text = ""
        if opportunity.context.tier1_persona:
            tier1_text = str(opportunity.context.tier1_persona.critical_facts)

        score = self.doubao_client.score_importance(
            tier1_persona=tier1_text,
            opportunity_content=opportunity.trigger.summary
        )
        return score

    def _calculate_historical_relevance(self, opportunity: Opportunity) -> float:
        """
        计算历史相关性
        Rel_his = max(CosineSim(E, Tier2) * Decay, CosineSim(E, Tier3))

        Tier2使用时间衰减，Tier3直接取最大相似度
        """
        # 获取opportunity的embedding
        emb = opportunity.embedding
        if emb is None:
            emb = self.embedding_engine.encode(opportunity.trigger.summary)

        # Tier2: 长期记忆 (带时间衰减)
        tier2_score = 0.0
        if opportunity.context.tier2_memories:
            tier2_embeddings = []
            for mem in opportunity.context.tier2_memories:
                mem_emb = self.embedding_engine.encode(mem.memory_text)
                tier2_embeddings.append(mem_emb)
            if tier2_embeddings:
                tier2_emb_array = np.array(tier2_embeddings)
                max_sim_tier2 = self.embedding_engine.max_cosine_similarity(emb, tier2_emb_array)
                # 应用时间衰减 (假设长期记忆的衰减因子为0.8)
                tier2_score = max_sim_tier2 * 0.8

        # Tier3: 短期状态 (直接相似度)
        tier3_score = 0.0
        if opportunity.context.tier3_events:
            tier3_embeddings = []
            for event in opportunity.context.tier3_events:
                event_emb = self.embedding_engine.encode(event.summary)
                tier3_embeddings.append(event_emb)
            if tier3_embeddings:
                tier3_emb_array = np.array(tier3_embeddings)
                tier3_score = self.embedding_engine.max_cosine_similarity(emb, tier3_emb_array)

        return max(tier2_score, tier3_score)

    def _calculate_wm_relevance(
        self,
        opportunity: Opportunity,
        wm: WorkingMemory
    ) -> float:
        """
        计算WM相关性
        Rel_wm = max_{b in EB}(CosineSim(E, b))
        """
        emb = opportunity.embedding
        if emb is None:
            emb = self.embedding_engine.encode(opportunity.trigger.summary)

        return wm.eb.get_max_similarity(emb)

    def _calculate_interference_cost(
        self,
        opportunity: Opportunity,
        wm: WorkingMemory
    ) -> float:
        """
        计算干扰成本
        Ci = (1/7) * sum_{n=1}^{7}(1 - CosineSim(E, PM_n))

        如果PM不满7个，只计算现有的项
        """
        emb = opportunity.embedding
        if emb is None:
            emb = self.embedding_engine.encode(opportunity.trigger.summary)

        pm_embeddings = wm.pm.get_all_embeddings()
        if pm_embeddings is None or len(pm_embeddings) == 0:
            return 0.0

        # 计算与每个PM项的(1 - 相似度)
        similarities = self.embedding_engine.batch_cosine_similarity(emb, pm_embeddings)
        interference_values = 1 - similarities

        # 计算平均值
        ci = float(np.mean(interference_values))
        return ci

    def _calculate_displacement_cost(
        self,
        opportunity: Opportunity,
        wm: WorkingMemory
    ) -> float:
        """
        计算替换成本
        如果PM满7个，Cd = min(PM_slot_scores)；否则为0
        """
        if not wm.pm.is_full():
            return 0.0

        return wm.pm.get_min_slot_score()

    def make_decision(
        self,
        opportunity: Opportunity,
        wm: WorkingMemory
    ) -> DecisionResult:
        """
        根据效用值做出决策

        Returns:
            DecisionResult: 包含决策和详细信息
        """
        utility, breakdown = self.calculate_utility(opportunity, wm)

        if utility > config.UTILITY_THRESHOLD:
            action = "EXECUTE"
            reason = f"效用值 {utility:.3f} > 阈值 {config.UTILITY_THRESHOLD}，立即执行"
            payload = self._create_execution_payload(opportunity, wm)
        elif utility > 0:
            action = "DEFER"
            reason = f"效用值 {utility:.3f} 在 (0, {config.UTILITY_THRESHOLD}] 范围内，加入延迟队列"
            payload = None
        else:
            action = "DISCARD"
            reason = f"效用值 {utility:.3f} <= 0，直接丢弃"
            payload = None

        return DecisionResult(
            action=action,
            utility=utility,
            utility_breakdown=breakdown,
            payload=payload,
            reason=reason
        )

    def _create_execution_payload(
        self,
        opportunity: Opportunity,
        wm: WorkingMemory
    ) -> ExecutionPayload:
        """
        创建执行载荷
        """
        # 获取opportunity的embedding
        emb = opportunity.embedding
        if emb is None:
            emb = self.embedding_engine.encode(opportunity.trigger.summary)

        # 获取最相关的EB组块
        best_chunk = wm.eb.get_best_matching_chunk(emb)
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
            d_layer_decision="execute_now"
        )

    def recalculate_utility_for_pending(
        self,
        cached_imp: float,
        cached_rel_his: float,
        opportunity: Opportunity,
        wm: WorkingMemory
    ) -> Tuple[float, dict]:
        """
        为延迟队列中的项重新计算效用
        保持Imp和Rel_his不变，只重算Rel_wm, Ci, Cd

        Args:
            cached_imp: 缓存的重要性得分
            cached_rel_his: 缓存的历史相关性
            opportunity: 机会事件
            wm: 工作记忆

        Returns:
            (新的效用值, 效用分解)
        """
        breakdown = {}

        # 使用缓存的值
        imp = cached_imp
        breakdown["Imp"] = round(imp, 3)

        rel_his = cached_rel_his
        breakdown["Rel_his"] = round(rel_his, 3)

        # 重新计算WM相关性
        rel_wm = self._calculate_wm_relevance(opportunity, wm)
        breakdown["Rel_wm"] = round(rel_wm, 3)

        # 计算Value
        value = (
            config.W_IMP * imp +
            config.W_HIS * rel_his +
            config.W_WM * rel_wm
        )
        breakdown["Value"] = round(value, 3)

        # 重新计算成本
        ci = self._calculate_interference_cost(opportunity, wm)
        breakdown["Ci"] = round(ci, 3)

        cd = self._calculate_displacement_cost(opportunity, wm)
        breakdown["Cd"] = round(cd, 3)

        cost = config.W_CI * ci + config.W_CD * cd
        breakdown["Cost"] = round(cost, 3)

        utility = value - cost
        breakdown["Utility"] = round(utility, 3)

        return utility, breakdown


# 全局单例
_engine = None


def get_decision_engine() -> DecisionEngine:
    """获取全局决策引擎单例"""
    global _engine
    if _engine is None:
        _engine = DecisionEngine()
    return _engine
