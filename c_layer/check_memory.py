"""快速查看三层记忆库内容"""
import sys, sqlite3
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from c_layer.config import PG_CONFIG, TIER3_DB_PATH

import psycopg


def check():
    # ── Tier1: 用户画像 (PostgreSQL) ──
    print("=" * 60)
    print("Tier1 - 用户画像 (PostgreSQL)")
    print("=" * 60)
    conn = psycopg.connect(**PG_CONFIG, autocommit=True)
    cur = conn.cursor()
    cur.execute("SELECT user_id, critical_facts, updated_at FROM tier1_persona")
    rows = cur.fetchall()
    if not rows:
        print("  (空)")
    for r in rows:
        print(f"  user_id: {r[0]}")
        print(f"  updated: {r[2]}")
        print(f"  facts:   {r[1]}")
    cur.close(); conn.close()

    # ── Tier2: 长期记忆 (PostgreSQL) ──
    print()
    print("=" * 60)
    print("Tier2 - 长期记忆 (PostgreSQL)")
    print("=" * 60)
    conn = psycopg.connect(**PG_CONFIG, autocommit=True)
    cur = conn.cursor()
    cur.execute("""
        SELECT resolved_entity_id, memory_id, base_importance, memory_text, created_at
        FROM tier2_memories ORDER BY last_accessed_at DESC
    """)
    rows = cur.fetchall()
    print(f"  共 {len(rows)} 条记忆")
    for i, r in enumerate(rows, 1):
        print(f"\n  [{i}] entity={r[0]} | importance={r[2]}")
        print(f"      id={r[1]} | created={r[4]}")
        print(f"      {r[3][:150]}{'...' if len(r[3]) > 150 else ''}")
    cur.close(); conn.close()

    # ── Tier3: 短期事件 (SQLite) ──
    print()
    print("=" * 60)
    print("Tier3 - 短期事件 (SQLite)")
    print("=" * 60)
    sq = sqlite3.connect(TIER3_DB_PATH)
    cur = sq.cursor()
    cur.execute("""
        SELECT resolved_entity_id, semantic_type, summary, start_ts
        FROM tier3_events ORDER BY start_ts DESC
    """)
    rows = cur.fetchall()
    print(f"  共 {len(rows)} 条事件")
    for i, r in enumerate(rows, 1):
        print(f"  [{i}] entity={r[0]} | type={r[1]} | time={r[3]}")
        print(f"      {r[2][:120]}{'...' if len(r[2]) > 120 else ''}")
    cur.close(); sq.close()


if __name__ == "__main__":
    check()
