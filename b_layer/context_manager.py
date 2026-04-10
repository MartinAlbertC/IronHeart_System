from typing import List, Dict, Optional
from datetime import datetime, timedelta

class ContextManager:
    def __init__(self):
        self.scene_label: Optional[str] = None
        self.active_persons: List[str] = []
        self.recent_activity: Optional[str] = None
        self.last_update: Optional[datetime] = None

    def update(self, event: Dict):
        self.last_update = datetime.fromisoformat(event['time']['start_ts'].replace('Z', '+00:00'))

        if event['event_type'] == 'scene_detection':
            self.scene_label = event['payload'].get('scene_label', 'unknown')

        elif event['event_type'] == 'speech_segment':
            self.recent_activity = 'speaking'

        elif event['event_type'] == 'face_detection':
            if 'resolved_alias' in event and event['resolved_alias'] not in self.active_persons:
                self.active_persons.append(event['resolved_alias'])

    def get_context(self) -> Dict:
        return {
            'scene_label': self.scene_label or 'unknown',
            'active_persons': self.active_persons.copy(),
            'recent_activity': self.recent_activity
        }
