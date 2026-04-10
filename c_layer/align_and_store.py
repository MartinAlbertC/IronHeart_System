"""
身份对齐和存储模块
从 B.jsonl 读取新事件，进行身份对齐，存储到 tier3
"""

import json
import sqlite3
from typing import Dict, List, Optional
from .identity_store import IdentityStore


class EventAligner:
    """事件身份对齐器"""

    def __init__(self, pg_config: Dict[str, str], tier3_db_path: str):
        """
        初始化对齐器

        Args:
            pg_config: PostgreSQL 配置
            tier3_db_path: tier3 SQLite 数据库路径
        """
        self.identity_store = IdentityStore(pg_config)
        self.tier3_db_path = tier3_db_path
        self._ensure_tier3_tables()

    def _ensure_tier3_tables(self):
        """确保 tier3 表存在"""
        conn = sqlite3.connect(self.tier3_db_path)
        cur = conn.cursor()

        # 创建事件表（不含向量）
        cur.execute("""
            CREATE TABLE IF NOT EXISTS events (
                event_id TEXT PRIMARY KEY,
                resolved_entity_id TEXT,
                timestamp TEXT,
                event_type TEXT,
                content TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 创建"遇到新人事件"表（含向量）
        cur.execute("""
            CREATE TABLE IF NOT EXISTS new_person_events (
                event_id TEXT PRIMARY KEY,
                temp_entity_id TEXT,
                resolved_entity_id TEXT,
                face_embedding TEXT,
                voice_embedding TEXT,
                timestamp TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.commit()
        conn.close()
        print("✅ tier3 表已初始化")

    def align_and_store_event(self, event: Dict) -> Dict:
        """
        对单个事件进行身份对齐并存储

        Args:
            event: B层事件

        Returns:
            处理结果字典
        """
        face_emb = event.get('face_embedding')
        voice_emb = event.get('voice_embedding')

        # 身份匹配
        resolved_id, is_new = self.identity_store.match_or_create(
            face_embedding=face_emb,
            voice_embedding=voice_emb
        )

        # 从B层事件提取统一字段（兼容两种字段命名）
        event_id = event.get('semantic_event_id') or event.get('event_id')
        temp_id = event.get('temp_alias_id') or event.get('temp_entity_id', resolved_id)
        timestamp = (event.get('time', {}).get('start_ts')
                     if isinstance(event.get('time'), dict)
                     else event.get('timestamp'))
        event_type = event.get('semantic_type') or event.get('event_type')

        # 存储到 tier3
        conn = sqlite3.connect(self.tier3_db_path)
        cur = conn.cursor()

        if is_new:
            # 新人：存储"遇到新人事件"（含向量）
            cur.execute("""
                INSERT INTO new_person_events
                (event_id, temp_entity_id, resolved_entity_id, face_embedding, voice_embedding, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                event_id,
                temp_id,
                resolved_id,
                json.dumps(face_emb) if face_emb else None,
                json.dumps(voice_emb) if voice_emb else None,
                timestamp
            ))

        # 存储普通事件（不含向量）
        cur.execute("""
            INSERT OR REPLACE INTO events
            (event_id, resolved_entity_id, timestamp, event_type, content)
            VALUES (?, ?, ?, ?, ?)
        """, (
            event_id,
            resolved_id,
            timestamp,
            event_type,
            json.dumps({k: v for k, v in event.items()
                       if k not in ['face_embedding', 'voice_embedding']})
        ))

        conn.commit()
        conn.close()

        return {
            'event_id': event_id,
            'resolved_entity_id': resolved_id,
            'is_new_person': is_new
        }

    def process_b_jsonl(self, b_jsonl_path: str) -> List[Dict]:
        """
        处理 B.jsonl 文件中的所有事件

        Args:
            b_jsonl_path: B.jsonl 文件路径

        Returns:
            处理结果列表
        """
        results = []

        with open(b_jsonl_path, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    event = json.loads(line)
                    result = self.align_and_store_event(event)
                    results.append(result)

        return results


if __name__ == '__main__':
    from pathlib import Path

    # 配置
    pg_config = {
        'host': 'localhost',
        'port': '5432',
        'user': 'ai_system',
        'password': 'secretpassword',
        'dbname': 'memory_db'
    }

    base_dir = Path(__file__).parent.parent
    tier3_db_path = str(base_dir / 'tier3_daily_events.db')
    b_jsonl_path = str(base_dir / 'events' / 'B.jsonl')

    # 执行对齐
    aligner = EventAligner(pg_config, tier3_db_path)
    results = aligner.process_b_jsonl(b_jsonl_path)

    # 统计
    new_persons = sum(1 for r in results if r['is_new_person'])
    print(f"\n处理完成：")
    print(f"  总事件数：{len(results)}")
    print(f"  新人数：{new_persons}")
    print(f"  匹配到现有身份：{len(results) - new_persons}")
