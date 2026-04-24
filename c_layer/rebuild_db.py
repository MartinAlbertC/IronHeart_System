"""
C 层数据库重建脚本
清理并重建 PostgreSQL (Tier1 & Tier2) 和 SQLite (Tier3) 的所有表
"""
import sys
import psycopg
from pgvector.psycopg import register_vector
import sqlite3
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.logger import setup_logger
logger = setup_logger("c_layer")

from c_layer.config import PG_CONFIG, TIER3_DB_PATH


def init_db():
    # 1. 初始化 PostgreSQL (Tier 1 & 2)
    logger.info("正在清理并重建 PostgreSQL (Tier 1 & 2)...")
    try:
        conn = psycopg.connect(**PG_CONFIG, autocommit=True)
        cur = conn.cursor()
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        register_vector(conn)

        # 彻底删除所有旧表
        old_tables = [
            "tier1_core_persona", "tier1_persona",
            "tier2_light_graph_edges", "tier2_memories", "tier2_vector_memories"
        ]
        for table in old_tables:
            cur.execute(f"DROP TABLE IF EXISTS {table} CASCADE;")

        # --- 第一层表 (Tier 1) ---
        cur.execute("""
            CREATE TABLE tier1_persona (
                user_id VARCHAR PRIMARY KEY,
                system_prompt_base TEXT,
                critical_facts JSONB,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        logger.info("Tier 1: tier1_persona 已创建")

        # --- 第二层表 (Tier 2) ---
        cur.execute("""
            CREATE TABLE tier2_memories (
                memory_id VARCHAR PRIMARY KEY,
                resolved_entity_id VARCHAR,
                memory_text TEXT,
                embedding vector(1536),
                base_importance FLOAT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_accessed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                access_count INT
            );
        """)
        logger.info("Tier 2: tier2_memories 已创建")

        # --- 新增：反思配置表 ---
        cur.execute("""
            CREATE TABLE IF NOT EXISTS reflection_config (
                id            INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
                schedule_time TEXT NOT NULL DEFAULT '["00:00"]',
                today_count   INT NOT NULL DEFAULT 0,
                last_date     DATE,
                updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cur.execute("""
            INSERT INTO reflection_config (schedule_time) VALUES ('["00:00"]')
            ON CONFLICT DO NOTHING;
        """)
        logger.info("新增: reflection_config 已创建")

        # --- 新增：行动卡片表 ---
        cur.execute("""
            CREATE TABLE IF NOT EXISTS action_cards (
                action_id      VARCHAR(64) PRIMARY KEY,
                source         VARCHAR(16) NOT NULL DEFAULT 'pipeline',
                type           VARCHAR(32) NOT NULL,
                title          TEXT,
                content        TEXT,
                confidence     REAL DEFAULT 0.0,
                status         VARCHAR(16) NOT NULL DEFAULT 'pending',
                context_json   JSONB,
                opportunity_id VARCHAR(64),
                created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        logger.info("新增: action_cards 已创建")

        # --- 新增：反思历史表 ---
        cur.execute("""
            CREATE TABLE IF NOT EXISTS reflection_history (
                id              SERIAL PRIMARY KEY,
                triggered_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                trigger_type    VARCHAR(16) NOT NULL DEFAULT 'manual',
                tier3_events    INT DEFAULT 0,
                tier2_written   INT DEFAULT 0,
                labels_updated  INT DEFAULT 0,
                names_updated   INT DEFAULT 0,
                tier1_updated   BOOLEAN DEFAULT FALSE,
                duration_seconds INT DEFAULT 0
            );
        """)
        logger.info("新增: reflection_history 已创建")

        # --- 新增：视频任务表 ---
        cur.execute("""
            CREATE TABLE IF NOT EXISTS video_jobs (
                job_id       VARCHAR(64) PRIMARY KEY,
                status       VARCHAR(16) NOT NULL DEFAULT 'queued',
                file_path    TEXT,
                file_size_mb REAL,
                source       VARCHAR(32) DEFAULT 'camera',
                events_generated INT DEFAULT 0,
                created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                return_code  INT
            );
        """)
        logger.info("新增: video_jobs 已创建")

        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"PostgreSQL 出错: {e}")

    # 2. 初始化 SQLite (Tier 3)
    logger.info(f"正在清理并重建 SQLite (Tier 3)...")
    try:
        # 确保目录存在
        import os
        os.makedirs(os.path.dirname(TIER3_DB_PATH), exist_ok=True)

        conn = sqlite3.connect(TIER3_DB_PATH)
        cur = conn.cursor()
        cur.execute("DROP TABLE IF EXISTS tier3_events;")

        # --- 第三层表 (Tier 3) ---
        cur.execute("""
            CREATE TABLE tier3_events (
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
            );
        """)
        conn.commit()
        conn.close()
        logger.info("Tier 3: tier3_events 已创建")
    except Exception as e:
        logger.error(f"SQLite 出错: {e}")


if __name__ == "__main__":
    init_db()
    logger.info("数据库已严格按照字段对齐，冗余表已全部剔除。")
