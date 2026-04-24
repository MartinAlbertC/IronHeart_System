"""行动卡片 API — /api/actions/*"""
import json
import asyncio
import sys
import threading
from pathlib import Path
from datetime import datetime
from typing import Dict, List

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from c_layer.c_online.gateway.response import ok, ApiError
from c_layer.config import PG_CONFIG
from shared.mq_client import MQClient

router = APIRouter()

# 内存中的待处理行动（MQ 订阅缓存）
_pending_actions: Dict[str, dict] = {}
# WebSocket 连接管理（用于实时推送）
_ws_connections: List[WebSocket] = []


def _pg_conn():
    import psycopg
    return psycopg.connect(**PG_CONFIG, autocommit=True)


def _save_to_db(action: dict):
    """持久化行动卡片到数据库"""
    try:
        import psycopg
        conn = psycopg.connect(**PG_CONFIG, autocommit=True)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO action_cards (action_id, source, type, title, content, confidence, status, context_json, opportunity_id, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (action_id) DO NOTHING
        """, (
            action.get("action_id"),
            action.get("source", "pipeline"),
            action.get("type", "task"),
            action.get("title", ""),
            action.get("content", ""),
            action.get("confidence", 0.0),
            action.get("status", "pending"),
            json.dumps(action.get("context", {}), ensure_ascii=False),
            action.get("opportunity_id"),
            action.get("created_at", datetime.now().isoformat()),
        ))
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[actions] 保存到数据库失败: {e}")


def _on_e_result(msg: dict):
    """收到 E 层结果，存入内存和数据库"""
    action_id = msg.get("action_id")
    if not action_id:
        return
    _pending_actions[action_id] = msg
    _save_to_db(msg)

    # WebSocket 实时推送
    for ws in _ws_connections[:]:
        try:
            import asyncio
            asyncio.get_event_loop().create_task(ws.send_json({"type": "new_action", "data": msg}))
        except Exception:
            pass


def start_e_results_subscriber():
    """启动 E 层结果订阅"""
    mq = MQClient()
    mq.subscribe("e_results", _on_e_result)
    print("[actions] e_results 订阅已启动")


@router.get("/api/actions")
async def get_actions(status: str = "pending", source: str = "all",
                      page: int = 1, page_size: int = 20):
    """查询行动卡片"""
    import psycopg
    conn = _pg_conn()
    cur = conn.cursor()

    where_clauses = []
    params = []
    if status != "all":
        where_clauses.append("status = %s")
        params.append(status)
    if source != "all":
        where_clauses.append("source = %s")
        params.append(source)

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    cur.execute(f"SELECT COUNT(*) FROM action_cards {where_sql}", params)
    total = cur.fetchone()[0]

    offset = (page - 1) * page_size
    cur.execute(f"""
        SELECT action_id, source, type, title, content, confidence, status, context_json, created_at
        FROM action_cards {where_sql}
        ORDER BY created_at DESC LIMIT %s OFFSET %s
    """, params + [page_size, offset])
    rows = cur.fetchall()
    cur.close()
    conn.close()

    actions = [{
        "id": r[0],
        "source": r[1],
        "type": r[2],
        "title": r[3],
        "content": r[4],
        "confidence": r[5],
        "status": r[6],
        "context": r[7] if isinstance(r[7], dict) else (json.loads(r[7]) if r[7] else {}),
        "created_at": str(r[8]) if r[8] else None,
    } for r in rows]

    return ok({"total": total, "actions": actions})


@router.put("/api/actions/{action_id}")
async def update_action(action_id: str, body: dict):
    """确认/拒绝行动卡片"""
    decision = body.get("decision")
    if decision not in ("confirmed", "rejected"):
        raise ApiError(40001, "decision 必须为 confirmed 或 rejected")

    import psycopg
    conn = _pg_conn()
    cur = conn.cursor()

    cur.execute("SELECT action_id FROM action_cards WHERE action_id = %s", (action_id,))
    if not cur.fetchone():
        cur.close()
        conn.close()
        raise ApiError(40401, "行动卡片不存在")

    now = datetime.now().isoformat()
    cur.execute("UPDATE action_cards SET status = %s, updated_at = %s WHERE action_id = %s",
                (decision, now, action_id))
    cur.close()
    conn.close()

    return ok({"id": action_id, "status": decision, "executed_at": now})


@router.websocket("/api/actions/ws")
async def actions_ws(ws: WebSocket):
    """WebSocket 实时推送新行动卡片"""
    await ws.accept()
    _ws_connections.append(ws)
    try:
        while True:
            try:
                msg = await asyncio.wait_for(ws.receive_json(), timeout=30.0)
                if msg.get("type") == "ping":
                    await ws.send_json({"type": "pong"})
            except asyncio.TimeoutError:
                pass
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        if ws in _ws_connections:
            _ws_connections.remove(ws)
