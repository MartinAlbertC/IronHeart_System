"""C-Online MQ 消费者：订阅 b_events，构造 Opportunity，推送到 opportunities"""
import sys
import time
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared.logger import setup_logger, log_event_inbound, log_event_outbound
from shared.mq_client import MQClient
from c_layer.c_online.opportunity_builder import OpportunityBuilder

logger = setup_logger("c_layer")


class COnlineConsumer:
    def __init__(self):
        self.mq = MQClient()
        self.builder = OpportunityBuilder()
        logger.info("C-Online 消费者初始化完成")

    def on_b_event(self, b_event: dict):
        """处理一条 B 层事件"""
        # 增强日志：记录收到的完整 B 事件
        log_event_inbound(logger, "B", "SemanticEvent", b_event)

        opportunity = self.builder.build_opportunity(b_event)
        if opportunity:
            # 增强日志：记录发出的 Opportunity
            log_event_outbound(logger, "D", "Opportunity", opportunity)
            self.mq.publish("opportunities", opportunity)
        else:
            logger.warning("Opportunity 构造失败，跳过")

    def run(self):
        logger.info("C-Online 启动，订阅 b_events 队列...")
        self.mq.subscribe("b_events", self.on_b_event)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("C-Online 关闭")


def main():
    consumer = COnlineConsumer()
    consumer.run()

if __name__ == "__main__":
    main()
