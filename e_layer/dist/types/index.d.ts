/**
 * D 层传入的 LLM 生成上下文
 * 仅飞书场景使用，供消息生成模型参考；Calendar 场景不传此字段
 */
export interface LLMContext {
    /** D 层触发此 Plan 的事件摘要，e.g. "用户深夜抱怨毕设进度，情绪焦躁" */
    trigger_summary: string;
    /** 用户硬约束列表，生成内容绝对不能违反，e.g. ["高血糖", "戒糖中", "极度讨厌被打断"] */
    user_constraints: string[];
    /** 与本次事件直接相关的长期记忆摘要，供模型理解背景 */
    relevant_memory?: string;
    /** 用户当前瞬时状态描述，e.g. "连续看屏幕 180 分钟，5 分钟前打开了外卖软件" */
    current_state?: string;
}
/** D 层自身的决策元数据 */
export interface DLayerMeta {
    /** D 层决策结果："execute_now" 表示立即执行 */
    decision: 'execute_now';
    /** D 层综合置信度 (0~1)，供 E 层日志/监控使用，不影响执行流程 */
    confidence: number;
}
/** 上游 D 层传入的执行计划 */
export interface ExecutionPlan {
    plan_id: string;
    /** 可追溯至 C 层的机会 ID */
    opportunity_id?: string;
    action_type: 'calendar' | 'feishu';
    payload: CalendarPayload | FeishuPayload;
    /**
     * LLM 生成上下文（仅飞书场景有意义）
     * D 层从 C 层三层上下文中筛选出对消息生成质量有直接影响的字段
     */
    llm_context?: LLMContext;
    /** D 层决策元数据（可选，用于日志追踪） */
    d_layer_meta?: DLayerMeta;
}
/** 日历场景 payload — 结构化事件数据（上游 AI 已完成自然语言解析） */
export interface CalendarPayload {
    title: string;
    start_time: string;
    end_time: string;
    location?: string;
    description?: string;
}
/** 飞书场景 payload — 收件人 + D 层对本次发送意图的总结 */
export interface FeishuPayload {
    /** 飞书用户唯一 ID（C 层实体对齐结果） */
    recipient_id: string;
    /** 收件人可读名称，供 LLM 生成消息时使用 */
    recipient_name?: string;
    /** D 层对本次发送目的的一句话概括，作为 LLM 的核心指令 */
    intent: string;
}
/** 草稿状态 */
export type DraftStatus = 'pending_approval' | 'executed' | 'rejected';
/** 草稿记录（仅飞书场景产生，Calendar 为静默写入） */
export interface DraftRecord {
    draft_id: string;
    plan_id: string;
    action_type: 'feishu';
    recipient_id: string;
    content: string;
    original_content: string;
    voice_feedback: string;
    status: DraftStatus;
    created_at: string;
    updated_at: string;
}
/** POST /drafts/:id/execute 的请求体 */
export interface ExecuteDraftRequest {
    modified_content?: string;
}
/** 统一 API 响应格式 */
export interface ApiResponse<T = null> {
    success: boolean;
    data: T;
}
//# sourceMappingURL=index.d.ts.map