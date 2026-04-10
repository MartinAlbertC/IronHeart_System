/** D 层传入的完整数据结构 */
export interface DLayerInput {
    plan_id: string;
    opportunity_id: string;
    /** 语义事件 payload */
    payload: DLayerPayload;
    /** LLM 生成上下文（三层记忆 + 认知状态） */
    llm_context: DLayerLLMContext;
    /** D 层决策元数据 */
    d_layer_decision: 'execute_now' | 'deferred_execute';
}
/** D 层 payload — 语义事件描述 */
export interface DLayerPayload {
    /** 语义类型，e.g. "conversation_act" */
    semantic_type: string;
    /** C 层实体对齐结果，可能为 undefined（首次见面） */
    resolved_entity_id?: string;
    /** 触发事件摘要 */
    trigger_summary: string;
}
/** D 层 LLM 上下文 — 供 E 层行动规划 LLM 参考 */
export interface DLayerLLMContext {
    /** Tier 1: 用户底线与偏好 */
    user_persona: {
        health?: string;
        preferences?: string;
    };
    /** Tier 2: 相关长期记忆（多条） */
    historical_memories: string[];
    /** Tier 3: 近期事件时间线 */
    recent_events: string[];
    /** 情景缓冲区：当前主观认知语境 */
    current_cognitive_episode: string;
}
//# sourceMappingURL=dLayerInput.d.ts.map