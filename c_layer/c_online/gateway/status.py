"""系统状态监控 — GET /api/status + WS /api/status/ws"""
import json
import asyncio
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from c_layer.c_online.gateway.response import ok
from shared.mq_client import MQClient

router = APIRouter()

# 全局反思标志（由 ReflectionScheduler 设置）
_reflecting = False

# 视频处理状态（由 video.py 设置）
_video_status: Optional[dict] = None


def set_reflecting(value: bool):
    global _reflecting
    _reflecting = value


def set_video_status(status: Optional[dict]):
    global _video_status
    _video_status = status


def get_system_state() -> dict:
    """查询系统完整状态"""
    # 1. Broker 队列状态
    try:
        client = MQClient()
        resp = client._send_and_recv({"op": "status"})
        broker_status = json.loads(resp["data"])
    except Exception:
        broker_status = {"queues": {}, "waiters": {}, "connections": 0}

    queues = broker_status.get("queues", {})
    is_working = any(v > 0 for v in queues.values())

    # 2. 组合状态
    states = []
    if _video_status and _video_status.get("status") == "processing":
        is_working = True
    if is_working:
        states.append("WORKING")
    if _reflecting:
        states.append("ORGANIZING")
    if not states:
        states.append("SLEEPING")

    # 3. 构造响应
    result = {
        "state": states[0] if len(states) == 1 else states[0],
        "states": states,
        "queues": queues,
        "video_processing": _video_status,
        "reflecting": _reflecting,
        "layer_status": {
            "broker": "running" if broker_status.get("connections", 0) >= 0 else "stopped",
            "b_layer": "running" if "b_events" in queues or "a_events" in queues else "unknown",
            "c_layer": "running" if "opportunities" in queues or "b_events" in queues else "unknown",
            "d_layer": "running" if "execution_plans" in queues or "opportunities" in queues else "unknown",
            "e_layer": "running" if "execution_plans" in queues else "unknown",
        },
        "updated_at": datetime.now().isoformat(),
    }
    return result


@router.get("/api/status")
async def status_poll():
    return ok(get_system_state())


@router.websocket("/api/status/ws")
async def status_websocket(ws: WebSocket):
    await ws.accept()
    try:
        while True:
            state = get_system_state()
            await ws.send_json(state)
            try:
                msg = await asyncio.wait_for(ws.receive_json(), timeout=2.0)
                if msg.get("type") == "ping":
                    await ws.send_json({"type": "pong"})
            except asyncio.TimeoutError:
                pass
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
