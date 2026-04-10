# -*- coding: utf-8 -*-
"""
D Layer Data Models
使用 Pydantic 定义所有数据结构
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, PrivateAttr
import numpy as np


# ============================================================
# D 层输入格式 (来自 C 层)
# ============================================================

class TriggerInfo(BaseModel):
    """触发信息"""
    semantic_event_id: str = Field(..., description="语义事件ID")
    resolved_entity_id: str = Field(..., description="解析后的实体ID")
    semantic_type: str = Field(..., description="语义类型: conversation_act/reminder/notification等")
    summary: str = Field(..., description="触发事件摘要")


class Tier1Persona(BaseModel):
    """Tier 1 用户画像片段 (新格式)"""
    critical_facts: Dict[str, Any] = Field(default_factory=dict, description="关键事实")


class Tier1PersonaLegacy(BaseModel):
    """Tier 1 核心画像 (旧格式，用于兼容)"""
    health_constraints: List[str] = Field(default_factory=list, description="健康禁忌")
    core_goals: List[str] = Field(default_factory=list, description="核心目标")
    emotional_state: List[str] = Field(default_factory=list, description="情绪状态")
    preferences: List[str] = Field(default_factory=list, description="偏好")
    raw_text: str = Field("", description="原始画像文本，用于Prompt")


class Tier2MemoryItem(BaseModel):
    """Tier 2 长期记忆项"""
    memory_text: str
    base_importance: float = 0.5


class Tier3EventItem(BaseModel):
    """Tier 3 短期事件项"""
    summary: str
    time: str


class OpportunityContext(BaseModel):
    """Opportunity 上下文"""
    tier1_persona: Optional[Tier1Persona] = None
    tier2_memories: List[Tier2MemoryItem] = Field(default_factory=list)
    tier3_events: List[Tier3EventItem] = Field(default_factory=list)


class Opportunity(BaseModel):
    """
    D 层输入: C 层传递的机会事件
    """
    opportunity_id: str = Field(..., description="机会ID，如 opp_20260325_001")
    created_at: datetime = Field(default_factory=datetime.now)
    trigger: TriggerInfo
    context: OpportunityContext = Field(default_factory=OpportunityContext)

    # 内部使用的 embedding (使用 PrivateAttr)
    _embedding: Optional[np.ndarray] = PrivateAttr(default=None)

    @property
    def embedding(self) -> Optional[np.ndarray]:
        return self._embedding

    @embedding.setter
    def embedding(self, value: np.ndarray):
        self._embedding = value

    def get_content_for_embedding(self) -> str:
        """获取用于embedding的内容"""
        return self.trigger.summary

    class Config:
        arbitrary_types_allowed = True


# ============================================================
# D 层输出格式 (发给 E 层)
# ============================================================

class ExecutionPayload(BaseModel):
    """
    D 层输出: 发给 E 层的执行计划
    """
    plan_id: str = Field(..., description="计划ID")
    opportunity_id: str = Field(..., description="对应的 Opportunity ID")

    # payload: 沿用 trigger，供 E 层确定执行意图
    payload: Dict[str, Any] = Field(default_factory=dict)

    # llm_context: 融合事实与心境，供生成文案使用
    llm_context: Dict[str, Any] = Field(default_factory=dict)

    # D 层决策
    d_layer_decision: str = Field(..., description="execute_now / deferred_execute")

    class Config:
        arbitrary_types_allowed = True


# ============================================================
# 工作记忆内部模型
# ============================================================

class PMItem(BaseModel):
    """
    感知记忆 (Perception Memory) 项
    容量: 7个槽位
    """
    id: int  # 使用 id 而不是 pm_id，保持与现有代码兼容
    content: str
    embedding: np.ndarray
    timestamp: datetime = Field(default_factory=datetime.now)

    # 综合得分组成部分
    recency_score: float = Field(1.0, description="新近度得分 (0-1)")
    relevance_score: float = Field(0.5, description="与WM的相关性得分 (0-1)")
    importance_score: float = Field(0.5, description="重要性得分 (0-1)")

    def calculate_score(self) -> float:
        """
        计算综合得分 S = 0.3 * Recency + 0.4 * Relevance_wm + 0.3 * Importance
        """
        return 0.3 * self.recency_score + 0.4 * self.relevance_score + 0.3 * self.importance_score

    class Config:
        arbitrary_types_allowed = True


class EBChunk(BaseModel):
    """
    情景缓冲区 (Episodic Buffer) 组块
    容量: 4个组块
    """
    id: int  # 使用 id 而不是 chunk_id
    summary: str = Field(..., description="组块的语义摘要")
    member_ids: List[int] = Field(default_factory=list, description="属于该组块的PM项ID列表")
    embedding: Optional[np.ndarray] = Field(None, description="组块摘要的向量表示")
    avg_score: float = Field(0.5, description="组块内成员的平均得分")

    @property
    def chunk_id(self) -> int:
        """兼容性属性"""
        return self.id

    @property
    def member_pm_ids(self) -> List[int]:
        """兼容性属性"""
        return self.member_ids

    def update_avg_score(self, pm_items: List['PMItem']):
        """根据成员PM项更新平均得分"""
        if not self.member_ids or not pm_items:
            self.avg_score = 0.5
            return
        member_scores = [item.calculate_score() for item in pm_items if item.id in self.member_ids]
        self.avg_score = sum(member_scores) / len(member_scores) if member_scores else 0.5

    class Config:
        arbitrary_types_allowed = True


class PendingItem(BaseModel):
    """
    延迟队列 (Pending Pool) 项
    """
    opportunity: Opportunity
    utility: float = Field(..., description="入池时的效用值")
    deferred_at: datetime = Field(default_factory=datetime.now)
    ttl_expired_at: datetime = Field(..., description="TTL过期时间")

    # 缓存的值，用于重估时保持不变
    cached_imp: float = Field(..., description="缓存的重要性得分")
    cached_rel_his: float = Field(..., description="缓存的历史相关性")

    def is_expired(self) -> bool:
        """检查是否已超过TTL"""
        return datetime.now() > self.ttl_expired_at

    class Config:
        arbitrary_types_allowed = True


# ============================================================
# 决策结果
# ============================================================

class DecisionResult(BaseModel):
    """
    决策结果
    """
    action: str = Field(..., description="EXECUTE / DEFER / DISCARD")
    utility: float
    utility_breakdown: dict = Field(default_factory=dict, description="效用值分解")
    payload: Optional[ExecutionPayload] = None
    reason: str = Field("", description="决策原因说明")


class WMState(BaseModel):
    """
    工作记忆状态快照 (用于日志和调试)
    """
    pm_items: List[dict] = Field(default_factory=list)
    eb_chunks: List[dict] = Field(default_factory=list)
    pending_count: int = 0
    timestamp: datetime = Field(default_factory=datetime.now)


# ============================================================
# 兼容性别名 (用于向后兼容)
# ============================================================

class LLMContext(BaseModel):
    """LLM上下文 (兼容性类)"""
    user_persona: str = Field("", description="用户画像文本")
    historical_memories: List[str] = Field(default_factory=list, description="历史记忆")
    recent_events: List[str] = Field(default_factory=list, description="最近事件")
    current_cognitive_episode: Optional[str] = Field(None, description="当前认知情景")

    def to_dict(self) -> dict:
        return {
            "user_persona": self.user_persona,
            "historical_memories": self.historical_memories,
            "recent_events": self.recent_events,
            "current_cognitive_episode": self.current_cognitive_episode
        }


# 旧的 CLayerMemory 类 (兼容性)
class CLayerMemoryLegacy(BaseModel):
    """C层记忆 (旧格式，用于兼容)"""
    tier1: 'Tier1Persona' = Field(default_factory=Tier1Persona)
    tier2: List['Tier2MemoryLegacy'] = Field(default_factory=list)
    tier3: List['Tier3EventLegacy'] = Field(default_factory=list)

    def get_tier1_text(self) -> str:
        return str(self.tier1.critical_facts) if self.tier1 else ""

    def get_tier2_embeddings(self) -> Optional[np.ndarray]:
        embeddings = [m.embedding for m in self.tier2 if m.embedding is not None]
        return np.array(embeddings) if embeddings else None

    def get_tier3_embeddings(self) -> Optional[np.ndarray]:
        embeddings = [e.embedding for e in self.tier3 if e.embedding is not None]
        return np.array(embeddings) if embeddings else None

    class Config:
        arbitrary_types_allowed = True


class Tier2MemoryLegacy(BaseModel):
    """Tier 2 长期记忆 (旧格式)"""
    id: int
    content: str
    importance: float = 0.5
    embedding: Optional[np.ndarray] = None
    timestamp: Optional[datetime] = None

    class Config:
        arbitrary_types_allowed = True


class Tier3EventLegacy(BaseModel):
    """Tier 3 短期事件 (旧格式)"""
    id: int
    summary: str
    timestamp: datetime
    embedding: Optional[np.ndarray] = None

    class Config:
        arbitrary_types_allowed = True


# 别名
CLayerMemory = CLayerMemoryLegacy
