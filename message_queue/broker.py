#!/usr/bin/env python3
"""
IranHeart 轻量异步 TCP 消息队列 Broker

队列定义：
  a_events          A层 → B层    (原始感知事件)
  b_events          B层 → C层    (语义聚合事件)
  opportunities     C层 → D层    (Opportunity 对象)
  execution_plans   D层 → E层    (执行计划)

协议：Newline-delimited JSON over TCP
  send: {"op":"send", "queue":"queue_name", "data":"json_string"}\n
  recv: {"op":"recv", "queue":"queue_name"}\n  (blocks until available)
  响应: {"status":"ok"}\n 或 {"status":"ok","data":"json_string"}\n
"""

import asyncio
import json
import logging
import sys
import os
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Set, Tuple
from datetime import datetime

# 使 shared 可导入
sys.path.insert(0, str(Path(__file__).parent.parent))

# ── 日志 ──
LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / "broker.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("broker")


class MessageBroker:
    """异步 FIFO 消息代理，支持竞争消费者"""

    # ── 预定义队列 ──
    KNOWN_QUEUES = {"a_events", "b_events", "opportunities", "execution_plans"}

    def __init__(self):
        self.queues: Dict[str, List[str]] = defaultdict(list)
        self.waiters: Dict[str, List[Tuple[asyncio.StreamReader, asyncio.Future]]] = defaultdict(list)
        self.active_connections: Set[asyncio.StreamReader] = set()
        self.queue_lock = asyncio.Lock()

    async def send_message(self, queue: str, data: str) -> bool:
        async with self.queue_lock:
            if queue in self.waiters and self.waiters[queue]:
                reader, future = self.waiters[queue].pop(0)
                if not future.done():
                    future.set_result(data)
                logger.info(f"[{queue}] 直接投递给等待消费者 | 等待数={len(self.waiters[queue])}")
                return True
            else:
                self.queues[queue].append(data)
                logger.info(f"[{queue}] 入队 | 队列深度={len(self.queues[queue])}")
                return False

    async def recv_message(self, queue: str, reader: asyncio.StreamReader) -> str:
        async with self.queue_lock:
            if queue in self.queues and self.queues[queue]:
                data = self.queues[queue].pop(0)
                logger.info(f"[{queue}] 出队 | 剩余={len(self.queues[queue])}")
                return data

        logger.info(f"[{queue}] 无消息，消费者等待中...")
        future = asyncio.Future()
        async with self.queue_lock:
            self.waiters[queue].append((reader, future))

        try:
            data = await future
            logger.info(f"[{queue}] 等待消费者收到消息")
            return data
        finally:
            async with self.queue_lock:
                if (reader, future) in self.waiters[queue]:
                    self.waiters[queue].remove((reader, future))

    async def cleanup_connection(self, reader: asyncio.StreamReader):
        if reader in self.active_connections:
            self.active_connections.remove(reader)
            logger.info(f"连接断开 | 活跃连接={len(self.active_connections)}")
        async with self.queue_lock:
            for qn in list(self.waiters.keys()):
                self.waiters[qn] = [
                    (r, f) for r, f in self.waiters[qn]
                    if r is not reader or not f.done()
                ]

    def get_status(self) -> dict:
        return {
            "queues": {q: len(msgs) for q, msgs in self.queues.items()},
            "waiters": {q: len(w) for q, w in self.waiters.items()},
            "connections": len(self.active_connections),
        }


class ClientHandler:
    def __init__(self, reader, writer, broker: MessageBroker):
        self.reader = reader
        self.writer = writer
        self.broker = broker
        self.addr = writer.get_extra_info("peername")

    async def _respond(self, resp: dict):
        try:
            self.writer.write((json.dumps(resp, ensure_ascii=False) + "\n").encode("utf-8"))
            await self.writer.drain()
        except (ConnectionError, BrokenPipeError):
            pass

    async def handle_request(self, request: dict):
        op = request.get("op")
        if op == "send":
            queue = request.get("queue")
            data = request.get("data")
            if not queue or data is None:
                await self._respond({"status": "error", "message": "Missing queue/data"})
                return
            await self.broker.send_message(queue, data)
            await self._respond({"status": "ok"})

        elif op == "recv":
            queue = request.get("queue")
            if not queue:
                await self._respond({"status": "error", "message": "Missing queue"})
                return
            try:
                data = await self.broker.recv_message(queue, self.reader)
                await self._respond({"status": "ok", "data": data})
            except asyncio.CancelledError:
                pass

        elif op == "status":
            await self._respond({"status": "ok", "data": json.dumps(self.broker.get_status())})

        else:
            await self._respond({"status": "error", "message": f"Unknown op: {op}"})

    async def run(self):
        self.broker.active_connections.add(self.reader)
        logger.info(f"新连接 {self.addr} | 活跃连接={len(self.broker.active_connections)}")
        try:
            while True:
                line = await self.reader.readline()
                if not line:
                    break
                text = line.decode("utf-8").strip()
                if not text:
                    continue
                try:
                    await self.handle_request(json.loads(text))
                except json.JSONDecodeError as e:
                    await self._respond({"status": "error", "message": f"Invalid JSON: {e}"})
                except Exception as e:
                    await self._respond({"status": "error", "message": str(e)})
        except (ConnectionError, BrokenPipeError, asyncio.IncompleteReadError):
            pass
        finally:
            await self.broker.cleanup_connection(self.reader)
            try:
                self.writer.close()
                await self.writer.wait_closed()
            except Exception:
                pass


async def main():
    broker = MessageBroker()
    server = await asyncio.start_server(
        lambda r, w: ClientHandler(r, w, broker).run(),
        "0.0.0.0", 6380,
    )
    logger.info("=" * 50)
    logger.info("IranHeart Message Broker 已启动 0.0.0.0:6380")
    logger.info(f"预定义队列: {broker.KNOWN_QUEUES}")
    logger.info("=" * 50)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Broker 关闭")
