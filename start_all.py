#!/usr/bin/env python3
"""
IranHeart 统一启动脚本
启动顺序:
  1. Broker (MQ消息中间件)
  2. B层 → C层 → D层 → E层
  3. A层 (最后启动，开始推事件)

用法:
  python start_all.py --video data/test.mp4
  python start_all.py --video data/test.mp4 --max-frames 300
  python start_all.py --mode no-a          # 跳过 A 层
"""
import subprocess
import time
import sys
import os
import socket
import argparse
import logging
from pathlib import Path
from typing import Dict

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("start_all")

BASE_DIR = Path(__file__).parent.resolve()

# Python 解释器：A 层用 d2lGPU conda 环境（有 GPU + CV 依赖），其余用系统 Python
D2LGPU_PYTHON = r"C:\Users\CWQ98\anaconda3\envs\d2lGPU\python.exe"
SYSTEM_PYTHON = sys.executable


def _resolve_python(layer: str) -> str:
    """选择对应层的 Python 解释器"""
    if layer == "a_layer":
        if Path(D2LGPU_PYTHON).exists():
            return D2LGPU_PYTHON
        logger.warning(f"d2lGPU not found at {D2LGPU_PYTHON}, falling back to system Python")
    return SYSTEM_PYTHON


def build_process_scripts(video_path: str = None, max_frames: int = None) -> dict:
    """构建各层启动命令"""
    scripts = {
        "broker": {
            "cmd": [SYSTEM_PYTHON, str(BASE_DIR / "message_queue" / "broker.py")],
            "delay": 0,
        },
        "b_layer": {
            "cmd": [SYSTEM_PYTHON, str(BASE_DIR / "b_layer" / "run.py")],
            "delay": 2,
        },
        "c_layer": {
            "cmd": [SYSTEM_PYTHON, str(BASE_DIR / "c_layer" / "run.py")],
            "delay": 3,
        },
        "d_layer": {
            "cmd": [SYSTEM_PYTHON, str(BASE_DIR / "d_layer" / "run.py")],
            "delay": 3,
        },
        "e_layer": {
            "cmd": ["node", str(BASE_DIR / "e_layer" / "dist" / "mqConsumer.js")],
            "delay": 3,
        },
    }

    # A 层：使用本地 a_layer/run.py（d2lGPU 环境）
    if video_path:
        a_python = _resolve_python("a_layer")
        abs_video = str(Path(video_path).resolve())
        a_cmd = [a_python, str(BASE_DIR / "a_layer" / "run.py"), "--video", abs_video]
        if max_frames:
            a_cmd.extend(["--max-frames", str(max_frames)])
        scripts["a_layer"] = {"cmd": a_cmd, "delay": 2, "cwd": str(BASE_DIR)}

    return scripts


# 启动顺序
LAYER_NAMES = ["broker", "a_layer", "b_layer", "c_layer", "d_layer", "e_layer"]


class SystemLauncher:
    def __init__(self, video_path: str = None, max_frames: int = None):
        self.processes: Dict[str, subprocess.Popen] = {}
        self.start_time = time.time()
        self.logs_dir = BASE_DIR / "logs"
        self.logs_dir.mkdir(exist_ok=True)
        self.scripts = build_process_scripts(video_path, max_frames)
        self.video_path = video_path
        logger.info("=" * 60)
        logger.info("  IranHeart Multi-Agent System Launcher")
        logger.info("=" * 60)

    def _start_process(self, name: str):
        """启动单个进程"""
        if name not in self.scripts:
            logger.warning(f"  [{name}] no launch config, skipping")
            return
        script_info = self.scripts[name]
        cmd = script_info["cmd"]
        logger.info(f"  Starting {name}: {' '.join(cmd)}")

        log_out = open(self.logs_dir / f"{name}_stdout.log", "w", encoding="utf-8")
        log_err = open(self.logs_dir / f"{name}_stderr.log", "w", encoding="utf-8")

        proc = subprocess.Popen(
            cmd,
            stdout=log_out,
            stderr=log_err,
            cwd=script_info.get("cwd", str(BASE_DIR)),
        )
        self.processes[name] = proc
        logger.info(f"  [{name}] PID={proc.pid}")

    def _wait_for_broker(self, timeout=30) -> bool:
        """等待 Broker 启动就绪"""
        logger.info("  Waiting for broker to start...")
        start = time.time()
        while time.time() - start < timeout:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            try:
                sock.connect(("localhost", 6380))
                sock.close()
                logger.info("  Broker ready on port 6380")
                return True
            except (socket.timeout, OSError, ConnectionRefusedError):
                sock.close()
                time.sleep(1)
        logger.error("  Broker startup timeout")
        return False

    def _monitor_process(self, name: str) -> bool:
        """检查进程是否存活"""
        proc = self.processes.get(name)
        if proc is None:
            return False
        if proc.poll() is not None:
            # A 层处理完视频后正常退出（code=0），不影响其他层运行
            if name == "a_layer" and proc.returncode == 0:
                logger.info(f"  [{name}] completed (video processing done), other layers keep running")
                return True
            logger.error(f"  [{name}] Process died with code {proc.returncode}")
            return False
        return True

    def launch_all(self):
        """启动所有层"""
        logger.info(f"Layers to start: {[n for n in LAYER_NAMES if n in self.scripts]}")

        # 1. 先启动 Broker 并等待就绪
        self._start_process("broker")
        if not self._wait_for_broker():
            logger.error("Broker failed to start, aborting")
            self.shutdown()
            return False
        time.sleep(1)

        # 2. 启动下游层（B/C/D/E 先启动，等待 A 层事件）
        for name in LAYER_NAMES:
            if name == "broker":
                continue
            if name == "a_layer":
                continue  # A 层最后启动
            self._start_process(name)
            delay = self.scripts[name].get("delay", 0)
            logger.info(f"  Waiting {delay}s for {name} to initialize...")
            time.sleep(delay)

        # 3. 最后启动 A 层（它会开始推送事件到队列）
        if "a_layer" in self.scripts:
            self._start_process("a_layer")
            logger.info("  A layer started, video processing begins...")

        # 4. 检查所有进程是否存活
        logger.info("Checking all processes...")
        all_alive = True
        for name in self.processes:
            if not self._monitor_process(name):
                all_alive = False
                logger.error(f"  [{name}] NOT running")

        if not all_alive:
            logger.error("Some processes failed to start")
            self.shutdown()
            return False

        logger.info("All layers launched!")
        elapsed = time.time() - self.start_time
        logger.info(f"  Started in {elapsed:.1f}s")
        logger.info(f"  Processes: {len(self.processes)}")
        logger.info("=" * 60)
        logger.info("System running... Press Ctrl+C to stop")
        logger.info("")

        # 5. 主循环：监控所有进程（持久运行，仅 Ctrl+C 退出）
        try:
            while True:
                for name in list(self.processes.keys()):
                    proc = self.processes.get(name)
                    if proc and proc.poll() is not None:
                        # A 层正常完成后仅记录日志，不影响其他层
                        if name == "a_layer" and proc.returncode == 0:
                            logger.info(f"[{name}] video processing finished, B/C/D/E layers continue running")
                        else:
                            logger.error(f"[{name}] process died (code={proc.returncode}), shutting down")
                            self.shutdown()
                            return False
                time.sleep(2)
        except KeyboardInterrupt:
            logger.info("\nShutting down...")
        finally:
            self.shutdown()
        return True

    def shutdown(self):
        """Stop all processes gracefully"""
        logger.info("Stopping all processes...")
        for name, proc in self.processes.items():
            try:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                logger.info(f"  [{name}] stopped")
            except Exception as e:
                logger.warning(f"  [{name}] stop error: {e}")
        elapsed = time.time() - self.start_time
        logger.info(f"  Total runtime: {elapsed:.1f}s")
        logger.info("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Launch IranHeart system")
    parser.add_argument("--video", type=str, default=None, help="A层输入视频路径")
    parser.add_argument("--max-frames", type=int, default=None, help="A层最大处理帧数")
    parser.add_argument("--mode", choices=["full", "no-a"], default="full",
                        help="full=全部启动, no-a=跳过A层(无视频时)")
    args = parser.parse_args()

    video_path = args.video
    max_frames = args.max_frames

    if args.mode == "no-a" and not video_path:
        video_path = None

    launcher = SystemLauncher(video_path=video_path, max_frames=max_frames)
    try:
        launcher.launch_all()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        logger.error(f"Launch failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
