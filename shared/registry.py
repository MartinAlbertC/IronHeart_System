"""
人员注册库 - 双模态（人脸 + 声纹）SQLite 存储
"""
import sqlite3
import numpy as np
import json
from pathlib import Path
from typing import List, Optional, Tuple, Dict
from datetime import datetime


DB_PATH = Path(__file__).parent.parent / "data" / "registry.db"


class PersonRegistry:
    """双模态人员注册库，支持人脸和声纹 embedding 的存储与匹配"""

    def __init__(self, db_path: str = str(DB_PATH)):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        # 内存缓存：person_id → {face_mean, voice_mean, is_wearer}
        self._cache: Dict[str, Dict] = {}
        self._load_cache()
        self._purge_strangers()

    # ─────────────────────────────────────────────────────────────
    # 清理
    # ─────────────────────────────────────────────────────────────

    def _purge_strangers(self, ttl_days: int = 7):
        """删除超过 ttl_days 天未出现的陌生人（person_id 以 stranger_ 开头）"""
        from datetime import timedelta
        cutoff = (datetime.now() - timedelta(days=ttl_days)).isoformat()
        with self._conn() as conn:
            # 找出过期陌生人
            rows = conn.execute("""
                SELECT person_id FROM persons
                WHERE person_id LIKE 'stranger_%'
                AND is_wearer = 0
                AND (last_seen IS NULL OR last_seen < ?)
                AND created_at < ?
            """, (cutoff, cutoff)).fetchall()

            for (pid,) in rows:
                conn.execute("DELETE FROM face_embeddings WHERE person_id=?", (pid,))
                conn.execute("DELETE FROM voice_embeddings WHERE person_id=?", (pid,))
                conn.execute("DELETE FROM persons WHERE person_id=?", (pid,))
                self._cache.pop(pid, None)

        if rows:
            import logging
            logging.getLogger(__name__).info(f"清理过期陌生人: {len(rows)} 条")

    # ─────────────────────────────────────────────────────────────
    # 初始化
    # ─────────────────────────────────────────────────────────────

    def _init_db(self):
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS persons (
                    person_id   TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    is_wearer   INTEGER DEFAULT 0,
                    created_at  TEXT NOT NULL,
                    updated_at  TEXT NOT NULL,
                    last_seen   TEXT
                );""")
            # 迁移：旧表可能缺少 last_seen 列
            cols = {r[1] for r in conn.execute("PRAGMA table_info(persons)").fetchall()}
            if "last_seen" not in cols:
                conn.execute("ALTER TABLE persons ADD COLUMN last_seen TEXT")
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS face_embeddings (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    person_id   TEXT NOT NULL,
                    vector      BLOB NOT NULL,
                    quality     REAL,
                    created_at  TEXT NOT NULL,
                    FOREIGN KEY (person_id) REFERENCES persons(person_id)
                );
                CREATE TABLE IF NOT EXISTS voice_embeddings (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    person_id   TEXT NOT NULL,
                    vector      BLOB NOT NULL,
                    quality     REAL,
                    created_at  TEXT NOT NULL,
                    FOREIGN KEY (person_id) REFERENCES persons(person_id)
                );
            """)

    def _conn(self):
        return sqlite3.connect(self.db_path)

    # ─────────────────────────────────────────────────────────────
    # 注册
    # ─────────────────────────────────────────────────────────────

    def register_person(self, person_id: str, display_name: str, is_wearer: bool = False):
        """注册新人员。若 person_id 已存在则跳过，不覆盖。"""
        now = datetime.now().isoformat()
        with self._conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO persons VALUES (?,?,?,?,?,?)",
                (person_id, display_name, int(is_wearer), now, now, None)
            )
        self._cache[person_id] = {
            "display_name": display_name,
            "is_wearer": is_wearer,
            "face_mean": None,
            "voice_mean": None,
        }

    def add_face_embedding(self, person_id: str, vector: np.ndarray, quality: float = None):
        """添加人脸 embedding 样本"""
        self._add_embedding("face_embeddings", person_id, vector, quality)
        self._update_mean(person_id, "face")

    def add_voice_embedding(self, person_id: str, vector: np.ndarray, quality: float = None):
        """添加声纹 embedding 样本"""
        self._add_embedding("voice_embeddings", person_id, vector, quality)
        self._update_mean(person_id, "voice")

    def _add_embedding(self, table: str, person_id: str, vector: np.ndarray, quality: float):
        now = datetime.now().isoformat()
        blob = vector.astype(np.float32).tobytes()
        with self._conn() as conn:
            conn.execute(
                f"INSERT INTO {table} (person_id, vector, quality, created_at) VALUES (?,?,?,?)",
                (person_id, blob, quality, now)
            )
            # 只保留最近 10 个样本
            conn.execute(f"""
                DELETE FROM {table} WHERE id IN (
                    SELECT id FROM {table} WHERE person_id=?
                    ORDER BY created_at ASC
                    LIMIT MAX(0, (SELECT COUNT(*) FROM {table} WHERE person_id=?) - 10)
                )
            """, (person_id, person_id))

    # ─────────────────────────────────────────────────────────────
    # 匹配
    # ─────────────────────────────────────────────────────────────

    def match_face(self, vector: np.ndarray, threshold: float = 0.5) -> Optional[Tuple[str, float]]:
        """人脸匹配，返回 (person_id, score) 或 None"""
        return self._match(vector, "face_mean", threshold)

    def match_voice(self, vector: np.ndarray, threshold: float = 0.75) -> Optional[Tuple[str, float]]:
        """声纹匹配，返回 (person_id, score) 或 None"""
        return self._match(vector, "voice_mean", threshold)

    def match_wearer_voice(self, vector: np.ndarray, threshold: float = 0.75) -> bool:
        """判断是否为穿戴者声音"""
        for pid, info in self._cache.items():
            if info["is_wearer"] and info["voice_mean"] is not None:
                score = self._cosine(vector, info["voice_mean"])
                if score >= threshold:
                    return True
        return False

    def get_wearer_id(self) -> Optional[str]:
        """获取穿戴者 person_id"""
        for pid, info in self._cache.items():
            if info["is_wearer"]:
                return pid
        return None

    def _match(self, vector: np.ndarray, mean_key: str, threshold: float) -> Optional[Tuple[str, float]]:
        best_id, best_score = None, 0.0
        for pid, info in self._cache.items():
            mean = info.get(mean_key)
            if mean is None:
                continue
            score = self._cosine(vector, mean)
            if score > best_score:
                best_score = score
                best_id = pid
        if best_id and best_score >= threshold:
            # 更新 last_seen
            now = datetime.now().isoformat()
            with self._conn() as conn:
                conn.execute("UPDATE persons SET last_seen=? WHERE person_id=?", (now, best_id))
            return best_id, best_score
        return None

    # ─────────────────────────────────────────────────────────────
    # 内部工具
    # ─────────────────────────────────────────────────────────────

    def _update_mean(self, person_id: str, modality: str):
        """重新计算并缓存均值 embedding"""
        table = f"{modality}_embeddings"
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT vector, quality FROM {table} WHERE person_id=?", (person_id,)
            ).fetchall()

        if not rows:
            return

        vectors = [np.frombuffer(r[0], dtype=np.float32) for r in rows]
        qualities = [r[1] if r[1] is not None else 0.5 for r in rows]

        weights = np.array(qualities, dtype=np.float32)
        weights /= weights.sum()
        mean = np.average(np.stack(vectors), axis=0, weights=weights).astype(np.float32)

        if person_id not in self._cache:
            self._cache[person_id] = {"face_mean": None, "voice_mean": None, "is_wearer": False}
        self._cache[person_id][f"{modality}_mean"] = mean

    def _load_cache(self):
        """启动时加载所有均值 embedding 到内存"""
        with self._conn() as conn:
            persons = conn.execute("SELECT person_id, display_name, is_wearer FROM persons").fetchall()

        for person_id, display_name, is_wearer in persons:
            self._cache[person_id] = {
                "display_name": display_name,
                "is_wearer": bool(is_wearer),
                "face_mean": None,
                "voice_mean": None,
            }
            self._update_mean(person_id, "face")
            self._update_mean(person_id, "voice")

    @staticmethod
    def _cosine(a: np.ndarray, b: np.ndarray) -> float:
        return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))

    def list_persons(self) -> List[Dict]:
        """列出所有注册人员及其样本数量"""
        with self._conn() as conn:
            persons = conn.execute("SELECT person_id, display_name, is_wearer FROM persons").fetchall()
            result = []
            for pid, name, is_wearer in persons:
                fc = conn.execute("SELECT COUNT(*) FROM face_embeddings WHERE person_id=?", (pid,)).fetchone()[0]
                vc = conn.execute("SELECT COUNT(*) FROM voice_embeddings WHERE person_id=?", (pid,)).fetchone()[0]
                result.append({
                    "person_id": pid,
                    "display_name": name,
                    "is_wearer": bool(is_wearer),
                    "face_samples": fc,
                    "voice_samples": vc,
                    "has_face": self._cache.get(pid, {}).get("face_mean") is not None,
                    "has_voice": self._cache.get(pid, {}).get("voice_mean") is not None,
                })
        return result
