"""
统一日志模块
- 每层独立日志文件: logs/a_layer.log, logs/b_layer.log, ...
- MQ 通信日志: logs/mq_comm.log
- 控制台 + 文件双输出
- JSONL 格式便于后续分析
"""
import logging
import os
import json
from pathlib import Path
from datetime import datetime


LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)


class JsonFormatter(logging.Formatter):
    """结构化 JSON 日志格式器"""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "ts": datetime.fromtimestamp(record.created).isoformat(timespec="milliseconds"),
            "layer": getattr(record, "layer_name", "unknown"),
            "level": record.levelname,
            "msg": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0]:
            log_entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(log_entry, ensure_ascii=False)


def setup_logger(layer_name: str, level: int = logging.INFO) -> logging.Logger:
    """
    创建层专用 Logger

    Args:
        layer_name: 层名称，如 "a_layer", "b_layer", "mq_comm"
        level: 日志级别

    Returns:
        配置好的 Logger 实例
    """
    logger = logging.getLogger(f"IranHeart.{layer_name}")

    # 避免重复添加 handler
    if logger.handlers:
        return logger

    logger.setLevel(level)

    # ── 控制台 handler ──
    console = logging.StreamHandler()
    console.setLevel(level)
    console_fmt = logging.Formatter(
        f"[%(asctime)s] [{layer_name}] %(levelname)s - %(message)s",
        datefmt="%H:%M:%S",
    )
    console.setFormatter(console_fmt)
    logger.addHandler(console)

    # ── 文件 handler（人类可读）──
    fh = logging.FileHandler(
        LOG_DIR / f"{layer_name}.log", encoding="utf-8"
    )
    fh.setLevel(level)
    fh.setFormatter(console_fmt)
    logger.addHandler(fh)

    # ── JSONL 文件 handler（机器可读）──
    jfh = logging.FileHandler(
        LOG_DIR / f"{layer_name}.jsonl", encoding="utf-8"
    )
    jfh.setLevel(level)
    jfh.setFormatter(JsonFormatter())
    logger.addHandler(jfh)

    return logger


def get_mq_logger() -> logging.Logger:
    """获取 MQ 通信日志器"""
    return setup_logger("mq_comm")


# ── 层间事件日志（带凸显标记）──

def log_event_inbound(logger: logging.Logger, from_layer: str,
                       event_type: str, event_data: dict):
    """
    记录从上层收到的事件（带凸显标记）

    Args:
        logger: 层专用 Logger
        from_layer: 来源层标识（A/B/C/D/E）
        event_type: 事件类型（PerceptionEvent / SemanticEvent / Opportunity / ExecutionPlan）
        event_data: 事件完整数据
    """
    event_json = json.dumps(event_data, ensure_ascii=False, default=str)
    sep = "=" * 70
    logger.info(f"\n{sep}")
    logger.info(f">>> INBOUND [{event_type}] from {from_layer}-layer")
    logger.info(sep)
    logger.info(event_json)
    logger.info(f"{sep}\n")


def log_event_outbound(logger: logging.Logger, to_layer: str,
                        event_type: str, event_data: dict):
    """
    记录向下层发送的事件（带凸显标记）

    Args:
        logger: 层专用 Logger
        to_layer: 目标层标识（A/B/C/D/E）
        event_type: 事件类型
        event_data: 事件完整数据
    """
    event_json = json.dumps(event_data, ensure_ascii=False, default=str)
    sep = "=" * 70
    logger.info(f"\n{sep}")
    logger.info(f"<<< OUTBOUND [{event_type}] to {to_layer}-layer")
    logger.info(sep)
    logger.info(event_json)
    logger.info(f"{sep}\n")
