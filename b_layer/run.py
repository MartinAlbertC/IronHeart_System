"""
B 层（语义聚合层）MQ 模式入口

从 a_events 队列订阅 A 层事件，经身份跟踪、事件聚合、语义生成后，
将 B 层语义事件发布到 b_events 队列。
"""
import json
import uuid
import sys
import time
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.logger import setup_logger, log_event_inbound, log_event_outbound
from shared.mq_client import MQClient

logger = setup_logger("b_layer")


# ─────────────────────────────────────────────────────────────────────────────
# 日志格式化工具
# ─────────────────────────────────────────────────────────────────────────────

_PANEL_WIDTH = 80


def _panel(lines: list, title: str = "") -> str:
    """生成一个居中标题的面板字符串"""
    out = []
    if title:
        out.append(f"╔{'═' * (_PANEL_WIDTH - 2)}╗")
        pad_l = (_PANEL_WIDTH - 4 - len(title)) // 2
        pad_r = _PANEL_WIDTH - 4 - len(title) - pad_l
        out.append(f"║  {' ' * pad_l}{title}{' ' * pad_r}  ║")
        out.append(f"╠{'═' * (_PANEL_WIDTH - 2)}╣")
    else:
        out.append(f"╔{'═' * (_PANEL_WIDTH - 2)}╗")

    for line in lines:
        if len(line) > _PANEL_WIDTH - 4:
            line = line[:_PANEL_WIDTH - 7] + "..."
        pad = _PANEL_WIDTH - 4 - len(line)
        out.append(f"║  {line}{' ' * pad}  ║")
    out.append(f"╚{'═' * (_PANEL_WIDTH - 2)}╝")
    return "\n".join(out)


def _format_alias_state(state: dict, alias: str) -> str:
    fa = state['face_samples']
    va = state['voice_samples']
    face_mark = "●" if state['has_face'] else "○"
    voice_mark = "●" if state['has_voice'] else "○"
    last_seen = state.get('last_seen')
    if last_seen is not None:
        t = datetime.fromtimestamp(last_seen).strftime("%H:%M:%S")
        time_str = f" | last={t}"
    else:
        time_str = ""
    return f"  {alias:<10} 人脸{face_mark}({fa:2d})  声音{voice_mark}({va:2d}){time_str}"


# ─────────────────────────────────────────────────────────────────────────────
# B 层处理器
# ─────────────────────────────────────────────────────────────────────────────

class BLayerProcessor:
    """B 层处理器：订阅 A 层事件 → 聚合分析 → 发布 B 层语义事件"""

    def __init__(self, config: dict):
        self.mq = MQClient()
        self.config = config

        from b_layer.identity_tracker import IdentityTracker
        from b_layer.event_aggregator import EventAggregator
        from b_layer.semantic_generator import SemanticGenerator
        from b_layer.context_manager import ContextManager
        from b_layer.identity_fusion import IdentityFusion
        from b_layer.temporal_align import TemporalAlignBuffer

        db_path = str(Path(__file__).parent.parent / "outputs" / "person_cache.db")
        identity_cfg = config.get('identity', {})
        self.tracker = IdentityTracker(
            db_path,
            threshold=identity_cfg.get('face_similarity_threshold', 0.60),
            min_sample_quality=identity_cfg.get('min_sample_quality', 0.40),
            merge_similarity_threshold=identity_cfg.get('merge_similarity_threshold', 0.70),
        )
        self.context_mgr = ContextManager()
        self.aggregator = EventAggregator(config)
        self.generator = SemanticGenerator(config)
        self.fusion = IdentityFusion()
        self.align_buffer = TemporalAlignBuffer(
            on_flush=self._process_aligned_events,
            timeout_sec=180.0,
        )

        self._flush_lock = threading.Lock()
        self.event_count = 0
        self.semantic_count = 0
        self.face_event_count = 0
        self.voice_event_count = 0
        self._last_entity_panel_time = 0.0

        logger.info("B层处理器初始化完成")

    def process_a_event(self, a_event: dict):
        """A层事件入口：scene_detection 直接处理，其余进对齐缓冲区"""
        try:
            self.event_count += 1
            event_type = a_event.get("event_type", "unknown")
            if event_type == "scene_detection":
                ts = a_event.get('time', {}).get('start_ts', '')[:19]
                logger.info(f"[{ts}] #{self.event_count:3d} scene_detection | {a_event.get('subtype', '')}")
                self.aggregator.add_event(a_event)
                if self.aggregator.should_trigger():
                    self._flush_window()
            else:
                self.align_buffer.add(a_event)
        except Exception as e:
            logger.error(f"处理A层事件异常: {e}", exc_info=True)

    def _process_aligned_events(self, events: list):
        """对齐缓冲区 flush 后的回调：对每个事件做身份融合，再送入聚合器"""
        try:
            # 跨模态 alias 合并：同批事件中 face alias ≠ speech alias → 合并到注册库
            face_alias = next((e["payload"].get("alias") for e in events
                               if e.get("event_type") == "face_detection" and e.get("payload", {}).get("alias")), None)
            speech_alias = next((e["payload"].get("alias") for e in events
                                 if e.get("event_type") == "speech_segment" and e.get("payload", {}).get("alias")), None)
            if face_alias and speech_alias and face_alias != speech_alias:
                logger.info(f"[identity] 合并 alias: {speech_alias} → {face_alias}")
                self.tracker.merge_aliases(keep=face_alias, absorb=speech_alias)
                # 把 speech 事件的 alias 统一改为 face_alias
                for e in events:
                    if e.get("event_type") == "speech_segment":
                        e.setdefault("payload", {})["alias"] = face_alias

            for a_event in events:
                self.fusion.fuse_event(a_event)
                event_type = a_event.get("event_type", "unknown")
                ts = a_event.get('time', {}).get('start_ts', '')[:19]
                alias = a_event.get("resolved_alias", "unknown")
                filled = " [aligned]" if a_event.get("_alias_filled_by_align") else ""

                if event_type == 'face_detection':
                    self.face_event_count += 1
                    logger.info(f"[{ts}] face_detection  | alias={alias}{filled}")
                elif event_type == 'speech_segment':
                    self.voice_event_count += 1
                    text = a_event['payload'].get('text', '')[:30]
                    logger.info(f"[{ts}] speech_segment  | alias={alias}{filled} | {text}")

                self.aggregator.add_event(a_event)
            if self.aggregator.should_trigger():
                self._flush_window()
        except Exception as e:
            logger.error(f"_process_aligned_events 异常: {e}", exc_info=True)

    @staticmethod
    def _parse_event_time(event: dict) -> datetime:
        ts_str = event.get('time', {}).get('start_ts', '')
        if ts_str:
            return datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
        return datetime.now()

    def _flush_window(self):
        if not self._flush_lock.acquire(blocking=False):
            return  # 已有线程在 flush，跳过
        try:
            self._flush_window_locked()
        finally:
            self._flush_lock.release()

    def _flush_window_locked(self):
        window_events = self.aggregator.window
        if not window_events:
            return

        # 上下文 & LLM 语义生成
        context = self.context_mgr.get_context()
        window_summary = self.aggregator.get_window_summary()
        llm_result = self.generator.generate(window_events, context)

        # ── 打印 LLM 聚合结果 ──
        t_start = window_summary['start_ts'][11:19] if window_summary['start_ts'] else ''
        t_end = window_summary['end_ts'][11:19] if window_summary['end_ts'] else ''
        face_aliases = window_summary['face_aliases']
        voice_aliases = window_summary['voice_aliases']
        logger.info(f"\n{'─' * _PANEL_WIDTH}")
        logger.info(f"  [LLM 聚合] {t_start} → {t_end}")
        logger.info(f"  face_aliases={face_aliases}  voice_aliases={voice_aliases}")
        logger.info(f"  dialogue_act : {llm_result['dialogue_act']}")
        logger.info(f"  summary      : {llm_result['summary'][:100]}")
        logger.info(f"{'─' * _PANEL_WIDTH}\n")

        # ── Step 4: 构建语义事件 ──
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

        # ── Step 5: 打印语义输出摘要 ──
        self.semantic_count += 1
        out_lines = [
            f"事件 #{self.semantic_count}",
            f"时间   : {t_start} → {t_end}",
            f"实体   : {primary_alias or 'N/A'}",
            f"对话类型: {llm_result['dialogue_act']}",
            f"摘要   : {llm_result['summary'][:80]}...",
        ]
        logger.info("\n" + _panel(out_lines, "语义事件输出"))

        self.mq.publish("b_events", semantic_event)
        self.aggregator.reset()
        self._maybe_log_entity_panel()

    @staticmethod
    def _to_unix(ts_str: str) -> float:
        if not ts_str:
            return 0.0
        ts_str = ts_str.rstrip('Z')
        try:
            dt = datetime.fromisoformat(ts_str)
        except ValueError:
            return 0.0
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.now().astimezone().tzinfo)
        return dt.timestamp()

    def _maybe_log_entity_panel(self):
        now = time.time()
        if now - self._last_entity_panel_time < 5.0:
            return
        self._last_entity_panel_time = now

        state = self.tracker.get_state_summary()
        if not state:
            return

        lines = [f"当前实体数量: {len(state)}"]
        for alias in sorted(state.keys()):
            lines.append(_format_alias_state(state[alias], alias))
        logger.info("\n" + _panel(lines, "实 体 状 态"))

    def run(self):
        logger.info("B层启动，订阅 a_events 队列...")
        self.mq.subscribe("a_events", self.process_a_event)

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            state = self.tracker.get_state_summary()
            final_lines = [
                f"处理 A 层事件: {self.event_count}",
                f"  face_events: {self.face_event_count}",
                f"  voice_events: {self.voice_event_count}",
                f"生成 B 层语义事件: {self.semantic_count}",
                f"最终实体数量: {len(state)}",
            ]
            for alias in sorted(state.keys()):
                final_lines.append(_format_alias_state(state[alias], alias))
            logger.info("\n" + _panel(final_lines, "B层关闭统计"))
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
