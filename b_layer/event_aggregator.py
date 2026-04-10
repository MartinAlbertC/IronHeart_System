from typing import List, Dict, Optional
from datetime import datetime, timedelta

class EventAggregator:
    def __init__(self, config: Dict):
        self.min_window = config['aggregation']['min_window_seconds']
        self.max_window = config['aggregation']['max_window_seconds']
        self.person_change_delay = config['aggregation']['person_change_delay']
        self.window: List[Dict] = []
        self.window_persons: set = set()

    def add_event(self, event: Dict):
        self.window.append(event)
        if 'resolved_alias' in event:
            self.window_persons.add(event['resolved_alias'])

    def should_trigger(self) -> bool:
        if not self.window:
            return False

        start_time = datetime.fromisoformat(self.window[0]['time']['start_ts'].replace('Z', '+00:00'))
        end_time = datetime.fromisoformat(self.window[-1]['time']['end_ts'].replace('Z', '+00:00'))
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

    def reset(self):
        """清空聚合窗口，在 flush 后调用"""
        self.window = []
        self.window_persons = set()
