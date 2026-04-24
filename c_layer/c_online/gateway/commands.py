"""用户直接指令路由 — POST /api/command"""
import uuid
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from c_layer.c_online.gateway.response import ok, ApiError
from c_layer.config import PG_CONFIG
from shared.mq_client import MQClient

router = APIRouter()


class CommandRequest(BaseModel):
    text: str = Field(..., description="指令内容", examples=["提醒我下午3点开会"])
    type: Optional[str] = Field("text", description="指令类型: text/voice")


@router.post("/api/command")
async def send_command(body: CommandRequest):
    text = body.text.strip()
    cmd_type = body.type or "text"
    if not text:
        raise ApiError(40001, "指令内容不能为空")

    command_id = f"cmd_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"

    # 1. 查询相关记忆（复用 OpportunityBuilder 的查询逻辑）
    from c_layer.c_online.opportunity_builder import OpportunityBuilder
    builder = OpportunityBuilder()

    tier1 = builder._query_tier1("default_user")
    tier2 = builder._query_tier2("entity_0001", limit=5)
    tier3 = builder._query_tier3_recent(limit=5)

    # 2. 构造 Opportunity（标记 skip_decision=True）
    opportunity = {
        "opportunity_id": f"opp_cmd_{uuid.uuid4().hex[:8]}",
        "created_at": datetime.now().isoformat(),
        "trigger": {
            "semantic_event_id": command_id,
            "resolved_entity_id": "entity_0001",
            "semantic_type": "user_command",
            "summary": text,
        },
        "context": {
            "tier1_persona": tier1,
            "tier2_memories": tier2,
            "tier3_events": tier3,
        },
        "source": "command",
        "skip_decision": True,
    }

    # 3. 发送到 command_opportunities 优先队列（D 层优先处理）
    mq = MQClient()
    mq.publish("command_opportunities", opportunity)

    return ok({
        "command_id": command_id,
        "status": "processing",
        "message": "指令已接收，正在生成行动卡片",
    })
