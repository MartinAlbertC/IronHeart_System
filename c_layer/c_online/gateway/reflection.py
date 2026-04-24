"""反思配置与调度 — /api/reflect/*"""
import json
import time
import threading
import sys
import traceback
from pathlib import Path
from datetime import datetime, date, timedelta
from typing import Optional, List

from fastapi import APIRouter

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from c_layer.c_online.gateway.response import ok, ApiError
from c_layer.c_online.gateway import status as status_module
from c_layer.config import PG_CONFIG

router = APIRouter()

# 开发人员限定的参数
DEFAULT_MAX_DAILY_REFLECTIONS = 3
DEFAULT_MIN_INTERVAL_MINUTES = 60


def _pg_conn():
    import psycopg
    return psycopg.connect(**PG_CONFIG, autocommit=True)


def _load_config() -> dict:
    """从 PostgreSQL 读取反思配置"""
    try:
        import psycopg
        conn = psycopg.connect(**PG_CONFIG, autocommit=True)
        cur = conn.cursor()
        cur.execute("SELECT schedule_time, today_count, last_date FROM reflection_config WHERE id=1")
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row:
            raw = row[0]
            # 兼容旧格式（单时间字符串）和新格式（JSON 数组）
            if raw.startswith('['):
                schedule_times = json.loads(raw)
            else:
                schedule_times = [raw]
            return {
                "schedule_times": schedule_times,
                "today_count": row[1] or 0,
                "last_date": str(row[2]) if row[2] else "",
            }
    except Exception as e:
        print(f"[reflection] 加载配置失败: {e}")
    return {"schedule_times": ["00:00"], "today_count": 0, "last_date": ""}


def _save_schedule_times(times: List[str]):
    """保存调度时间列表到数据库"""
    import psycopg
    conn = psycopg.connect(**PG_CONFIG, autocommit=True)
    cur = conn.cursor()
    cur.execute("UPDATE reflection_config SET schedule_time = %s, updated_at = NOW() WHERE id = 1",
                (json.dumps(times, ensure_ascii=False),))
    cur.close()
    conn.close()


def _reset_daily_count_if_needed(config: dict):
    """如果是新的一天，重置 daily count"""
    today = str(date.today())
    if config.get("last_date") != today:
        try:
            import psycopg
            conn = psycopg.connect(**PG_CONFIG, autocommit=True)
            cur = conn.cursor()
            cur.execute("UPDATE reflection_config SET today_count = 0, last_date = %s WHERE id = 1", (today,))
            cur.close()
            conn.close()
        except Exception:
            pass


def _save_reflection_history(result: dict, trigger_type: str, duration: float):
    """保存反思历史到数据库"""
    summary = result.get("summary", result)
    try:
        import psycopg
        conn = psycopg.connect(**PG_CONFIG, autocommit=True)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO reflection_history (trigger_type, tier3_events, tier2_written, labels_updated, names_updated, tier1_updated, duration_seconds)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            trigger_type,
            summary.get("tier3_events", 0),
            summary.get("tier2_written", 0),
            summary.get("labels_updated", 0),
            summary.get("names_updated", 0),
            summary.get("tier1_updated", False),
            int(duration),
        ))
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[reflection] 保存历史失败: {e}")


def _increment_daily_count():
    """增加今日反思计数"""
    try:
        import psycopg
        conn = psycopg.connect(**PG_CONFIG, autocommit=True)
        cur = conn.cursor()
        cur.execute("UPDATE reflection_config SET today_count = today_count + 1 WHERE id = 1")
        cur.close()
        conn.close()
    except Exception:
        pass


def run_reflection(trigger_type: str = "manual", enable_tier1_llm: bool = True) -> dict:
    """执行一次反思"""
    status_module.set_reflecting(True)
    start_time = time.time()
    result = {}
    try:
        from c_layer.night_reflection import NightReflector
        from c_layer.config import PG_CONFIG, TIER3_DB_PATH
        reflector = NightReflector(PG_CONFIG, TIER3_DB_PATH, "default_user")
        result = reflector.run(
            dry_run=False,
            enable_tier1_update=True,
            enable_tier1_llm=enable_tier1_llm,
        )
    except Exception as e:
        print(f"[reflection] 反思执行失败: {e}")
        traceback.print_exc()
        result = {"error": str(e)}
    finally:
        status_module.set_reflecting(False)
        duration = time.time() - start_time
        _save_reflection_history(result, trigger_type, duration)
        # 只有自动触发才计入每日计数
        if trigger_type == "auto":
            _increment_daily_count()
    return result


class ReflectionScheduler:
    """后台线程，按配置时间触发反思"""

    def __init__(self):
        self._running = False
        self._thread = None
        self._triggered_times_today = set()
        self._current_date = ""

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="ReflectionScheduler")
        self._thread.start()
        print("[ReflectionScheduler] 已启动")

    def _loop(self):
        while self._running:
            try:
                config = _load_config()
                _reset_daily_count_if_needed(config)
                config = _load_config()

                now = datetime.now()
                today = str(date.today())

                # 新的一天，重置已触发记录
                if self._current_date != today:
                    self._triggered_times_today = set()
                    self._current_date = today

                # 检查当前时间是否匹配某个调度时间
                current_time = f"{now.hour:02d}:{now.minute:02d}"
                for t in config.get("schedule_times", []):
                    if (t == current_time and
                        t not in self._triggered_times_today and
                        config.get("today_count", 0) < DEFAULT_MAX_DAILY_REFLECTIONS):

                        print(f"[ReflectionScheduler] 到达反思时间 {t}，开始执行 (今日第{config['today_count']+1}次)")
                        run_reflection(trigger_type="auto", enable_tier1_llm=True)
                        self._triggered_times_today.add(t)
                        break
            except Exception as e:
                print(f"[ReflectionScheduler] 循环异常: {e}")

            time.sleep(60)

    def stop(self):
        self._running = False


# 全局实例
scheduler = ReflectionScheduler()


@router.get("/api/reflect/config")
async def get_reflect_config():
    config = _load_config()
    _reset_daily_count_if_needed(config)
    config = _load_config()

    return ok({
        "schedule_times": config["schedule_times"],
        "max_daily_reflections": DEFAULT_MAX_DAILY_REFLECTIONS,
        "min_interval_minutes": DEFAULT_MIN_INTERVAL_MINUTES,
        "today_reflection_count": config.get("today_count", 0),
        "last_reflection_at": config.get("last_date"),
    })


@router.put("/api/reflect/config")
async def update_reflect_config(body: dict):
    """仅接受 schedule_time 字段（向后兼容）"""
    time_str = body.get("schedule_time", "").strip()
    if not time_str:
        raise ApiError(40001, "schedule_time 不能为空")
    try:
        parts = time_str.split(":")
        hour, minute = int(parts[0]), int(parts[1])
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError()
    except (ValueError, IndexError):
        raise ApiError(40001, "时间格式错误，应为 HH:MM")

    # 覆盖为单个时间点（向后兼容）
    _save_schedule_times([time_str])
    return ok({"schedule_times": [time_str]})


@router.post("/api/reflect/schedule")
async def add_schedule_time(body: dict):
    """添加一个调度时间点"""
    time_str = body.get("time", "").strip()
    if not time_str:
        raise ApiError(40001, "time 不能为空")
    try:
        parts = time_str.split(":")
        hour, minute = int(parts[0]), int(parts[1])
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError()
    except (ValueError, IndexError):
        raise ApiError(40001, "时间格式错误，应为 HH:MM")

    config = _load_config()
    times = config.get("schedule_times", [])

    if time_str in times:
        raise ApiError(40001, f"调度时间 {time_str} 已存在")

    if len(times) >= DEFAULT_MAX_DAILY_REFLECTIONS:
        raise ApiError(40001, f"调度时间数量不能超过每日最大反思次数 ({DEFAULT_MAX_DAILY_REFLECTIONS})")

    times.append(time_str)
    times.sort()
    _save_schedule_times(times)
    return ok({"schedule_times": times})


@router.delete("/api/reflect/schedule")
async def remove_schedule_time(body: dict):
    """删除一个调度时间点"""
    time_str = body.get("time", "").strip()
    if not time_str:
        raise ApiError(40001, "time 不能为空")

    config = _load_config()
    times = config.get("schedule_times", [])

    if time_str not in times:
        raise ApiError(40001, f"调度时间 {time_str} 不存在")

    times.remove(time_str)
    _save_schedule_times(times)
    return ok({"schedule_times": times})


@router.post("/api/reflect/trigger")
async def trigger_reflect(body: dict = None):
    """手动触发反思（不受最大次数和最小间隔限制）"""
    body = body or {}
    enable_tier1_llm = body.get("enable_tier1_llm", True)

    if status_module._reflecting:
        raise ApiError(40901, "反思正在进行中")

    result = run_reflection(trigger_type="manual", enable_tier1_llm=enable_tier1_llm)
    summary = result.get("summary", result)
    return ok({
        "triggered": True,
        "message": "反思已完成",
        "tier2_written": summary.get("tier2_written", 0),
        "labels_updated": summary.get("labels_updated", 0),
        "tier1_updated": summary.get("tier1_updated", False),
    })


@router.get("/api/reflect/history")
async def get_reflect_history(page: int = 1, page_size: int = 10):
    import psycopg
    conn = psycopg.connect(**PG_CONFIG, autocommit=True)
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM reflection_history")
    total = cur.fetchone()[0]

    offset = (page - 1) * page_size
    cur.execute("""
        SELECT id, triggered_at, trigger_type, tier3_events, tier2_written,
               labels_updated, names_updated, tier1_updated, duration_seconds
        FROM reflection_history ORDER BY triggered_at DESC LIMIT %s OFFSET %s
    """, (page_size, offset))
    rows = cur.fetchall()
    cur.close()
    conn.close()

    records = [{
        "id": r[0],
        "triggered_at": str(r[1]) if r[1] else None,
        "trigger_type": r[2],
        "tier3_events": r[3],
        "tier2_written": r[4],
        "labels_updated": r[5],
        "names_updated": r[6],
        "tier1_updated": r[7],
        "duration_seconds": r[8],
    } for r in rows]

    return ok({"total": total, "records": records})
