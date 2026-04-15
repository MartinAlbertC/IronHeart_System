from typing import List, Dict, Optional, Set, Tuple
from datetime import datetime


class EventAggregator:
    def __init__(self, config: Dict):
        self.min_window = config['aggregation']['min_window_seconds']
        self.max_window = config['aggregation']['max_window_seconds']
        self.person_change_delay = config['aggregation']['person_change_delay']
        self.window: List[Dict] = []
        self.window_persons: set = set()
        self._pending_cross_modal_merges: List[Tuple[str, str]] = []

    def add_event(self, event: Dict):
        self.window.append(event)
        if 'resolved_alias' in event:
            self.window_persons.add(event['resolved_alias'])

    def should_trigger(self) -> bool:
        if not self.window:
            return False

        start_time = self._parse_time(self.window[0]['time']['start_ts'])
        end_time = self._parse_time(self.window[-1]['time']['end_ts'])
        duration = (end_time - start_time).total_seconds()

        if duration < self.min_window:
            return False

        if duration > self.max_window:
            return True

        # Check for person change
        if len(self.window) > 1:
            last_event = self.window[-1]
            if 'resolved_alias' in last_event:
                prev_persons = set()
                for e in self.window[:-1]:
                    if 'resolved_alias' in e:
                        prev_persons.add(e['resolved_alias'])
                if last_event['resolved_alias'] not in prev_persons:
                    return True

        return False

    def detect_cross_modal_merges(self) -> List[Tuple[str, str]]:
        """
        检测当前窗口中需要合并的 alias 对。
        返回 [(keep_alias, absorb_alias), ...]

        场景：同一时间窗口内，同一个人被识别为不同的 alias
        - face 检测到一个 alias（可能是通过跨模态推断得到的）
        - voice 检测到另一个 alias
        这意味着这两个 alias 应该合并为同一个人
        """
        face_aliases: Set[str] = set()
        voice_aliases: Set[str] = set()

        for e in self.window:
            alias = e.get('resolved_alias')
            if not alias:
                continue
            if e['event_type'] == 'face_detection':
                face_aliases.add(alias)
            elif e['event_type'] == 'speech_segment':
                voice_aliases.add(alias)

        # 如果两个模态都检测到了alias，但彼此不同 → 应该合并
        # face_aliases = {A, B}, voice_aliases = {C}
        # A != C，说明可能是同一个人被分配了不同alias
        merges = []
        if face_aliases and voice_aliases:
            # 取出现最多的 face_alias 和 voice_alias 作为主
            for fa in face_aliases:
                for va in voice_aliases:
                    if fa != va:
                        # 保留字典序较小的作为主 alias（更稳定的命名）
                        merges.append((min(fa, va), max(fa, va)))

        return merges

    def get_window_summary(self) -> Dict:
        """返回当前窗口的简要信息"""
        face_count = sum(1 for e in self.window if e.get('event_type') == 'face_detection')
        voice_count = sum(1 for e in self.window if e.get('event_type') == 'speech_segment')
        scene_count = sum(1 for e in self.window if e.get('event_type') == 'scene_detection')

        face_aliases = {e['resolved_alias'] for e in self.window
                        if e.get('event_type') == 'face_detection' and 'resolved_alias' in e}
        voice_aliases = {e['resolved_alias'] for e in self.window
                         if e.get('event_type') == 'speech_segment' and 'resolved_alias' in e}

        start_ts = self.window[0]['time']['start_ts'] if self.window else None
        end_ts = self.window[-1]['time']['end_ts'] if self.window else None

        return {
            'total_events': len(self.window),
            'face_events': face_count,
            'voice_events': voice_count,
            'scene_events': scene_count,
            'face_aliases': sorted(face_aliases),
            'voice_aliases': sorted(voice_aliases),
            'start_ts': start_ts,
            'end_ts': end_ts,
        }

    @staticmethod
    def _parse_time(ts_str: str) -> datetime:
        return datetime.fromisoformat(ts_str.replace('Z', '+00:00'))

    def reset(self):
        """清空聚合窗口，在 flush 后调用"""
        self.window = []
        self.window_persons = set()
        self._pending_cross_modal_merges = []
