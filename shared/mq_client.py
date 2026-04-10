"""
MQ 客户端封装
- 基于 message_queue/broker.py 的 TCP + JSON 协议
- 自动重连
- 发布 / 阻塞接收 / 订阅（后台线程轮询）
- 通信日志记录到 mq_comm.log

协议格式（与 broker.py 对齐）：
  send: {"op":"send", "queue":"xxx", "data":"json_string"}\\n
  recv: {"op":"recv", "queue":"xxx"}\\n  → 阻塞等待响应
  响应: {"status":"ok", "data":"..."}\\n 或 {"status":"error","message":"..."}\\n
"""

import json
import socket
import threading
import time
import sys
from pathlib import Path
from typing import Callable, Dict, Any, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from shared.logger import get_mq_logger

logger = get_mq_logger()


class MQClient:
    """
    轻量 TCP 消息队列客户端

    每次 send / recv 使用独立 TCP 连接（与 broker 的协议一致），
    避免长连接阻塞问题。
    """

    def __init__(self, host: str = "localhost", port: int = 6380):
        self.host = host
        self.port = port

    # ── 内部工具 ──

    def _open(self) -> socket.socket:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((self.host, self.port))
        return sock

    def _send_and_recv(self, payload: dict, sock: Optional[socket.socket] = None) -> dict:
        """发送一条 JSON 并读取一行 JSON 响应"""
        own_sock = sock is None
        if own_sock:
            sock = self._open()
        try:
            sock.sendall((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
            buf = b""
            while True:
                chunk = sock.recv(8192)
                if not chunk:
                    raise ConnectionError("MQ 连接已断开")
                buf += chunk
                if b"\n" in buf:
                    break
            line = buf.split(b"\n")[0].decode("utf-8").strip()
            return json.loads(line)
        finally:
            if own_sock:
                sock.close()

    # ── 公开 API ──

    def publish(self, queue_name: str, message: Dict[str, Any]) -> bool:
        """
        发布消息到指定队列

        Args:
            queue_name: 队列名
            message: 消息字典（会被序列化为 JSON）

        Returns:
            是否发布成功
        """
        data_str = json.dumps(message, ensure_ascii=False)
        try:
            resp = self._send_and_recv({
                "op": "send",
                "queue": queue_name,
                "data": data_str,
            })
            if resp.get("status") == "ok":
                logger.info(f"[PUB→{queue_name}] 成功 | 大小={len(data_str)} 字节")
                return True
            else:
                logger.error(f"[PUB→{queue_name}] 失败: {resp}")
                return False
        except Exception as e:
            logger.error(f"[PUB→{queue_name}] 异常: {e}")
            return False

    def receive(self, queue_name: str) -> Optional[Dict]:
        """
        从指定队列阻塞接收一条消息

        Args:
            queue_name: 队列名

        Returns:
            消息字典，或 None（连接异常时）
        """
        try:
            sock = self._open()
            resp = self._send_and_recv({"op": "recv", "queue": queue_name}, sock=sock)
            sock.close()
            if resp.get("status") == "ok" and "data" in resp:
                msg = json.loads(resp["data"]) if isinstance(resp["data"], str) else resp["data"]
                logger.info(f"[RECV←{queue_name}] 成功")
                return msg
            else:
                logger.warning(f"[RECV←{queue_name}] 响应异常: {resp}")
                return None
        except Exception as e:
            logger.error(f"[RECV←{queue_name}] 异常: {e}")
            return None

    def subscribe(self, queue_name: str, callback: Callable[[Dict], None]):
        """
        订阅队列：在后台线程中持续 receive，有消息时调用 callback

        Args:
            queue_name: 队列名
            callback: 消息回调函数，接收消息字典

        Returns:
            后台线程对象（daemon=True）
        """
        def _loop():
            logger.info(f"[SUB→{queue_name}] 订阅线程启动")
            while True:
                try:
                    msg = self.receive(queue_name)
                    if msg is not None:
                        try:
                            callback(msg)
                        except Exception as cb_err:
                            logger.error(f"[SUB→{queue_name}] 回调异常: {cb_err}")
                except Exception as e:
                    logger.error(f"[SUB→{queue_name}] 接收异常: {e}，1s 后重试")
                    time.sleep(1)

        t = threading.Thread(target=_loop, daemon=True, name=f"MQ-Sub-{queue_name}")
        t.start()
        logger.info(f"[SUB→{queue_name}] 订阅已注册")
        return t
