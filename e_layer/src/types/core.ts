// ============================================================
// E 层核心类型定义
// ============================================================

/** D 层输入 — 执行触发器 */
export interface ExecutionTrigger {
  plan_id: string;
  opportunity_id: string;
  payload: {
    semantic_type: string;
    resolved_entity_id?: string;
    trigger_summary: string;
  };
  llm_context: {
    user_persona: {
      health?: string;
      preferences?: string;
    };
    historical_memories: string[];
    recent_events: string[];
    current_cognitive_episode: string;
  };
  d_layer_decision: 'execute_now' | 'deferred_execute';
}

/** ActionPlanner 输出 — 规划后的行动方案 */
export interface PlannedAction {
  plan_id: string;
  opportunity_id: string;
  actions: ActionItem[];
  llm_context: LLMContext;
  confidence: number;
}

/** 单个行动项 */
export interface ActionItem {
  action_type: 'feishu' | 'calendar' | 'voice_feedback';
  intent: string;
  payload?: FeishuPayload | CalendarPayload;
}

/** 日历场景 payload */
export interface CalendarPayload {
  title: string;
  start_time: string;
  end_time: string;
  location?: string;
  description?: string;
}

/** 飞书场景 payload */
export interface FeishuPayload {
  recipient_id: string;
  recipient_name?: string;
  intent: string;
}

/** LLM 生成上下文（供 mockSkillRunner 使用） */
export interface LLMContext {
  trigger_summary: string;
  user_constraints: string[];
  relevant_memory?: string;
  current_state?: string;
}

/** mockSkillRunner 输出 */
export interface SkillOutput {
  message_to_recipient: string;
  voice_feedback: string;
  additional_actions?: Array<{
    type: 'calendar_reminder';
    description: string;
  }>;
}

/** 草稿记录 */
export interface DraftRecord {
  draft_id: string;
  plan_id: string;
  action_type: 'feishu';
  recipient_id: string;
  content: string;
  original_content: string;
  voice_feedback: string;
  status: 'pending_approval' | 'executed' | 'rejected';
  created_at: string;
  updated_at: string;
}

/** E 层输出 — 执行响应 */
export interface ExecutionResponse {
  success: boolean;
  data: {
    voice_feedback?: string;
    draft_id?: string;
    calendar_events?: Array<{
      title: string;
      time: string;
    }>;
  } | null;
}

/** POST /drafts/:id/execute 的请求体 */
export interface ExecuteDraftRequest {
  modified_content?: string;
}
