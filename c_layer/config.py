"""C 层配置"""
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent

# PostgreSQL 配置
PG_CONFIG = {
    "host": os.getenv("PG_HOST", "localhost"),
    "port": os.getenv("PG_PORT", "5432"),
    "user": os.getenv("PG_USER", "ai_system"),
    "password": os.getenv("PG_PASSWORD", "secretpassword"),
    "dbname": os.getenv("PG_DBNAME", "memory_db"),
    "options": "-c timezone=Asia/Shanghai",
}

# Tier3 SQLite 路径
TIER3_DB_PATH = str(PROJECT_ROOT / "outputs" / "tier3_daily_events.db")

# MQ 配置
MQ_HOST = os.getenv("MQ_HOST", "localhost")
MQ_PORT = int(os.getenv("MQ_PORT", "6380"))

# HTTP API 配置
API_HOST = os.getenv("C_API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("C_API_PORT", "8000"))
