"""
Opportunity 构造器
从 B 层语义事件构建 D 层需要的 Opportunity 对象

输出格式严格匹配 D 层 models.py:
  Opportunity:
    - opportunity_id: str
    - created_at: datetime
    - trigger: TriggerInfo
        - semantic_event_id: str
        - resolved_entity_id: str
        - semantic_type: str
        - summary: str
    - context: OpportunityContext
        - tier1_persona: Tier1Persona (critical_facts: dict)
        - tier2_memories: List[Tier2MemoryItem (memory_text, base_importance)]
        - tier3_events: List[Tier3EventItem (summary, time)]
"""
import json
import uuid
from datetime import datetime
from typing import Dict, List, Any, Optional

from shared.logger import setup_logger
logger = setup_logger("c_layer")

from c_layer.config import PG_CONFIG, TIER3_DB_PATH


class OpportunityBuilder:
    def __init__(self):
        from c_layer.identity_store import IdentityStore
        self.identity_store = IdentityStore(PG_CONFIG)
        if not self.identity_store._db_available:
            logger.warning("IdentityStore 处于降级模式，身份数据将不会持久化")
        logger.info("OpportunityBuilder 初始化完成")

    def build_opportunity(self, b_event: dict) -> Optional[dict]:
        """
        从 B 层事件构造 Opportunity

        Args:
            b_event: B 层语义事件

        Returns:
            Opportunity 字典（符合 D 层 models.py 格式），或 None
        """
        try:
            # 1. 身份对齐
            face_emb = b_event.get("face_embedding")
            voice_emb = b_event.get("voice_embedding")

            if face_emb or voice_emb:
                resolved_id, is_new = self.identity_store.match_or_create(
                    face_embedding=face_emb,
                    voice_embedding=voice_emb
                )
                logger.info(f"身份对齐: entity={resolved_id} | new={is_new}")
            else:
                resolved_id = b_event.get("resolved_entity_id", "unknown")

            # 2. 存储到 Tier3
            self._store_to_tier3(b_event, resolved_id)

            # 3. 查询上下文
            tier1 = self._query_tier1("default_user")
            tier2_list = self._query_tier2(resolved_id, limit=5)
            tier3_list = self._query_tier3_recent(limit=10)

            # 4. 构造 Opportunity
            summary = b_event.get("summary", "")
            if not summary:
                summary = self._generate_summary(b_event)

            opportunity = {
                "opportunity_id": f"opp_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}",
                "created_at": datetime.now().isoformat(),
                "trigger": {
                    "semantic_event_id": b_event.get("semantic_event_id") or b_event.get("event_id", ""),
                    "resolved_entity_id": resolved_id,
                    "semantic_type": b_event.get("semantic_type", "unknown"),
                    "summary": summary,
                },
                "context": {
                    "tier1_persona": tier1,
                    "tier2_memories": tier2_list,
                    "tier3_events": tier3_list,
                }
            }

            logger.info(f"Opportunity 构造完成: id={opportunity['opportunity_id']} | "
                       f"type={opportunity['trigger']['semantic_type']} | entity={resolved_id}")
            return opportunity

        except Exception as e:
            logger.error(f"Opportunity 构造失败: {e}", exc_info=True)
            return None

    def _store_to_tier3(self, b_event: dict, resolved_id: str):
        """存储 B 层事件到 Tier3 SQLite"""
        import sqlite3
        import os

        # 确保目录存在
        os.makedirs(os.path.dirname(TIER3_DB_PATH), exist_ok=True)

        conn = sqlite3.connect(TIER3_DB_PATH)
        cur = conn.cursor()
        # 确保表存在
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tier3_events (
                semantic_event_id TEXT PRIMARY KEY,
                resolved_entity_id TEXT,
                start_ts TEXT,
                end_ts TEXT,
                semantic_type TEXT,
                summary TEXT,
                dialogue_act TEXT,
                platform_hint TEXT,
                ui_thread_hint TEXT,
                extra_slots_json TEXT
            )
        """)

        event_id = b_event.get("semantic_event_id") or b_event.get("event_id", str(uuid.uuid4()))
        time_info = b_event.get("time", {})
        start_ts = time_info.get("start_ts", "") if isinstance(time_info, dict) else ""
        end_ts = time_info.get("end_ts", "") if isinstance(time_info, dict) else ""

        cur.execute("""
            INSERT OR REPLACE INTO tier3_events
            (semantic_event_id, resolved_entity_id, start_ts, end_ts, semantic_type, summary, dialogue_act, platform_hint, ui_thread_hint, extra_slots_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            event_id,
            resolved_id,
            start_ts,
            end_ts,
            b_event.get("semantic_type", "unknown"),
            b_event.get("summary", ""),
            b_event.get("dialogue_act"),
            b_event.get("platform_hint"),
            b_event.get("ui_thread_hint"),
            json.dumps({k: v for k, v in b_event.items()
                       if k not in ["face_embedding", "voice_embedding"]}, ensure_ascii=False),
        ))
        conn.commit()
        conn.close()
        logger.info(f"Tier3 存储: event={event_id}")

    def _query_tier1(self, user_id: str) -> Optional[dict]:
        """查询 Tier1 用户画像"""
        try:
            import psycopg
            conn = psycopg.connect(**PG_CONFIG, autocommit=True, connect_timeout=3)
            cur = conn.cursor()
            cur.execute("SELECT critical_facts FROM tier1_persona WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
            cur.close()
            conn.close()
            if row and row[0]:
                return {"critical_facts": row[0]}
        except Exception as e:
            logger.warning(f"Tier1 查询失败: {e}")
        return None

    def _query_tier2(self, entity_id: str, limit: int = 5) -> list:
        """查询 Tier2 长期记忆"""
        try:
            import psycopg
            conn = psycopg.connect(**PG_CONFIG, autocommit=True, connect_timeout=3)
            cur = conn.cursor()
            cur.execute(
                "SELECT memory_text, base_importance FROM tier2_memories WHERE resolved_entity_id = %s ORDER BY last_accessed_at DESC LIMIT %s",
                (entity_id, limit)
            )
            rows = cur.fetchall()
            cur.close()
            conn.close()
            return [{"memory_text": r[0], "base_importance": r[1]} for r in rows]
        except Exception as e:
            logger.warning(f"Tier2 查询失败: {e}")
            return []

    def _query_tier3_recent(self, limit: int = 10) -> list:
        """查询 Tier3 最近短期事件"""
        import sqlite3
        try:
            conn = sqlite3.connect(TIER3_DB_PATH)
            cur = conn.cursor()
            cur.execute(
                "SELECT summary, start_ts FROM tier3_events ORDER BY start_ts DESC LIMIT ?",
                (limit,)
            )
            rows = cur.fetchall()
            conn.close()
            return [{"summary": r[0], "time": r[1] or ""} for r in rows]
        except Exception as e:
            logger.warning(f"Tier3 查询失败: {e}")
            return []

    def _generate_summary(self, b_event: dict) -> str:
        """从 B 层事件生成摘要文本"""
        sem_type = b_event.get("semantic_type", "unknown")
        entity = b_event.get("resolved_entity_id", "unknown")
        payload = b_event.get("payload", {})

        if sem_type == "speech_segment":
            text = payload.get("text", "")
            return f"{entity} 说：{text[:100]}" if text else f"{entity} 有语音活动"
        elif sem_type == "face_detection":
            return f"检测到 {entity} 的面部"
        elif sem_type == "person_track":
            return f"{entity} 出现并移动"
        elif sem_type == "scene_detection":
            label = payload.get("scene_label", "")
            return f"场景变化: {label[:100]}"
        else:
            return json.dumps(b_event, ensure_ascii=False)[:200]
