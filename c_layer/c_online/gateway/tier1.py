"""Tier1 用户画像读写扩展 — GET/PUT /api/tier1/{user_id}"""
import json
import uuid
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional

from fastapi import APIRouter

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from c_layer.c_online.gateway.response import ok, ApiError
from c_layer.config import PG_CONFIG

router = APIRouter()

CATEGORIES = ["preferences", "habits", "health_constraints", "core_goals", "relationships"]


def _pg_conn():
    import psycopg
    return psycopg.connect(**PG_CONFIG, autocommit=True)


def _normalize_facts(raw_facts: dict) -> dict:
    """将旧格式（纯字符串列表）转换为新格式（带 source 标签）"""
    result = {}
    for category in CATEGORIES:
        items = raw_facts.get(category, [])
        normalized = []
        for item in items:
            if isinstance(item, str):
                normalized.append({
                    "id": f"sys_{hash(item) & 0xFFFFFF:06x}",
                    "text": item,
                    "source": "system"
                })
            elif isinstance(item, dict):
                if "id" not in item:
                    item["id"] = f"sys_{hash(item.get('text', '')) & 0xFFFFFF:06x}"
                if "source" not in item:
                    item["source"] = "system"
                normalized.append(item)
        result[category] = normalized
    return result


def _read_tier1(user_id: str) -> Optional[dict]:
    """读取 Tier1 画像"""
    conn = _pg_conn()
    cur = conn.cursor()
    cur.execute("SELECT critical_facts, updated_at FROM tier1_persona WHERE user_id = %s", (user_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if row:
        facts = _normalize_facts(row[0] if row[0] else {})
        return {"user_id": user_id, "critical_facts": facts, "updated_at": str(row[1])}
    return None


@router.get("/api/tier1/{user_id}")
async def get_tier1(user_id: str):
    """获取用户画像"""
    result = _read_tier1(user_id)
    if not result:
        # 返回空画像而不是 404（前端首次访问时）
        empty_facts = {cat: [] for cat in CATEGORIES}
        return ok({"user_id": user_id, "critical_facts": empty_facts, "updated_at": None})
    return ok(result)


@router.put("/api/tier1/{user_id}")
async def update_tier1(user_id: str, body: dict):
    """更新用户画像（只操作 source=user 的条目）"""
    category = body.get("category")
    action = body.get("action")
    item = body.get("item")

    if category not in CATEGORIES:
        raise ApiError(40001, f"无效分类: {category}")
    if action not in ("add", "update", "delete"):
        raise ApiError(40001, f"无效操作: {action}")
    if not item or not item.get("text") and action != "delete":
        raise ApiError(40001, "缺少 item.text")

    conn = _pg_conn()
    cur = conn.cursor()

    # 读取现有 facts
    cur.execute("SELECT critical_facts FROM tier1_persona WHERE user_id = %s", (user_id,))
    row = cur.fetchone()
    raw_facts = row[0] if row else {}
    facts = _normalize_facts(raw_facts)
    items = facts.get(category, [])

    if action == "add":
        new_item = {
            "id": f"user_{uuid.uuid4().hex[:8]}",
            "text": item["text"],
            "source": "user"
        }
        items.append(new_item)
    elif action == "update":
        target_id = item.get("id")
        if not target_id:
            raise ApiError(40001, "update 操作需要 item.id")
        found = False
        for i, existing in enumerate(items):
            if existing.get("id") == target_id:
                items[i] = {**existing, "text": item["text"]}
                found = True
                break
        if not found:
            raise ApiError(40401, f"条目 {target_id} 不存在")
    elif action == "delete":
        target_id = item.get("id")
        if not target_id:
            raise ApiError(40001, "delete 操作需要 item.id")
        original_len = len(items)
        items = [i for i in items if i.get("id") != target_id]
        if len(items) == original_len:
            raise ApiError(40401, f"条目 {target_id} 不存在")

    facts[category] = items

    # 写回数据库
    cur.execute("""
        INSERT INTO tier1_persona (user_id, system_prompt_base, critical_facts)
        VALUES (%s, '', %s)
        ON CONFLICT (user_id) DO UPDATE SET critical_facts = EXCLUDED.critical_facts
    """, (user_id, json.dumps(facts, ensure_ascii=False)))
    conn.commit()
    cur.close()
    conn.close()

    return ok({"user_id": user_id, "critical_facts": facts})
