"""
夜间反思模块
1) 提纯 Tier3 事件并写入 Tier2
2) 结合 Tier3 + 身份表更新 identity labels/name（LLM 参与）
3) 谨慎更新 Tier1 核心画像
"""

import argparse
import hashlib
import json
import os
import sqlite3
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Any, Optional

import psycopg

try:
    from .identity_store import IdentityStore
except ImportError:
    try:
        from models.identity_store import IdentityStore
    except Exception:
        from identity_store import IdentityStore


class NightReflector:
    def __init__(
        self,
        pg_config: Dict[str, str],
        tier3_db_path: str,
        user_id: str,
        model_name: str = "glm-4-flash",
    ):
        self.pg_config = pg_config
        self.tier3_db_path = tier3_db_path
        self.user_id = user_id
        self.model_name = model_name
        self.identity_store = IdentityStore(pg_config)

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

    def _topic_key(self, event: Dict[str, Any]) -> str:
        st = (event.get("semantic_type") or "unknown").strip().lower()
        sm = (event.get("summary") or "").strip().lower()
        digest = hashlib.md5(sm.encode("utf-8")).hexdigest()[:8]
        return f"{st}:{digest}"

    def _importance(self, event: Dict[str, Any], duplicate_count: int) -> float:
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
        """提纯/去冲突后写入 tier2_memories。"""
        grouped = defaultdict(list)
        for e in events:
            entity = e.get("resolved_entity_id") or "unknown"
            grouped[(entity, self._topic_key(e))].append(e)

        prepared = []
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

            prepared.append(
                {
                    "memory_id": memory_id,
                    "resolved_entity_id": entity,
                    "memory_text": memory_text,
                    "base_importance": importance,
                    "created_at": base_ts,
                }
            )

        if dry_run:
            return {
                "input_events": len(events),
                "after_merge": len(prepared),
                "written": 0,
            }

        conn = self._pg_conn()
        cur = conn.cursor()
        written = 0
        try:
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
            "written": written,
        }

    def _call_llm_for_identity(
        self,
        entity_id: str,
        current_labels: Optional[str],
        snippets: List[str],
    ) -> Dict[str, Any]:
        """调用 BigModel(OpenAI 风格) 生成 identity 更新建议。"""
        api_key = os.getenv("BIGMODEL_API_KEY", "").strip() or os.getenv("ZHIPU_API_KEY", "").strip()
        base_url = os.getenv("BIGMODEL_BASE_URL", "https://open.bigmodel.cn/api/paas/v4").rstrip("/")
        model = os.getenv("BIGMODEL_MODEL", self.model_name or "glm-4-flash")

        if not api_key:
            return {
                "entity_id": entity_id,
                "proposed_name": None,
                "proposed_labels": current_labels or "",
                "confidence": 0.0,
                "reason": "BIGMODEL_API_KEY/ZHIPU_API_KEY 未设置，跳过自动 identity 更新",
            }

        try:
            payload = {
                "model": model,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "你是 identity 更新建议器。只输出一个 JSON 对象，"
                            "字段必须包含 entity_id, proposed_name, proposed_labels, confidence, reason。"
                            "confidence 取 0 到 1 之间的小数。不要输出 JSON 以外内容。"
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "entity_id": entity_id,
                                "current_labels": current_labels or "",
                                "evidence": snippets[:20],
                                "task": "基于证据返回 JSON 建议",
                            },
                            ensure_ascii=False,
                        ),
                    },
                ],
                "temperature": 0,
                "stream": False,
            }

            req = urllib.request.Request(
                url=f"{base_url}/chat/completions",
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
                method="POST",
            )

            with urllib.request.urlopen(req, timeout=45) as resp:
                raw = resp.read().decode("utf-8")

            body = json.loads(raw)
            text = (
                body.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
            )

            start = text.find("{")
            end = text.rfind("}")
            if start == -1 or end == -1:
                raise ValueError(f"LLM 未返回 JSON，原始内容: {text[:300]}")

            data = json.loads(text[start : end + 1])
            data.setdefault("entity_id", entity_id)
            data.setdefault("proposed_name", None)
            data.setdefault("proposed_labels", current_labels or "")
            data.setdefault("confidence", 0.0)
            data.setdefault("reason", "")
            return data

        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="ignore") if hasattr(e, "read") else str(e)
            return {
                "entity_id": entity_id,
                "proposed_name": None,
                "proposed_labels": current_labels or "",
                "confidence": 0.0,
                "reason": f"LLM HTTP 错误: {e.code} {detail[:300]}",
            }
        except Exception as e:
            return {
                "entity_id": entity_id,
                "proposed_name": None,
                "proposed_labels": current_labels or "",
                "confidence": 0.0,
                "reason": f"LLM 调用失败: {e}",
            }

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

    def run(self, dry_run: bool = False, enable_tier1_update: bool = False) -> Dict[str, Any]:
        events = self.load_tier3_events()
        tier2_stats = self.refine_to_tier2(events, dry_run=dry_run)
        identity_stats = self.update_identity_with_llm(events, dry_run=dry_run)

        merged = {
            "tier3_events": len(events),
            "tier2_written": tier2_stats.get("written", 0),
            "labels_updated": identity_stats.get("labels_updated", 0),
            "names_updated": identity_stats.get("names_updated", 0),
            "dry_run": dry_run,
        }

        if enable_tier1_update:
            self.update_tier1_persona(merged, dry_run=dry_run)

        return {
            "tier2": tier2_stats,
            "identity": identity_stats,
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
    parser.add_argument("--model", default=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--enable-tier1-update", action="store_true")
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
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
