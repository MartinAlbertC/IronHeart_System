# -*- coding: utf-8 -*-
"""
A 层（感知层）MQ 模式入口
- 从视频文件运行视觉+音频管道
- 事件通过 EventSink 自动写入文件 + 推送到 MQ a_events 队列
- 日志记录完整的 PerceptionEvent 输出
"""
import argparse
import sys
import time
import threading
from datetime import datetime
from pathlib import Path

# 1. IranHeart_System 根目录 → 可导入 shared.*
sys.path.insert(0, str(Path(__file__).parent.parent))
# 2. a_layer 目录 → 可导入 src.*
sys.path.insert(0, str(Path(__file__).parent))

from shared.logger import setup_logger, log_event_outbound
logger = setup_logger("a_layer")


def main():
    parser = argparse.ArgumentParser(description="IranHeart A-layer Perception Pipeline")
    parser.add_argument("--video", type=str, required=True, help="视频文件路径")
    parser.add_argument("--max-frames", type=int, default=None, help="最大处理帧数")
    args = parser.parse_args()
    logger.info(f"A-layer startup | video={args.video} | max_frames={args.max_frames}")

    # 导入 A 层模块（此时 sys.path 已设置好）
    # 先加载本层 config 覆盖 src.core.config（让 src 模块读到正确的路径）
    import a_layer.config as _cfg
    import src.core.config as _core_cfg
    # 将本层 config 的属性同步到 src.core.config
    for attr in dir(_cfg):
        if attr.isupper():
            setattr(_core_cfg, attr, getattr(_cfg, attr))

    from src.core.event_generator import EventSink
    sink = EventSink(
        output_file=str(Path(__file__).parent.parent / "outputs" / "a_events_backup.jsonl"),
        append=False,
    )

    from src.vision.vision_pipeline import VisionPipeline
    from src.audio.audio_pipeline import AudioPipeline

    logger.info("Loading vision pipeline models...")
    vision = VisionPipeline(event_sink=sink)

    logger.info("Loading audio pipeline models...")
    audio = AudioPipeline(event_sink=sink)

    # 并行处理
    shared_start_time = datetime.now()
    errors = {}

    def run_vision():
        try:
            vision.process_video(args.video, max_frames=args.max_frames, start_time=shared_start_time)
        except Exception as e:
            errors["vision"] = e
            logger.error(f"Vision pipeline error: {e}", exc_info=True)

    def run_audio():
        try:
            audio.process_video(args.video, start_time=shared_start_time)
        except Exception as e:
            errors["audio"] = e
            logger.error(f"Audio pipeline error: {e}", exc_info=True)

    t0 = time.time()

    vt = threading.Thread(target=run_vision, daemon=True, name="run_vision")
    vt.start()
    at = threading.Thread(target=run_audio, daemon=True, name="run_audio")
    at.start()

    vt.join()
    at.join()
    elapsed = time.time() - t0

    sink.close()

    if errors:
        for name, err in errors.items():
            logger.error(f"[{name}] {err}")
        sys.exit(1)

    logger.info(f"A-layer processing complete | elapsed={elapsed:.1f}s")


if __name__ == "__main__":
    main()
