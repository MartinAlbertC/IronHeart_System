#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
D层（决策层）MQ 模式入口
- 订阅 C 层的 opportunities 队列
- 经过 WM + 效用函数决策
- EXECUTE → 发送到 execution_plans 队列
- DEFER → 加入 PendingPool
- DISCARD → 丢弃
"""
import sys
import os
import json
import time
from pathlib import Path

# 使本层模块可互相 import
sys.path.insert(0, str(Path(__file__).parent))
# 使 shared 可导入
sys.path.insert(0, str(Path(__file__).parent.parent))

from shared import MQClient, setup_logger
from shared.logger import log_event_inbound, log_event_outbound
from models import Opportunity, ExecutionPayload, DecisionResult
from memory_wm import WorkingMemory
from decision_engine import get_decision_engine
from pending_pool import PendingPool

logger = setup_logger("d_layer")


class DLayerRunner:
    """D层 MQ 模式运行器"""

    def __init__(self):
        self.mq = MQClient()
        self.wm = WorkingMemory()
        self.pending_pool = PendingPool()
        self.decision_engine = get_decision_engine()
        logger.info("D层初始化完成")

    def _build_execution_payload(self, opp: Opportunity) -> ExecutionPayload:
        """构建发送给 E 层的执行载荷"""
        import uuid
        from embedding import get_embedding_engine
        embedding_engine = get_embedding_engine()

        emb = opp.embedding
        if emb is None:
            emb = embedding_engine.encode(opp.trigger.summary)

        best_chunk = self.wm.eb.get_best_matching_chunk(emb)
        current_episode = best_chunk.summary if best_chunk else None

        llm_context = {
            "user_persona": opp.context.tier1_persona.critical_facts if opp.context.tier1_persona else {},
            "historical_memories": [m.memory_text for m in opp.context.tier2_memories],
            "recent_events": [e.summary for e in opp.context.tier3_events],
            "current_cognitive_episode": current_episode
        }

        payload = {
            "semantic_type": opp.trigger.semantic_type,
            "resolved_entity_id": opp.trigger.resolved_entity_id,
            "trigger_summary": opp.trigger.summary
        }

        return ExecutionPayload(
            plan_id=f"plan_{uuid.uuid4().hex[:8]}",
            opportunity_id=opp.opportunity_id,
            payload=payload,
            llm_context=llm_context,
            d_layer_decision="execute_now"
        )

    def process_opportunity(self, opportunity: Opportunity):
        """处理一个 Opportunity"""
        opp_id = opportunity.opportunity_id
        summary = opportunity.trigger.summary
        logger.info(f"收到 Opportunity [{opp_id}]: {summary}")

        # Enhanced logging: complete inbound Opportunity
        log_event_inbound(logger, "C", "Opportunity", opportunity.model_dump(mode="json"))

        # 1. 更新工作记忆
        wm_changed = self.wm.process_opportunity(opportunity)

        # Log WM/EB state after processing
        wm_state = self.wm.get_state_summary()
        sep = "=" * 70
        logger.info(f"\n{sep}")
        logger.info(">>> WORKING MEMORY STATE")
        logger.info(sep)
        logger.info(f"PM: {wm_state['pm']['count']}/{wm_state['pm']['capacity']} items")
        for item in wm_state['pm']['items']:
            logger.info(f"  [{item['id']}] score={item['score']:.3f} age={item['age_seconds']}s | {item['content']}")
        logger.info(f"EB: {wm_state['eb']['count']}/{wm_state['eb']['capacity']} chunks")
        for chunk in wm_state['eb']['chunks']:
            logger.info(f"  [{chunk['chunk_id']}] avg={chunk['avg_score']:.3f} members={chunk['member_count']} | {chunk['summary']}")
        logger.info(f"{sep}\n")

        # 2. 如果 WM 变化，触发 PendingPool 重估
        if wm_changed:
            promoted, expired = self.pending_pool.on_wm_update(
                self.wm
            )
            for result in promoted:
                if result.payload:
                    self._send_to_e_layer(result.payload)
                    logger.info(f"PendingPool 提升: [{result.payload.opportunity_id}]")

        # 3. 对当前 Opportunity 做决策
        result = self.decision_engine.make_decision(opportunity, self.wm)

        # Log decision details
        sep = "=" * 70
        logger.info(f"\n{sep}")
        logger.info(f">>> DECISION: {result.action} | Utility={result.utility:.3f}")
        logger.info(sep)
        if hasattr(result, 'utility_breakdown') and result.utility_breakdown:
            for k, v in result.utility_breakdown.items():
                logger.info(f"  {k}: {v:.3f}")
        logger.info(f"{sep}\n")

        if result.action == "EXECUTE":
            payload = self._build_execution_payload(opportunity)
            self._send_to_e_layer(payload)
            logger.info(f"EXECUTE [{opp_id}] | Utility={result.utility:.3f} | {summary}")

        elif result.action == "DEFER":
            imp = result.utility_breakdown.get("Imp", 0.5)
            rel_his = result.utility_breakdown.get("Rel_his", 0.5)
            self.pending_pool.try_add(opportunity, result.utility, imp, rel_his)
            logger.info(f"DEFER [{opp_id}] | Utility={result.utility:.3f} | PendingPool={self.pending_pool.get_count()}")

        elif result.action == "DISCARD":
            logger.info(f"DISCARD [{opp_id}] | Utility={result.utility:.3f}")

        self.wm.reset_changed_flags()

    def _send_to_e_layer(self, payload: ExecutionPayload):
        """发送执行计划到 execution_plans 队列"""
        # Enhanced logging: complete outbound ExecutionPayload
        log_event_outbound(logger, "E", "ExecutionPayload", payload.model_dump(mode="json"))
        msg = payload.model_dump(mode="json")
        success = self.mq.publish("execution_plans", msg)
        if success:
            logger.info(f"[MQ→execution_plans] 已发送 plan={payload.plan_id}")
        else:
            logger.error(f"[MQ→execution_plans] 发送失败 plan={payload.plan_id}")

    def run(self):
        """主循环：从 opportunities 队列接收消息"""
        logger.info("=" * 50)
        logger.info("D层（决策层）启动 - 订阅 opportunities 队列")
        logger.info("=" * 50)

        while True:
            try:
                msg = self.mq.receive("opportunities")
                if msg is None:
                    logger.warning("收到空消息，1秒后重试")
                    time.sleep(1)
                    continue

                # 反序列化为 Opportunity
                opportunity = Opportunity.model_validate(msg)
                self.process_opportunity(opportunity)

            except Exception as e:
                logger.error(f"处理异常: {e}", exc_info=True)
                time.sleep(1)


if __name__ == "__main__":
    runner = DLayerRunner()
    runner.run()
