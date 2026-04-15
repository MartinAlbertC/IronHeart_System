"""
时间对齐缓冲区（v2 简化版）

A 层统一管道输出的 face/speech 事件已天然对齐（同一窗口产生），
此处只做简单的批次透传，不再需要双水位线对齐逻辑。

保留类接口兼容性，以便 B 层 run.py 无需修改。
"""
from typing import List, Dict, Callable


class TemporalAlignBuffer:

    def __init__(self, on_flush: Callable[[List[Dict]], None], timeout_sec: float = 180.0):
        self.on_flush = on_flush

    def add(self, event: Dict):
        """直接透传到 on_flush 回调（A 层已对齐，无需缓冲）"""
        self.on_flush([event])
