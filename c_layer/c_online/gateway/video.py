"""视频上传管理 — /api/video/*"""
import asyncio
import json
import sys
import uuid
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Dict

from fastapi import APIRouter, UploadFile, File

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from c_layer.c_online.gateway.response import ok, ApiError
from c_layer.c_online.gateway import status as status_module
from c_layer.config import PG_CONFIG

router = APIRouter()

UPLOAD_DIR = Path(__file__).parent.parent.parent.parent / "data" / "uploads"
D2LGPU_PYTHON = r"C:\Users\CWQ98\anaconda3\envs\d2lGPU\python.exe"
BASE_DIR = Path(__file__).parent.parent.parent.parent

# 内存中的任务追踪
_video_jobs: Dict[str, dict] = {}


def _pg_conn():
    import psycopg
    return psycopg.connect(**PG_CONFIG, autocommit=True)


def _save_job_to_db(job: dict):
    """持久化任务到数据库"""
    try:
        import psycopg
        conn = psycopg.connect(**PG_CONFIG, autocommit=True)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO video_jobs (job_id, status, file_path, file_size_mb, source, created_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (job_id) DO UPDATE SET status = EXCLUDED.status, completed_at = EXCLUDED.completed_at,
                                                events_generated = EXCLUDED.events_generated, return_code = EXCLUDED.return_code
        """, (
            job["job_id"], job["status"], job.get("path", ""),
            job.get("file_size_mb"), job.get("source", "camera"),
            job.get("created_at"),
        ))
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[video] 保存任务到数据库失败: {e}")


async def _monitor_job(job_id: str, proc: subprocess.Popen):
    """后台监控 A 层进程"""
    while True:
        ret = proc.poll()
        if ret is not None:
            job = _video_jobs.get(job_id, {})
            job["completed_at"] = datetime.now().isoformat()
            job["return_code"] = ret
            if ret == 0:
                job["status"] = "completed"
            else:
                # A 层可能因音频连接超时等非致命错误退出非零，
                # 但视频处理本身已完成。检查是否生成了事件。
                import sqlite3
                from c_layer.config import TIER3_DB_PATH
                try:
                    conn = sqlite3.connect(TIER3_DB_PATH)
                    cur = conn.cursor()
                    cur.execute("SELECT COUNT(*) FROM tier3_events WHERE semantic_event_id LIKE 'evt_%'")
                    count = cur.fetchone()[0]
                    conn.close()
                    if count > 0:
                        job["status"] = "completed"
                        job["warning"] = f"A层退出码={ret}（非致命），视频处理已完成"
                    else:
                        job["status"] = "failed"
                except Exception:
                    job["status"] = "failed"
            _save_job_to_db(job)

            # 清除视频处理状态
            if status_module._video_status and status_module._video_status.get("job_id") == job_id:
                status_module.set_video_status(None)
            break
        await asyncio.sleep(2)


@router.post("/api/video/upload")
async def upload_video(file: UploadFile = File(...), source: str = "camera"):
    if not file.filename or not file.filename.lower().endswith(".mp4"):
        raise ApiError(40001, "仅支持 MP4 格式")

    # 检查是否有正在处理的任务
    for j in _video_jobs.values():
        if j.get("status") == "processing":
            raise ApiError(40901, "已有视频正在处理中，请等待完成")

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    job_id = f"job_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    save_path = UPLOAD_DIR / f"{job_id}.mp4"

    # 写入文件
    content = await file.read()
    with open(save_path, "wb") as f:
        f.write(content)
    file_size = round(len(content) / (1024 * 1024), 1)

    # 创建任务记录
    created_at = datetime.now().isoformat()
    job = {
        "job_id": job_id,
        "status": "processing",
        "path": str(save_path),
        "file_size_mb": file_size,
        "source": source,
        "created_at": created_at,
        "process": None,
    }
    _video_jobs[job_id] = job
    _save_job_to_db(job)

    # 设置视频处理状态
    status_module.set_video_status({
        "has_active_job": True,
        "job_id": job_id,
        "progress": 0.0,
    })

    # 启动 A 层进程
    cmd = [D2LGPU_PYTHON, str(BASE_DIR / "a_layer" / "run.py"), "--video", str(save_path)]
    proc = subprocess.Popen(cmd, cwd=str(BASE_DIR))
    job["process"] = proc

    # 后台监控
    asyncio.create_task(_monitor_job(job_id, proc))

    return ok({
        "job_id": job_id,
        "status": "processing",
        "file_size_mb": file_size,
        "created_at": created_at,
    })


@router.get("/api/video/status/{job_id}")
async def get_video_status(job_id: str):
    job = _video_jobs.get(job_id)
    if not job:
        # 尝试从数据库加载
        try:
            import psycopg
            conn = psycopg.connect(**PG_CONFIG, autocommit=True)
            cur = conn.cursor()
            cur.execute("SELECT job_id, status, file_size_mb, events_generated, created_at, completed_at FROM video_jobs WHERE job_id = %s", (job_id,))
            row = cur.fetchone()
            cur.close()
            conn.close()
            if row:
                return ok({
                    "job_id": row[0],
                    "status": row[1],
                    "file_size_mb": row[2],
                    "events_generated": row[3],
                    "created_at": str(row[4]) if row[4] else None,
                    "completed_at": str(row[5]) if row[5] else None,
                })
        except Exception:
            pass
        raise ApiError(40401, "任务不存在")

    return ok({
        "job_id": job_id,
        "status": job["status"],
        "file_size_mb": job.get("file_size_mb"),
        "created_at": job.get("created_at"),
        "completed_at": job.get("completed_at"),
    })


@router.get("/api/video/jobs")
async def list_video_jobs(page: int = 1, page_size: int = 10):
    # 合并内存和数据库的任务
    all_jobs = list(_video_jobs.values())

    try:
        import psycopg
        conn = psycopg.connect(**PG_CONFIG, autocommit=True)
        cur = conn.cursor()
        cur.execute("SELECT job_id, status, file_size_mb, events_generated, created_at, completed_at FROM video_jobs ORDER BY created_at DESC")
        rows = cur.fetchall()
        cur.close()
        conn.close()
        for r in rows:
            if r[0] not in _video_jobs:
                all_jobs.append({
                    "job_id": r[0], "status": r[1], "file_size_mb": r[2],
                    "events_generated": r[3], "created_at": str(r[4]),
                    "completed_at": str(r[5]) if r[5] else None,
                })
    except Exception:
        pass

    all_jobs.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    start = (page - 1) * page_size
    page_jobs = all_jobs[start:start + page_size]

    return ok({
        "total": len(all_jobs),
        "page": page,
        "page_size": page_size,
        "jobs": [{k: v for k, v in j.items() if k != "process"} for j in page_jobs],
    })
