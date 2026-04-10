"""C 层 HTTP API 服务器 - 供 E 层直接查询"""
import json
import sys
import os
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared.logger import setup_logger
logger = setup_logger("c_layer")

from c_layer.config import PG_CONFIG, TIER3_DB_PATH, API_HOST, API_PORT

try:
    from fastapi import FastAPI, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
    import uvicorn
except ImportError:
    logger.error("需要安装 fastapi 和 uvicorn: pip install fastapi uvicorn")
    raise

app = FastAPI(title="IranHeart C Layer API", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def _pg_conn():
    import psycopg
    return psycopg.connect(**PG_CONFIG, autocommit=True)


@app.get("/api/tier1/{user_id}")
async def get_tier1(user_id: str):
    """获取用户画像"""
    try:
        conn = _pg_conn()
        cur = conn.cursor()
        cur.execute("SELECT critical_facts, updated_at FROM tier1_persona WHERE user_id = %s", (user_id,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row:
            return {"user_id": user_id, "critical_facts": row[0], "updated_at": str(row[1])}
        raise HTTPException(404, f"User {user_id} not found")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/tier2/{entity_id}")
async def get_tier2(entity_id: str, limit: int = 10):
    """获取长期记忆"""
    try:
        conn = _pg_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT memory_id, memory_text, base_importance, created_at FROM tier2_memories WHERE resolved_entity_id = %s ORDER BY last_accessed_at DESC LIMIT %s",
            (entity_id, limit),
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [{"memory_id": r[0], "memory_text": r[1], "base_importance": r[2], "created_at": str(r[3])} for r in rows]
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/tier3/recent")
async def get_tier3_recent(limit: int = 20):
    """获取最近短期事件"""
    import sqlite3
    try:
        conn = sqlite3.connect(TIER3_DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM tier3_events ORDER BY start_ts DESC LIMIT ?", (limit,))
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/entity/{entity_id}")
async def get_entity(entity_id: str):
    """获取身份信息"""
    try:
        from c_layer.identity_store import IdentityStore
        store = IdentityStore(PG_CONFIG)
        entity = store.get_entity(entity_id)
        if entity:
            return entity
        raise HTTPException(404, f"Entity {entity_id} not found")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/entity/list")
async def list_entities():
    """列出所有身份"""
    try:
        from c_layer.identity_store import IdentityStore
        store = IdentityStore(PG_CONFIG)
        entities = store.list_all_entities()
        # 不返回 embedding 向量（太大）
        return [{k: v for k, v in e.items() if k not in ["face_embedding", "voice_embedding"]} for e in entities]
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/stats")
async def get_stats():
    """全局统计"""
    try:
        from c_layer.identity_store import IdentityStore
        store = IdentityStore(PG_CONFIG)
        return store.get_statistics()
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/health")
async def health():
    return {"status": "ok", "service": "c_layer_api"}


def run_api():
    logger.info(f"C层 API 启动: {API_HOST}:{API_PORT}")
    uvicorn.run(app, host=API_HOST, port=API_PORT, log_level="info")


if __name__ == "__main__":
    run_api()
