"""
时间对齐缓冲区：基于双水位线的事件对齐。

逻辑：
- face_detection 和 speech_segment 各自维护一个水位线（最新到达事件的 end_ts）
- 每次任一队列更新水位线后，取 min(face_watermark, speech_watermark)
- 两个队列中所有 end_ts <= min_watermark 的事件一起 flush
- 超过 timeout_sec 未被 flush 的事件强制 flush
"""
from datetime import datetime
from typing import List, Dict, Callable, Optional
import threading
import time
import logging

_log = logging.getLogger("IranHeart.b_layer.align")
_log.setLevel(logging.DEBUG)
_log.propagate = False
_align_fh = logging.FileHandler(
    str(__import__("pathlib").Path(__file__).parent.parent / "logs" / "b_layer_align.log"),
    encoding="utf-8"
)
_align_fh.setLevel(logging.DEBUG)
_align_fh.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s - %(message)s", datefmt="%H:%M:%S"))
_log.addHandler(_align_fh)


def _parse_ts(ts_str: str) -> float:
    try:
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def _event_end_ts(event: Dict) -> float:
    t = event.get("time", {})
    return _parse_ts(t.get("end_ts", "") or t.get("start_ts", ""))


class TemporalAlignBuffer:

    def __init__(self, on_flush: Callable[[List[Dict]], None], timeout_sec: float = 180.0):
        self.on_flush = on_flush
        self.timeout_sec = timeout_sec
        self._face_queue: List[Dict] = []    # {"event": ..., "arrived_at": float}
        self._speech_queue: List[Dict] = []  # {"event": ..., "arrived_at": float}
        self._face_watermark: float = 0.0
        self._speech_watermark: float = 0.0
        self._lock = threading.Lock()
        threading.Thread(target=self._timeout_loop, daemon=True).start()

    def add(self, event: Dict):
        et = event.get("event_type", "")
        if et == "face_detection":
            self._add_face(event)
        elif et == "speech_segment":
            self._add_speech(event)
        else:
            threading.Thread(target=self.on_flush, args=([event],), daemon=True).start()

    def _add_face(self, event: Dict):
        end_ts = _event_end_ts(event)
        ts = event.get("time", {}).get("start_ts", "")[:19]
        to_flush = None
        with self._lock:
            self._face_queue.append({"event": event, "arrived_at": time.time()})
            if end_ts > self._face_watermark:
                self._face_watermark = end_ts
            _log.debug(f"[align] face ADD ts={ts} face_wm={self._face_watermark:.1f} speech_wm={self._speech_watermark:.1f}")
            to_flush = self._try_flush()
        if to_flush:
            threading.Thread(target=self.on_flush, args=(to_flush,), daemon=True).start()

    def _add_speech(self, event: Dict):
        end_ts = _event_end_ts(event)
        ts = event.get("time", {}).get("start_ts", "")[:19]
        to_flush = None
        with self._lock:
            self._speech_queue.append({"event": event, "arrived_at": time.time()})
            if end_ts > self._speech_watermark:
                self._speech_watermark = end_ts
            _log.debug(f"[align] speech ADD ts={ts} face_wm={self._face_watermark:.1f} speech_wm={self._speech_watermark:.1f}")
            to_flush = self._try_flush()
        if to_flush:
            threading.Thread(target=self.on_flush, args=(to_flush,), daemon=True).start()

    def _try_flush(self) -> Optional[List[Dict]]:
        """在锁内调用。取 min 水位线，flush 两队列中所有 end_ts <= min_wm 的事件。"""
        if self._face_watermark == 0.0 or self._speech_watermark == 0.0:
            return None  # 任一队列还没有事件，不 flush
        min_wm = min(self._face_watermark, self._speech_watermark)
        ready_f = [i for i in self._face_queue if _event_end_ts(i["event"]) <= min_wm]
        ready_s = [i for i in self._speech_queue if _event_end_ts(i["event"]) <= min_wm]
        if not ready_f or not ready_s:
            return None
        self._face_queue = [i for i in self._face_queue if _event_end_ts(i["event"]) > min_wm]
        self._speech_queue = [i for i in self._speech_queue if _event_end_ts(i["event"]) > min_wm]
        events = [i["event"] for i in ready_f + ready_s]
        events.sort(key=lambda e: e.get("time", {}).get("start_ts", ""))
        self._align_aliases(events)
        _log.debug(f"[align] FLUSH {len(ready_f)} face(s) + {len(ready_s)} speech(es) at min_wm={min_wm:.1f}")
        return events

    @staticmethod
    def _align_aliases(events: List[Dict]):
        face_alias = next(
            (e["payload"].get("alias") for e in events
             if e.get("event_type") == "face_detection" and e.get("payload", {}).get("alias")),
            None
        )
        voice_alias = next(
            (e["payload"].get("alias") for e in events
             if e.get("event_type") == "speech_segment" and e.get("payload", {}).get("alias")),
            None
        )
        unified = face_alias or voice_alias
        if not unified:
            return
        for e in events:
            if e.get("event_type") in ("face_detection", "speech_segment"):
                if not e.get("payload", {}).get("alias"):
                    e.setdefault("payload", {})["alias"] = unified
                    e["_alias_filled_by_align"] = True

    def _timeout_loop(self):
        while True:
            time.sleep(5)
            now = time.time()
            to_flush = None
            with self._lock:
                expired_f = [i for i in self._face_queue if now - i["arrived_at"] >= self.timeout_sec]
                expired_s = [i for i in self._speech_queue if now - i["arrived_at"] >= self.timeout_sec]
                self._face_queue = [i for i in self._face_queue if now - i["arrived_at"] < self.timeout_sec]
                self._speech_queue = [i for i in self._speech_queue if now - i["arrived_at"] < self.timeout_sec]
                if expired_f or expired_s:
                    all_expired = [i["event"] for i in expired_f + expired_s]
                    all_expired.sort(key=lambda e: e.get("time", {}).get("start_ts", ""))
                    self._align_aliases(all_expired)
                    to_flush = all_expired
                    _log.debug(f"[align] TIMEOUT flush {len(expired_f)} face(s) + {len(expired_s)} speech(es)")
            if to_flush:
                threading.Thread(target=self.on_flush, args=(to_flush,), daemon=True).start()
