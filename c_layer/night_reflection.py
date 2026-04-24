"""
夜间反思模块
1) 提纯 Tier3 事件并写入 Tier2
2) 结合 Tier3 + 身份表更新 identity labels/name（LLM 参与）
3) 谨慎更新 Tier1 核心画像
"""

import argparse
import hashlib
import json
import logging
import os
import sqlite3
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Any, Optional

import psycopg

logger = logging.getLogger("c_layer.night_reflection")

try:
    from .identity_store import IdentityStore
    from .llm_client import CLayerLLMClient
except ImportError:
    try:
        from models.identity_store import IdentityStore
        from llm_client import CLayerLLMClient
    except Exception:
        from identity_store import IdentityStore
        from llm_client import CLayerLLMClient


class NightReflector:
    def __init__(
        self,
        pg_config: Dict[str, str],
        tier3_db_path: str,
        user_id: str,
        model_name: str = "deepseek-chat",
    ):
        self.pg_config = pg_config
        self.tier3_db_path = tier3_db_path
        self.user_id = user_id
        self.model_name = model_name
        self.identity_store = IdentityStore(pg_config)
        self.llm_client = CLayerLLMClient(model_name=model_name)

    def _pg_conn(self):
        return psycopg.connect(**self.pg_config, autocommit=False)

    def _sqlite_conn(self):
        return sqlite3.connect(self.tier3_db_path)

    def load_tier3_events(self) -> List[Dict[str, Any]]:
        """兼容读取 tier3_events 与 events/new_person_events。"""
        conn = self._sqlite_conn()
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {r[0] for r in cur.fetchall()}

        unified: List[Dict[str, Any]] = []

        if "tier3_events" in tables:
            cur.execute(
                """
                SELECT semantic_event_id, resolved_entity_id, start_ts, end_ts,
                       semantic_type, summary, dialogue_act, platform_hint,
                       ui_thread_hint, extra_slots_json
                FROM tier3_events
                """
            )
            for r in cur.fetchall():
                extra = {}
                if r[9]:
                    try:
                        extra = json.loads(r[9])
                    except Exception:
                        extra = {"raw": r[9]}
                unified.append(
                    {
                        "event_id": r[0],
                        "resolved_entity_id": r[1],
                        "start_ts": r[2],
                        "end_ts": r[3],
                        "semantic_type": r[4],
                        "summary": r[5] or "",
                        "dialogue_act": r[6],
                        "platform_hint": r[7],
                        "ui_thread_hint": r[8],
                        "extra_slots": extra,
                    }
                )

        if "events" in tables:
            cur.execute(
                """
                SELECT event_id, resolved_entity_id, timestamp, event_type, content
                FROM events
                """
            )
            for r in cur.fetchall():
                content = {}
                if r[4]:
                    try:
                        content = json.loads(r[4])
                    except Exception:
                        content = {"raw": r[4]}
                unified.append(
                    {
                        "event_id": r[0],
                        "resolved_entity_id": r[1],
                        "start_ts": r[2],
                        "end_ts": r[2],
                        "semantic_type": r[3] or "unknown",
                        "summary": content.get("summary")
                        or content.get("content")
                        or json.dumps(content, ensure_ascii=False)[:300],
                        "dialogue_act": content.get("dialogue_act"),
                        "platform_hint": content.get("platform_hint"),
                        "ui_thread_hint": content.get("ui_thread_hint"),
                        "extra_slots": content,
                    }
                )

        conn.close()
        return unified

    def _call_llm_for_tier2_extraction(
        self,
        entity_id: str,
        events: List[Dict[str, Any]],
        existing_tier2_memories: List[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        调用 LLM 从 Tier3 事件列表中提取 Tier2 长期记忆

        Args:
            entity_id: 实体 ID
            events: 该实体的 Tier3 事件列表
            existing_tier2_memories: 现有的 Tier2 记忆列表（用于合并）

        Returns:
            {
                "memories": [...],
                "updated_memories": [...],
                "reason": "提取理由",
                "fallback": True/False
            }
        """
        # 使用统一的 LLM 客户端，传入现有 Tier2 记忆
        return self.llm_client.extract_tier2_memories(entity_id, events, existing_tier2_memories)

    def _topic_key(self, event: Dict[str, Any]) -> str:
        """生成事件的主题键（用于降级模式下的规则合并）"""
        st = (event.get("semantic_type") or "unknown").strip().lower()
        sm = (event.get("summary") or "").strip().lower()
        digest = hashlib.md5(sm.encode("utf-8")).hexdigest()[:8]
        return f"{st}:{digest}"

    def _importance(self, event: Dict[str, Any], duplicate_count: int) -> float:
        """计算事件的重要性分数（用于降级模式）"""
        event_type = (event.get("semantic_type") or "unknown").lower()
        base = 0.3
        if any(k in event_type for k in ["error", "conflict", "alarm", "risk"]):
            base += 0.3
        if any(k in event_type for k in ["plan", "promise", "task", "todo"]):
            base += 0.2
        if duplicate_count >= 2:
            base += 0.15
        return max(0.0, min(1.0, base))

    def refine_to_tier2(self, events: List[Dict[str, Any]], dry_run: bool = False) -> Dict[str, int]:
        """
        提纯 Tier3 事件并写入 tier2_memories。
        使用 LLM 提取长期记忆特征，降级时使用规则合并。

        数据流：Tier3（当天事件）+ Tier2（现有记忆）→ 更新 Tier2
        """
        # 按实体分组
        by_entity = defaultdict(list)
        for e in events:
            entity = e.get("resolved_entity_id") or "unknown"
            by_entity[entity].append(e)

        # 查询现有 Tier2 记忆（用于合并）
        existing_tier2_by_entity = defaultdict(list)
        try:
            conn = self._pg_conn()
            cur = conn.cursor()
            for entity_id in by_entity.keys():
                cur.execute("""
                    SELECT memory_id, memory_text, base_importance
                    FROM tier2_memories
                    WHERE resolved_entity_id = %s
                    ORDER BY base_importance DESC, created_at DESC
                    LIMIT 20
                """, (entity_id,))
                for row in cur.fetchall():
                    existing_tier2_by_entity[entity_id].append({
                        "memory_id": row[0],
                        "memory_text": row[1],
                        "base_importance": row[2],
                    })
            cur.close()
            conn.close()
        except Exception as e:
            logger.warning(f"查询现有 Tier2 记忆失败：{e}")

        prepared = []
        updated = []  # 需要更新的现有记忆
        llm_extraction_count = 0

        for entity_id, entity_events in by_entity.items():
            # 1. 尝试使用 LLM 提取特征（传入现有 Tier2 记忆）
            llm_result = self._call_llm_for_tier2_extraction(
                entity_id,
                entity_events,
                existing_tier2_by_entity.get(entity_id, []),
            )

            if llm_result.get("memories"):
                # LLM 提取成功 - 新增记忆
                for mem in llm_result["memories"]:
                    base_ts = entity_events[-1].get("start_ts") or datetime.now().isoformat()
                    digest = hashlib.md5(f"{entity_id}|{mem.get('memory_text', '')[:50]}|{base_ts}".encode("utf-8")).hexdigest()[:12]
                    memory_id = f"nm_{entity_id}_{digest}"

                    memory_text = (
                        f"[type={mem.get('category', 'extracted')}] {mem['memory_text']}\n"
                        f"[from_tier3_llm] event_count={len(entity_events)} reason={mem.get('reason', llm_result.get('reason', ''))}"
                    )

                    prepared.append({
                        "memory_id": memory_id,
                        "resolved_entity_id": entity_id,
                        "memory_text": memory_text,
                        "base_importance": float(mem.get("base_importance", 0.5)),
                        "created_at": base_ts,
                    })

                llm_extraction_count += 1

            if llm_result.get("updated_memories"):
                # LLM 返回需要更新的现有记忆
                for mem in llm_result["updated_memories"]:
                    updated.append({
                        "memory_id": mem.get("memory_id"),
                        "memory_text": mem.get("memory_text"),
                        "base_importance": float(mem.get("base_importance", 0.5)),
                    })

            if not llm_result.get("memories") and not llm_result.get("updated_memories"):
                # LLM 降级：使用规则合并
                # 按 topic_key 分组
                grouped = defaultdict(list)
                for e in entity_events:
                    topic_key = self._topic_key(e)
                    grouped[(entity_id, topic_key)].append(e)

                for (entity, topic), rows in grouped.items():
                    rows = sorted(rows, key=lambda x: (x.get("start_ts") or ""))
                    latest = rows[-1]
                    merged_summary = " | ".join(
                        list(dict.fromkeys([r.get("summary") or "" for r in rows if r.get("summary")]))
                    )[:1200]
                    importance = self._importance(latest, len(rows))
                    base_ts = latest.get("start_ts") or datetime.now().isoformat()
                    digest = hashlib.md5(f"{entity}|{topic}|{base_ts}".encode("utf-8")).hexdigest()[:12]
                    memory_id = f"nm_{entity}_{digest}"

                    memory_text = (
                        f"[type={latest.get('semantic_type','unknown')}] {merged_summary}\n"
                        f"[from_tier3] event_count={len(rows)} topic={topic}"
                    )

                    prepared.append({
                        "memory_id": memory_id,
                        "resolved_entity_id": entity,
                        "memory_text": memory_text,
                        "base_importance": importance,
                        "created_at": base_ts,
                    })

        if dry_run:
            return {
                "input_events": len(events),
                "after_merge": len(prepared),
                "updated": len(updated),
                "llm_extraction": llm_extraction_count,
                "written": 0,
            }

        # 写入数据库（新增 + 更新）
        conn = self._pg_conn()
        cur = conn.cursor()
        written = 0
        try:
            # 写入新增记忆
            for m in prepared:
                cur.execute(
                    """
                    INSERT INTO tier2_memories
                    (memory_id, resolved_entity_id, memory_text, embedding, base_importance, created_at, last_accessed_at, access_count)
                    VALUES (%s, %s, %s, NULL, %s, %s, %s, 0)
                    ON CONFLICT (memory_id) DO UPDATE
                    SET memory_text = EXCLUDED.memory_text,
                        base_importance = EXCLUDED.base_importance,
                        last_accessed_at = CURRENT_TIMESTAMP
                    """,
                    (
                        m["memory_id"],
                        m["resolved_entity_id"],
                        m["memory_text"],
                        m["base_importance"],
                        m["created_at"],
                        m["created_at"],
                    ),
                )
                written += 1

            # 更新现有记忆
            for m in updated:
                cur.execute(
                    """
                    UPDATE tier2_memories
                    SET memory_text = %s,
                        base_importance = %s,
                        last_accessed_at = CURRENT_TIMESTAMP
                    WHERE memory_id = %s
                    """,
                    (m["memory_text"], m["base_importance"], m["memory_id"]),
                )
                written += 1

            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()
            conn.close()

        return {
            "input_events": len(events),
            "after_merge": len(prepared),
            "updated": len(updated),
            "llm_extraction": llm_extraction_count,
            "written": written,
        }

    def _call_llm_for_identity(
        self,
        entity_id: str,
        current_labels: Optional[str],
        snippets: List[str],
    ) -> Dict[str, Any]:
        """调用 LLM 生成 identity 更新建议，通过统一 LLM 客户端。"""
        return self.llm_client.infer_identity(entity_id, current_labels, snippets)

    def update_identity_with_llm(self, events: List[Dict[str, Any]], dry_run: bool = False) -> Dict[str, int]:
        by_entity = defaultdict(list)
        for e in events:
            entity = e.get("resolved_entity_id")
            if entity:
                by_entity[entity].append(e)

        suggestions = []
        for entity_id, rows in by_entity.items():
            current = self.identity_store.get_entity(entity_id) or {}
            snippets = [r.get("summary") or "" for r in rows if r.get("summary")]
            suggestions.append(
                self._call_llm_for_identity(entity_id, current.get("labels"), snippets)
            )

        if dry_run:
            return {
                "entities": len(by_entity),
                "labels_updated": 0,
                "names_updated": 0,
            }

        labels_updated = 0
        names_updated = 0

        def _to_text(val: Any) -> str:
            if val is None:
                return ""
            if isinstance(val, str):
                return val.strip()
            if isinstance(val, (list, tuple)):
                return ", ".join([str(x).strip() for x in val if str(x).strip()])
            if isinstance(val, dict):
                return json.dumps(val, ensure_ascii=False)
            return str(val).strip()

        for s in suggestions:
            conf = float(s.get("confidence", 0.0) or 0.0)
            entity_id = str(s.get("entity_id") or "").strip()
            if not entity_id:
                continue

            proposed_labels = _to_text(s.get("proposed_labels"))
            proposed_name = _to_text(s.get("proposed_name")) or None

            if conf >= 0.70 and proposed_labels:
                if self.identity_store.update_labels(entity_id, proposed_labels):
                    labels_updated += 1

            if conf >= 0.85 and proposed_name and proposed_name != entity_id:
                if self.identity_store.rename_entity_everywhere(entity_id, proposed_name, self.tier3_db_path):
                    names_updated += 1

        return {
            "entities": len(by_entity),
            "labels_updated": labels_updated,
            "names_updated": names_updated,
        }

    def update_tier1_persona(self, stats: Dict[str, Any], dry_run: bool = False) -> bool:
        """更新 Tier1 用户画像（仅存储统计信息，不使用 LLM）"""
        if dry_run:
            return True

        conn = self._pg_conn()
        cur = conn.cursor()
        try:
            cur.execute(
                "SELECT critical_facts FROM tier1_persona WHERE user_id = %s",
                (self.user_id,),
            )
            row = cur.fetchone()
            current = row[0] if row and row[0] else {}
            if not isinstance(current, dict):
                current = {}

            current.setdefault("night_reflection", {})
            current["night_reflection"].update(
                {
                    "last_run_at": datetime.now().isoformat(),
                    "tier3_events": stats.get("tier3_events", 0),
                    "tier2_written": stats.get("tier2_written", 0),
                    "identity_labels_updated": stats.get("labels_updated", 0),
                    "identity_names_updated": stats.get("names_updated", 0),
                }
            )

            cur.execute(
                """
                INSERT INTO tier1_persona (user_id, system_prompt_base, critical_facts)
                VALUES (%s, %s, %s)
                ON CONFLICT (user_id)
                DO UPDATE SET critical_facts = EXCLUDED.critical_facts,
                              updated_at = CURRENT_TIMESTAMP
                """,
                (self.user_id, "", json.dumps(current, ensure_ascii=False)),
            )
            conn.commit()
            return True
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()
            conn.close()

    def update_tier1_persona_with_llm(
        self,
        events: List[Dict[str, Any]],
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """
        使用 LLM 从 Tier2 长期记忆中提取 Tier1 核心画像

        数据流：Tier2（长期记忆）→ Tier1（核心画像）
        Tier2 已经过筛选和合并，是更稳定的数据源

        Args:
            events: Tier3 事件列表（用于上下文参考）
            dry_run: 是否只模拟执行

        Returns:
            {
                "critical_facts": {...},
                "updated": True/False,
                "reason": "..."
            }
        """
        # 1. 查询现有 Tier2 记忆（主要数据源）
        tier2_memories = []
        try:
            conn = self._pg_conn()
            cur = conn.cursor()
            # 获取所有与该用户相关的 Tier2 记忆
            cur.execute("""
                SELECT memory_id, resolved_entity_id, memory_text, base_importance, created_at
                FROM tier2_memories
                ORDER BY base_importance DESC, created_at DESC
                LIMIT 50
            """)
            for row in cur.fetchall():
                tier2_memories.append({
                    "memory_id": row[0],
                    "resolved_entity_id": row[1],
                    "memory_text": row[2],
                    "base_importance": row[3],
                    "created_at": str(row[4]) if row[4] else "",
                })
            cur.close()
            conn.close()
        except Exception as e:
            logger.warning(f"读取 Tier2 记忆失败：{e}")

        if not tier2_memories:
            return {
                "critical_facts": {},
                "updated": False,
                "reason": "没有找到 Tier2 记忆",
            }

        # 2. 获取当前 critical_facts
        current_facts = {}
        try:
            conn = self._pg_conn()
            cur = conn.cursor()
            cur.execute(
                "SELECT critical_facts FROM tier1_persona WHERE user_id = %s",
                (self.user_id,),
            )
            row = cur.fetchone()
            if row and row[0]:
                current_facts = row[0] if isinstance(row[0], dict) else json.loads(row[0])
            cur.close()
            conn.close()
        except Exception as e:
            logger.warning(f"读取 Tier1 失败：{e}")

        if dry_run:
            return {
                "critical_facts": current_facts,
                "updated": False,
                "reason": "dry_run 模式",
            }

        # 3. 调用 LLM 从 Tier2 提取 Tier1（Tier3 事件作为上下文参考）
        llm_result = self.llm_client.update_tier1_persona(tier2_memories, current_facts, events)

        # 4. 更新 Tier1
        new_facts = llm_result.get("critical_facts", current_facts)
        if new_facts != current_facts:
            try:
                conn = self._pg_conn()
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO tier1_persona (user_id, system_prompt_base, critical_facts)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (user_id)
                    DO UPDATE SET critical_facts = EXCLUDED.critical_facts,
                                  updated_at = CURRENT_TIMESTAMP
                    """,
                    (self.user_id, "", json.dumps(new_facts, ensure_ascii=False)),
                )
                conn.commit()
                cur.close()
                conn.close()

                logger.info(f"Tier1 已更新：{len(new_facts)} 个特征")
                return {
                    "critical_facts": new_facts,
                    "updated": True,
                    "reason": llm_result.get("reason", ""),
                }
            except Exception as e:
                logger.error(f"更新 Tier1 失败：{e}")
                return {
                    "critical_facts": current_facts,
                    "updated": False,
                    "reason": f"数据库更新失败：{e}",
                }

        return {
            "critical_facts": current_facts,
            "updated": False,
            "reason": llm_result.get("reason", "LLM 未提取到新特征"),
        }

    def run(
        self,
        dry_run: bool = False,
        enable_tier1_update: bool = False,
        enable_tier1_llm: bool = False,
    ) -> Dict[str, Any]:
        """
        执行夜间反思

        Args:
            dry_run: 是否只模拟执行
            enable_tier1_update: 是否更新 Tier1（仅统计信息）
            enable_tier1_llm: 是否使用 LLM 提取 Tier1 特征

        Returns:
            {
                "tier2": {...},
                "identity": {...},
                "tier1": {...},  # 仅当 enable_tier1_llm 时
                "summary": {...}
            }
        """
        events = self.load_tier3_events()
        tier2_stats = self.refine_to_tier2(events, dry_run=dry_run)
        identity_stats = self.update_identity_with_llm(events, dry_run=dry_run)

        merged = {
            "tier3_events": len(events),
            "tier2_written": tier2_stats.get("written", 0),
            "llm_extraction": tier2_stats.get("llm_extraction", 0),
            "labels_updated": identity_stats.get("labels_updated", 0),
            "names_updated": identity_stats.get("names_updated", 0),
            "dry_run": dry_run,
        }

        # Tier1 更新（LLM 提取）
        tier1_result = None
        if enable_tier1_llm:
            tier1_result = self.update_tier1_persona_with_llm(events, dry_run=dry_run)
            merged["tier1_updated"] = tier1_result.get("updated", False)
            logger.info(f"Tier1 LLM 更新：{tier1_result.get('updated', False)}")

        # Tier1 更新（仅统计信息）
        if enable_tier1_update and not enable_tier1_llm:
            self.update_tier1_persona(merged, dry_run=dry_run)

        return {
            "tier2": tier2_stats,
            "identity": identity_stats,
            "tier1": tier1_result,
            "summary": merged,
        }


def _arg_or_env(name: str, env_key: str, default: Optional[str] = None) -> Optional[str]:
    return name if name is not None else os.getenv(env_key, default)


def main():
    parser = argparse.ArgumentParser(description="夜间反思任务")
    parser.add_argument("--pg-host")
    parser.add_argument("--pg-port")
    parser.add_argument("--pg-user")
    parser.add_argument("--pg-password")
    parser.add_argument("--pg-dbname")
    parser.add_argument("--tier3-db-path")
    parser.add_argument("--user-id", default=None)
    parser.add_argument("--model", default="deepseek-chat")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--enable-tier1-update", action="store_true")
    parser.add_argument("--enable-tier1-llm", action="store_true",
                        help="使用 LLM 从 Tier2 提取 Tier1 核心画像")
    args = parser.parse_args()

    pg_config = {
        "host": _arg_or_env(args.pg_host, "PG_HOST"),
        "port": _arg_or_env(args.pg_port, "PG_PORT"),
        "user": _arg_or_env(args.pg_user, "PG_USER"),
        "password": _arg_or_env(args.pg_password, "PG_PASSWORD"),
        "dbname": _arg_or_env(args.pg_dbname, "PG_DBNAME"),
    }

    missing = [k for k, v in pg_config.items() if not v]
    if missing:
        raise SystemExit(f"缺少 PostgreSQL 参数: {missing}，请通过参数或环境变量提供")

    tier3_db_path = _arg_or_env(args.tier3_db_path, "TIER3_DB_PATH")
    if not tier3_db_path:
        raise SystemExit("缺少 tier3 db 路径，请使用 --tier3-db-path 或 TIER3_DB_PATH")

    user_id = _arg_or_env(args.user_id, "USER_ID", "default_user")

    reflector = NightReflector(
        pg_config=pg_config,
        tier3_db_path=tier3_db_path,
        user_id=user_id,
        model_name=args.model,
    )
    result = reflector.run(
        dry_run=args.dry_run,
        enable_tier1_update=args.enable_tier1_update,
        enable_tier1_llm=args.enable_tier1_llm,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
