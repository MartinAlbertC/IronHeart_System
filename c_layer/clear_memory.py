#!/usr/bin/env python3
"""清空三层记忆库（Tier1 + Tier2 + Tier3 + 身份表）"""
import sys
import sqlite3
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from c_layer.config import PG_CONFIG, TIER3_DB_PATH

import psycopg


def clear():
    # PostgreSQL: Tier1, Tier2, 身份表
    conn = psycopg.connect(**PG_CONFIG, autocommit=True)
    cur = conn.cursor()
    cur.execute("DELETE FROM tier1_persona")
    t1 = cur.rowcount
    cur.execute("DELETE FROM tier2_memories")
    t2 = cur.rowcount
    cur.execute("DELETE FROM resolved_entities")
    ent = cur.rowcount
    cur.close(); conn.close()

    # SQLite: Tier3
    sq = sqlite3.connect(TIER3_DB_PATH)
    cur = sq.cursor()
    cur.execute("DELETE FROM tier3_events")
    t3 = cur.rowcount
    sq.commit(); cur.close(); sq.close()

    print(f"已清空: Tier1={t1}条 | Tier2={t2}条 | Tier3={t3}条 | 身份表={ent}条")


if __name__ == "__main__":
    clear()
