"""
B 层（语义聚合层）MQ 模式入口

从 a_events 队列订阅 A 层事件，经身份跟踪、事件聚合、语义生成后，
将 B 层语义事件发布到 b_events 队列。
"""
import json
import uuid
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.logger import setup_logger, log_event_inbound, log_event_outbound
from shared.mq_client import MQClient

logger = setup_logger("b_layer")


class BLayerProcessor:
    """B 层处理器：订阅 A 层事件 → 聚合分析 → 发布 B 层语义事件"""

    def __init__(self, config: dict):
        self.mq = MQClient()
        self.config = config

        from b_layer.identity_tracker import IdentityTracker
        from b_layer.event_aggregator import EventAggregator
        from b_layer.semantic_generator import SemanticGenerator
        from b_layer.context_manager import ContextManager

        db_path = str(Path(__file__).parent.parent / "outputs" / "person_cache.db")
        self.tracker = IdentityTracker(db_path, config['identity']['face_similarity_threshold'])
        self.context_mgr = ContextManager()
        self.aggregator = EventAggregator(config)
        self.generator = SemanticGenerator(config)

        self.event_count = 0
        self.semantic_count = 0

        logger.info("B层处理器初始化完成")

    def process_a_event(self, a_event: dict):
        """处理单个 A 层事件（由 MQ subscribe 回调调用）"""
        try:
            # 记录接收到的 A 层事件
            log_event_inbound(logger, "A", "PerceptionEvent", a_event)

            self.event_count += 1
            event_type = a_event.get("event_type", "unknown")
            logger.info(f"处理A层事件 #{self.event_count}: type={event_type}")

            # 1. 更新上下文
            self.context_mgr.update(a_event)

            # 2. 身份跟踪：为 face_detection 和 speech_segment 匹配/创建身份
            if event_type == 'face_detection':
                face_emb = a_event['payload']['face_embedding']['vector']
                ts = self._parse_event_time(a_event)
                alias_id = self.tracker.match_or_create(face_emb, 'face', timestamp=ts)
                a_event['resolved_alias'] = alias_id

            elif event_type == 'speech_segment':
                voice_emb = a_event['payload'].get('voice_embedding', {}).get('vector')
                if voice_emb:
                    ts = self._parse_event_time(a_event)
                    alias_id = self.tracker.match_or_create(voice_emb, 'voice', timestamp=ts)
                    a_event['resolved_alias'] = alias_id

            # 3. 添加到聚合窗口
            self.aggregator.add_event(a_event)

            # 4. 检查是否触发聚合输出
            if self.aggregator.should_trigger():
                self._flush_window()

        except Exception as e:
            logger.error(f"处理A层事件异常: {e}", exc_info=True)

    @staticmethod
    def _parse_event_time(event: dict) -> datetime:
        """从 A 层事件中解析时间戳"""
        ts_str = event.get('time', {}).get('start_ts', '')
        if ts_str:
            return datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
        return datetime.now()

    def _flush_window(self):
        """将当前聚合窗口的事件生成语义事件并发布"""
        window_events = self.aggregator.window
        if not window_events:
            return

        context = self.context_mgr.get_context()

        # 调用 LLM 生成语义
        llm_result = self.generator.generate(window_events, context)

        # Log LLM aggregation result
        sep = "=" * 70
        logger.info(f"\n{sep}")
        logger.info(">>> LLM AGGREGATION RESULT")
        logger.info(sep)
        logger.info(json.dumps(llm_result, ensure_ascii=False, indent=2))
        logger.info(f"{sep}\n")

        # 构建语义事件
        first_event = window_events[0]
        last_event = window_events[-1]

        primary_alias = None
        face_embedding = None
        voice_embedding = None
        for e in window_events:
            if 'resolved_alias' in e:
                if not primary_alias:
                    primary_alias = e['resolved_alias']
                if e['event_type'] == 'face_detection' and not face_embedding:
                    face_embedding = e['payload']['face_embedding']['vector']
                elif e['event_type'] == 'speech_segment' and not voice_embedding:
                    voice_embedding = e['payload'].get('voice_embedding', {}).get('vector')

        semantic_event = {
            'semantic_event_id': str(uuid.uuid4()),
            'temp_alias_id': primary_alias,
            'face_embedding': face_embedding,
            'voice_embedding': voice_embedding,
            'time': {
                'start_ts': first_event['time']['start_ts'],
                'end_ts': last_event['time']['end_ts']
            },
            'semantic_type': 'conversation_act',
            'summary': llm_result['summary'],
            'slots': {
                'platform_hint': 'offline',
                'ui_thread_hint': None,
                'dialogue_act': llm_result['dialogue_act']
            }
        }

        # 记录要发送到 C 层的语义事件
        log_event_outbound(logger, "C", "SemanticEvent", semantic_event)

        # 发布到 MQ
        self.mq.publish("b_events", semantic_event)
        self.semantic_count += 1
        logger.info(
            f"B层输出事件 #{self.semantic_count}: "
            f"type={semantic_event['semantic_type']} | "
            f"entity={primary_alias} | "
            f"dialogue_act={llm_result['dialogue_act']} | "
            f"summary={llm_result['summary'][:50]}"
        )

        # 重置聚合窗口
        self.aggregator.reset()

    def run(self):
        """主循环：订阅 a_events 队列"""
        logger.info("B层启动，订阅 a_events 队列...")
        self.mq.subscribe("a_events", self.process_a_event)

        # 保持主线程存活
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info(f"B层关闭 | 共处理 {self.event_count} 个A层事件, 生成 {self.semantic_count} 个B层事件")


def main():
    config_path = Path(__file__).parent.parent / "config.json"
    logger.info(f"加载配置: {config_path}")
    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)

    processor = BLayerProcessor(config)
    processor.run()


if __name__ == "__main__":
    main()
