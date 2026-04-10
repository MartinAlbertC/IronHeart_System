"""
C 层身份存储模块
负责管理 resolved_entities 表，用于存储和匹配人物身份特征

表结构:
- resolved_entity_id: 人物唯一标识 (如 "王老师", "alias_A")
- face_embedding: 人脸特征向量 (pgvector 1024 维)
- face_embedding_count: 人脸特征更新次数
- voice_embedding: 声音特征向量 (pgvector 1024 维)
- voice_embedding_count: 声音特征更新次数
- created_at: 首次创建时间
- updated_at: 最后更新时间
"""

import json
import logging
import numpy as np
from typing import Dict, List, Optional, Tuple
from datetime import datetime

logger = logging.getLogger("c_layer.identity_store")

try:
    import psycopg
    from pgvector.psycopg import register_vector
    _PG_AVAILABLE = True
except ImportError:
    _PG_AVAILABLE = False


class IdentityStore:
    """身份存储管理类，处理人物特征的增删查改和相似度匹配"""

    # 相似度阈值
    FACE_THRESHOLD = 0.75  # 人脸匹配阈值
    VOICE_THRESHOLD = 0.70  # 声音匹配阈值

    def __init__(self, pg_config: Dict[str, str]):
        """
        初始化身份存储

        Args:
            pg_config: PostgreSQL 配置字典，包含 host, port, user, password, dbname
        """
        self.pg_config = pg_config
        self._db_available = False
        self._degraded_counter = 0  # 降级模式下的自增计数器

        if not _PG_AVAILABLE:
            logger.warning("psycopg / pgvector 未安装，IdentityStore 运行于降级模式（无法持久化身份数据）")
            return

        try:
            self._ensure_table()
            self._db_available = True
        except Exception as e:
            logger.warning("PostgreSQL 不可用 (%s)，IdentityStore 运行于降级模式（无法持久化身份数据）", e)

    def _get_connection(self):
        """获取数据库连接"""
        if not self._db_available:
            raise RuntimeError("PostgreSQL 不可用，IdentityStore 处于降级模式")
        conn = psycopg.connect(**self.pg_config, autocommit=True)
        register_vector(conn)
        return conn

    def _ensure_table(self):
        """确保身份表存在（直接连接，不走 _get_connection 守卫）"""
        conn = psycopg.connect(**self.pg_config, autocommit=True)
        register_vector(conn)
        cur = conn.cursor()

        # 创建 pgvector 扩展
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        register_vector(conn)

        # 创建身份表
        cur.execute("""
            CREATE TABLE IF NOT EXISTS resolved_entities (
                resolved_entity_id VARCHAR(255) PRIMARY KEY,
                face_embedding vector(512),
                face_embedding_count INTEGER DEFAULT 0,
                voice_embedding vector(256),
                voice_embedding_count INTEGER DEFAULT 0,
                labels TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # 创建向量索引加速相似度搜索
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_face_embedding
            ON resolved_entities USING ivfflat (face_embedding vector_cosine_ops)
            WITH (lists = 100);
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_voice_embedding
            ON resolved_entities USING ivfflat (voice_embedding vector_cosine_ops)
            WITH (lists = 100);
        """)

        cur.close()
        conn.close()
        logger.info("resolved_entities 表已初始化")

    def _parse_embedding(self, embedding):
        """解析向量数据，支持 np.str_('[...]') 格式"""
        if embedding is None:
            return None
        if isinstance(embedding, list):
            return embedding
        if isinstance(embedding, str):
            # 处理 np.str_('[...]') 格式
            if embedding.startswith("np.str_('") and embedding.endswith("')"):
                embedding = embedding[9:-2]
            # 解析数组字符串
            if embedding.startswith('[') and embedding.endswith(']'):
                return json.loads(embedding)
        return embedding

    def _cosine_similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        """计算两个向量的余弦相似度"""
        if a is None or b is None:
            return 0.0
        norm_a, norm_b = np.linalg.norm(a), np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(np.dot(a, b) / (norm_a * norm_b))

    def _embedding_to_list(self, embedding: np.ndarray) -> List[float]:
        """将 numpy 数组转换为列表"""
        return embedding.tolist()

    def match_or_create(
        self,
        face_embedding: Optional[List[float]] = None,
        voice_embedding: Optional[List[float]] = None
    ) -> Tuple[str, bool]:
        """
        根据人脸或声音特征匹配或创建身份

        Args:
            face_embedding: 人脸特征向量 (1024 维)
            voice_embedding: 声音特征向量 (1024 维)

        Returns:
            (resolved_entity_id, is_new_match): 身份 ID 和是否为新匹配
        """
        # 降级模式：不查数据库，用自增计数器生成 entity_id
        if not self._db_available:
            self._degraded_counter += 1
            new_id = f"entity_{self._degraded_counter:04d}"
            logger.debug("降级模式: 生成临时 entity_id=%s", new_id)
            return new_id, True

        # 解析向量数据
        face_embedding = self._parse_embedding(face_embedding)
        voice_embedding = self._parse_embedding(voice_embedding)

        conn = self._get_connection()
        cur = conn.cursor()

        best_match_id = None
        best_score = 0.0
        match_type = None  # 'face' or 'voice'

        # 优先使用人脸匹配
        if face_embedding:
            face_vec = np.array(face_embedding)

            # 查询所有有 face_embedding 的记录
            cur.execute("""
                SELECT resolved_entity_id, face_embedding
                FROM resolved_entities
                WHERE face_embedding IS NOT NULL
            """)

            for row in cur.fetchall():
                entity_id, db_face_emb = row
                if db_face_emb is not None:
                    db_face_array = np.array(db_face_emb)
                    score = self._cosine_similarity(face_vec, db_face_array)
                    if score > best_score:
                        best_score = score
                        best_match_id = entity_id
                        match_type = 'face'

            # 如果人脸匹配成功，更新该记录
            if best_score >= self.FACE_THRESHOLD and best_match_id:
                self._update_entity(cur, best_match_id, face_embedding, 'face')
                cur.close()
                conn.close()
                return best_match_id, False

        # 人脸未匹配，尝试声音匹配
        if voice_embedding and (best_score < self.FACE_THRESHOLD or not face_embedding):
            voice_vec = np.array(voice_embedding)

            cur.execute("""
                SELECT resolved_entity_id, voice_embedding
                FROM resolved_entities
                WHERE voice_embedding IS NOT NULL
            """)

            for row in cur.fetchall():
                entity_id, db_voice_emb = row
                if db_voice_emb is not None:
                    db_voice_array = np.array(db_voice_emb)
                    score = self._cosine_similarity(voice_vec, db_voice_array)
                    if score > best_score:
                        best_score = score
                        best_match_id = entity_id
                        match_type = 'voice'

            # 如果声音匹配成功，更新该记录
            if best_score >= self.VOICE_THRESHOLD and best_match_id:
                self._update_entity(cur, best_match_id, voice_embedding, 'voice')
                cur.close()
                conn.close()
                return best_match_id, False

        # 未匹配到，创建新身份
        new_id = self._create_entity(cur, face_embedding, voice_embedding)
        cur.close()
        conn.close()
        return new_id, True

    def _update_entity(
        self,
        cur,
        entity_id: str,
        embedding: List[float],
        modality: str
    ):
        """
        更新现有身份的特征 (增量平均)

        Args:
            cur: 数据库游标
            entity_id: 身份 ID
            embedding: 新的特征向量
            modality: 'face' 或 'voice'
        """
        # 确保embedding是numpy数组
        if isinstance(embedding, list):
            embedding = np.array(embedding)
        elif not isinstance(embedding, np.ndarray):
            embedding = np.array(list(embedding))

        # 读取当前的embedding和count
        if modality == 'face':
            cur.execute("""
                SELECT face_embedding, face_embedding_count
                FROM resolved_entities
                WHERE resolved_entity_id = %s
            """, (entity_id,))
        else:
            cur.execute("""
                SELECT voice_embedding, voice_embedding_count
                FROM resolved_entities
                WHERE resolved_entity_id = %s
            """, (entity_id,))

        row = cur.fetchone()
        if not row:
            return

        old_embedding, old_count = row
        old_embedding = np.array(old_embedding) if old_embedding is not None else None

        # 在Python中计算增量平均
        if old_embedding is not None and old_count > 0:
            new_embedding = (old_embedding * old_count + embedding) / (old_count + 1)
        else:
            new_embedding = embedding

        new_embedding_list = new_embedding.tolist()

        # 更新数据库
        if modality == 'face':
            cur.execute("""
                UPDATE resolved_entities
                SET
                    face_embedding = %s::vector(512),
                    face_embedding_count = face_embedding_count + 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE resolved_entity_id = %s
            """, (new_embedding_list, entity_id))
        else:
            cur.execute("""
                UPDATE resolved_entities
                SET
                    voice_embedding = %s::vector(256),
                    voice_embedding_count = voice_embedding_count + 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE resolved_entity_id = %s
            """, (new_embedding_list, entity_id))

    def _create_entity(
        self,
        cur,
        face_embedding: Optional[List[float]] = None,
        voice_embedding: Optional[List[float]] = None
    ) -> str:
        """
        创建新身份记录

        Args:
            cur: 数据库游标
            face_embedding: 人脸特征向量
            voice_embedding: 声音特征向量

        Returns:
            新生成的身份 ID
        """
        # 生成新 ID (先查询最大序号)
        cur.execute("SELECT COUNT(*) FROM resolved_entities")
        next_num = cur.fetchone()[0] + 1
        new_id = f"entity_{next_num:04d}"

        # 确保embedding是列表类型
        if face_embedding:
            if isinstance(face_embedding, np.ndarray):
                face_embedding = face_embedding.tolist()
            elif not isinstance(face_embedding, list):
                face_embedding = list(face_embedding)

        if voice_embedding:
            if isinstance(voice_embedding, np.ndarray):
                voice_embedding = voice_embedding.tolist()
            elif not isinstance(voice_embedding, list):
                voice_embedding = list(voice_embedding)

        # 构造参数列表
        params = [new_id]

        if face_embedding:
            params.extend([face_embedding, 1])
        else:
            params.append(0)

        if voice_embedding:
            params.extend([voice_embedding, 1])
        else:
            params.append(0)

        face_emb_sql = "%s::vector(512)" if face_embedding else "NULL"
        voice_emb_sql = "%s::vector(256)" if voice_embedding else "NULL"

        cur.execute(f"""
            INSERT INTO resolved_entities (
                resolved_entity_id,
                face_embedding,
                face_embedding_count,
                voice_embedding,
                voice_embedding_count,
                created_at,
                updated_at
            ) VALUES (
                %s,
                {face_emb_sql},
                %s,
                {voice_emb_sql},
                %s,
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP
            )
        """, params)

        return new_id

    def get_entity(self, entity_id: str) -> Optional[Dict]:
        """
        获取指定身份的详细信息

        Args:
            entity_id: 身份 ID

        Returns:
            身份信息字典，包含 face_embedding, voice_embedding 等
        """
        if not self._db_available:
            return None

        conn = self._get_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT
                resolved_entity_id,
                face_embedding,
                face_embedding_count,
                voice_embedding,
                voice_embedding_count,
                labels,
                created_at,
                updated_at
            FROM resolved_entities
            WHERE resolved_entity_id = %s
        """, (entity_id,))

        row = cur.fetchone()
        cur.close()
        conn.close()

        if row:
            return {
                'resolved_entity_id': row[0],
                'face_embedding': row[1],
                'face_embedding_count': row[2],
                'voice_embedding': row[3],
                'voice_embedding_count': row[4],
                'labels': row[5],
                'created_at': row[6].isoformat() if row[6] else None,
                'updated_at': row[7].isoformat() if row[7] else None
            }
        return None

    def list_all_entities(self) -> List[Dict]:
        """
        获取所有身份记录

        Returns:
            身份信息列表
        """
        if not self._db_available:
            return []

        conn = self._get_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT
                resolved_entity_id,
                face_embedding,
                face_embedding_count,
                voice_embedding,
                voice_embedding_count,
                labels,
                created_at,
                updated_at
            FROM resolved_entities
            ORDER BY created_at
        """)

        entities = []
        for row in cur.fetchall():
            entities.append({
                'resolved_entity_id': row[0],
                'face_embedding': row[1],
                'face_embedding_count': row[2],
                'voice_embedding': row[3],
                'voice_embedding_count': row[4],
                'labels': row[5],
                'created_at': row[6].isoformat() if row[6] else None,
                'updated_at': row[7].isoformat() if row[7] else None
            })

        cur.close()
        conn.close()
        return entities

    def update_entity_name(self, old_id: str, new_name: str) -> bool:
        """
        更新身份名称 (用于夜间反思后将 alias 改为真实名称如 "王老师")

        Args:
            old_id: 原身份 ID (如 "entity_0001")
            new_name: 新名称 (如 "王老师")

        Returns:
            是否更新成功
        """
        if not self._db_available:
            return False

        conn = self._get_connection()
        cur = conn.cursor()

        try:
            cur.execute("""
                UPDATE resolved_entities
                SET
                    resolved_entity_id = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE resolved_entity_id = %s
            """, (new_name, old_id))
            conn.commit()
            return True
        except Exception as e:
            logger.warning("更新身份名称失败: %s", e)
            conn.rollback()
            return False
        finally:
            cur.close()
            conn.close()

    def get_statistics(self) -> Dict:
        """获取身份表统计信息"""
        if not self._db_available:
            return {
                'total_entities': 0,
                'with_face_embedding': 0,
                'with_voice_embedding': 0,
                'with_both': 0,
            }

        conn = self._get_connection()
        cur = conn.cursor()

        cur.execute("SELECT COUNT(*) FROM resolved_entities")
        total_count = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM resolved_entities WHERE face_embedding IS NOT NULL")
        with_face = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM resolved_entities WHERE voice_embedding IS NOT NULL")
        with_voice = cur.fetchone()[0]

        cur.close()
        conn.close()

        return {
            'total_entities': total_count,
            'with_face_embedding': with_face,
            'with_voice_embedding': with_voice,
            'with_both': total_count - (with_face + with_voice - total_count)
        }

    def update_labels(self, entity_id: str, labels: str) -> bool:
        """
        更新身份标签 (用于夜间反思)

        Args:
            entity_id: 身份 ID
            labels: 标签内容 (如 "老师、中年")

        Returns:
            是否更新成功
        """
        if not self._db_available:
            return False

        conn = self._get_connection()
        cur = conn.cursor()

        try:
            cur.execute("""
                UPDATE resolved_entities
                SET labels = %s, updated_at = CURRENT_TIMESTAMP
                WHERE resolved_entity_id = %s
            """, (labels, entity_id))
            conn.commit()
            return True
        except Exception as e:
            logger.warning("更新标签失败: %s", e)
            conn.rollback()
            return False
        finally:
            cur.close()
            conn.close()

    def rename_entity_everywhere(self, old_id: str, new_id: str, tier3_db_path: Optional[str] = None) -> bool:
        """
        跨表更新实体ID：resolved_entities + tier2_memories + tier3(SQLite 可选)
        """
        if not self._db_available:
            return False

        pg_conn = self._get_connection()
        pg_cur = pg_conn.cursor()

        sqlite_conn = None
        sqlite_cur = None
        try:
            # PostgreSQL: identity + tier2
            pg_cur.execute(
                """
                UPDATE resolved_entities
                SET resolved_entity_id = %s, updated_at = CURRENT_TIMESTAMP
                WHERE resolved_entity_id = %s
                """,
                (new_id, old_id),
            )

            pg_cur.execute(
                """
                UPDATE tier2_memories
                SET resolved_entity_id = %s
                WHERE resolved_entity_id = %s
                """,
                (new_id, old_id),
            )

            # SQLite tier3 (optional)
            if tier3_db_path:
                import sqlite3

                sqlite_conn = sqlite3.connect(tier3_db_path)
                sqlite_cur = sqlite_conn.cursor()
                sqlite_cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = {r[0] for r in sqlite_cur.fetchall()}

                if "tier3_events" in tables:
                    sqlite_cur.execute(
                        "UPDATE tier3_events SET resolved_entity_id = ? WHERE resolved_entity_id = ?",
                        (new_id, old_id),
                    )
                if "events" in tables:
                    sqlite_cur.execute(
                        "UPDATE events SET resolved_entity_id = ? WHERE resolved_entity_id = ?",
                        (new_id, old_id),
                    )
                if "new_person_events" in tables:
                    sqlite_cur.execute(
                        "UPDATE new_person_events SET resolved_entity_id = ? WHERE resolved_entity_id = ?",
                        (new_id, old_id),
                    )

            pg_conn.commit()
            if sqlite_conn:
                sqlite_conn.commit()
            return True
        except Exception as e:
            logger.warning("跨表更新实体ID失败: %s", e)
            pg_conn.rollback()
            if sqlite_conn:
                sqlite_conn.rollback()
            return False
        finally:
            pg_cur.close()
            pg_conn.close()
            if sqlite_cur:
                sqlite_cur.close()
            if sqlite_conn:
                sqlite_conn.close()
