#!/usr/bin/env python3
"""
IronHeart 常驻服务启动脚本
启动: Broker + B + C(API Gateway) + D + E + 反思调度器
不启动 A 层（A 层由 API 按需启动）

用法:
  python start_service.py            # 启动常驻服务
  python start_service.py --init-db  # 同时重建数据库
"""
import subprocess
import time
import sys
import os
import socket
import signal
import logging
from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()
D2LGPU_PYTHON = r"C:\Users\CWQ98\anaconda3\envs\d2lGPU\python.exe"
SYSTEM_PYTHON = sys.executable
LOGS_DIR = BASE_DIR / "logs"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("start_service")

processes = {}


def start_process(name, cmd, delay=0):
    log_out = open(LOGS_DIR / f"{name}_stdout.log", "w", encoding="utf-8")
    log_err = open(LOGS_DIR / f"{name}_stderr.log", "w", encoding="utf-8")
    proc = subprocess.Popen(cmd, stdout=log_out, stderr=log_err, cwd=str(BASE_DIR))
    processes[name] = proc
    logger.info(f"  [{name}] PID={proc.pid}")
    if delay:
        time.sleep(delay)


def wait_for_broker(timeout=30):
    logger.info("  Waiting for broker...")
    start = time.time()
    while time.time() - start < timeout:
        try:
            s = socket.socket()
            s.settimeout(2)
            s.connect(("localhost", 6380))
            s.close()
            logger.info("  Broker ready on port 6380")
            return True
        except Exception:
            time.sleep(1)
    return False


def init_db():
    logger.info("Rebuilding database...")
    subprocess.run([SYSTEM_PYTHON, str(BASE_DIR / "c_layer" / "rebuild_db.py")], cwd=str(BASE_DIR))


def main():
    LOGS_DIR.mkdir(exist_ok=True)

    if "--init-db" in sys.argv:
        init_db()

    logger.info("=" * 60)
    logger.info("  IronHeart Service Launcher (persistent mode)")
    logger.info("=" * 60)

    # 1. Broker
    start_process("broker", [SYSTEM_PYTHON, str(BASE_DIR / "message_queue" / "broker.py")])
    if not wait_for_broker():
        logger.error("Broker failed to start")
        sys.exit(1)
    time.sleep(1)

    # 2. B/C/D/E 常驻层
    start_process("b_layer", [SYSTEM_PYTHON, str(BASE_DIR / "b_layer" / "run.py")], delay=2)
    start_process("c_layer", [SYSTEM_PYTHON, str(BASE_DIR / "c_layer" / "run.py")], delay=3)
    start_process("d_layer", [SYSTEM_PYTHON, str(BASE_DIR / "d_layer" / "run.py")], delay=3)
    start_process("e_layer", ["node", str(BASE_DIR / "e_layer" / "dist" / "mqConsumer.js")], delay=3)

    logger.info("=" * 60)
    logger.info("  All layers running")
    logger.info("  API:  http://0.0.0.0:8000")
    logger.info("  Docs: http://0.0.0.0:8000/docs")
    logger.info("  Press Ctrl+C to stop")
    logger.info("=" * 60)

    try:
        while True:
            for name, proc in list(processes.items()):
                if proc.poll() is not None:
                    logger.error(f"[{name}] died (code={proc.returncode})")
            time.sleep(5)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        for name, proc in processes.items():
            proc.terminate()
            try:
                proc.wait(5)
            except Exception:
                proc.kill()
        logger.info("Stopped.")


if __name__ == "__main__":
    main()
