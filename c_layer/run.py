"""C 层入口：启动 C-Online 消费者和 HTTP API"""
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.logger import setup_logger
logger = setup_logger("c_layer")


def main():
    logger.info("C层启动...")

    # 在子线程中启动 HTTP API
    from c_layer.c_online.api_server import run_api
    api_thread = threading.Thread(target=run_api, daemon=True, name="C-API")
    api_thread.start()
    logger.info("HTTP API 线程已启动")

    # 在主线程中启动 MQ 消费者
    from c_layer.c_online.consumer import COnlineConsumer
    consumer = COnlineConsumer()
    consumer.run()

if __name__ == "__main__":
    main()
