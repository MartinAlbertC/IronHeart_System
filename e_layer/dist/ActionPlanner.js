"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
const deepseekClient_1 = __importDefault(require("./llm/deepseekClient"));
/**
 * ActionPlanner — E 层行动规划 LLM（第一阶段）
 *
 * 职责：
 * 1. 接收 D 层的 ExecutionTrigger
 * 2. 调用 LLM 决定 action_type + intent
 * 3. 输出结构化的 PlannedAction
 *
 * 不负责：生成最终文案（由 mockSkillRunner 负责）
 */
class ActionPlanner {
    constructor() { }
    static getInstance() {
        if (!ActionPlanner.instance) {
            ActionPlanner.instance = new ActionPlanner();
        }
        return ActionPlanner.instance;
    }
    /**
     * plan — 将 ExecutionTrigger 转换为 PlannedAction
     */
    async plan(trigger) {
        const decision = await this.callPlanningLLM(trigger);
        const actions = decision.actions.map(a => {
            const item = {
                action_type: a.action_type,
                intent: a.intent,
            };
            if (a.action_type === 'feishu') {
                item.payload = {
                    recipient_id: a.recipient_id || trigger.payload.resolved_entity_id || 'unknown_user',
                    recipient_name: a.recipient_name,
                    intent: a.intent,
                };
            }
            return item;
        });
        return {
            plan_id: trigger.plan_id,
            opportunity_id: trigger.opportunity_id,
            actions,
            llm_context: this.buildLLMContext(trigger),
            confidence: decision.confidence,
        };
    }
    /**
     * callPlanningLLM — 调用 DeepSeek API 进行行动规划
     */
    async callPlanningLLM(trigger) {
        const prompt = this.buildPlanningPrompt(trigger);
        const systemPrompt = '你是 Jarvis AI 的行动规划模块。根据用户事件，以 JSON 格式输出多个建议行动。';
        const response = await deepseekClient_1.default.chat(prompt, systemPrompt);
        console.log('[ActionPlanner] DeepSeek Response:', response);
        // 解析 JSON 响应
        try {
            const cleanedResponse = response.trim().replace(/^```json\s*/, '').replace(/\s*```$/, '');
            const decision = JSON.parse(cleanedResponse);
            return {
                actions: decision.actions || [],
                confidence: decision.confidence || 0.8,
            };
        }
        catch (err) {
            console.error('[ActionPlanner] Failed to parse LLM response:', err);
            throw new Error('LLM response parsing failed');
        }
    }
    /**
     * buildPlanningPrompt — 组装规划 Prompt
     */
    buildPlanningPrompt(trigger) {
        const lines = [];
        const ctx = trigger.llm_context;
        lines.push('## 任务');
        lines.push('你是 Jarvis AI 的行动规划模块，根据用户事件决定应采取哪些行动。');
        lines.push('输出多个行动建议，每个行动包含类型和意图描述。');
        lines.push('');
        lines.push('## 触发事件');
        lines.push(`类型: ${trigger.payload.semantic_type}`);
        lines.push(`摘要: ${trigger.payload.trigger_summary}`);
        if (trigger.payload.resolved_entity_id) {
            lines.push(`涉及实体: ${trigger.payload.resolved_entity_id}`);
        }
        lines.push('');
        lines.push('## 用户画像');
        if (ctx.user_persona.health)
            lines.push(`健康: ${ctx.user_persona.health}`);
        if (ctx.user_persona.preferences)
            lines.push(`偏好: ${ctx.user_persona.preferences}`);
        lines.push('');
        if (ctx.historical_memories.length > 0) {
            lines.push('## 相关历史记忆');
            ctx.historical_memories.forEach(m => lines.push(`- ${m}`));
            lines.push('');
        }
        lines.push('## 近期事件');
        ctx.recent_events.forEach(e => lines.push(`- ${e}`));
        lines.push('');
        lines.push('## 当前认知状态');
        lines.push(ctx.current_cognitive_episode);
        lines.push('');
        lines.push('## 输出要求');
        lines.push('以 JSON 格式输出：');
        lines.push('{');
        lines.push('  "actions": [');
        lines.push('    { "action_type": "feishu", "intent": "回复导师说明论文进展", "recipient_name": "王教授" },');
        lines.push('    { "action_type": "calendar", "intent": "添加下周三与导师讨论论文的日程" },');
        lines.push('    { "action_type": "voice_feedback", "intent": "关心用户健康和进度，提醒注意休息" }');
        lines.push('  ],');
        lines.push('  "confidence": 0.9');
        lines.push('}');
        lines.push('');
        lines.push('## 系统当前支持的行动类型（仅限以下三种）');
        lines.push('1. feishu: 发送飞书消息');
        lines.push('   - 当前实现：向指定收件人发送文本消息');
        lines.push('');
        lines.push('2. calendar: 日程管理');
        lines.push('   - 当前实现：创建日程提醒');
        lines.push('');
        lines.push('3. voice_feedback: 语音反馈');
        lines.push('   - 当前实现：生成给用户的语音提示文本');
        lines.push('');
        lines.push('重要：只能生成以上三种类型的行动，不要生成其他类型（如email、phone_call等）');
        return lines.join('\n');
    }
    /**
     * buildLLMContext — 将 D 层上下文转换为 LLMContext
     */
    buildLLMContext(trigger) {
        const ctx = trigger.llm_context;
        const constraints = [];
        if (ctx.user_persona.health)
            constraints.push(ctx.user_persona.health);
        if (ctx.user_persona.preferences)
            constraints.push(ctx.user_persona.preferences);
        return {
            trigger_summary: trigger.payload.trigger_summary,
            user_constraints: constraints,
            relevant_memory: ctx.historical_memories.join('\n'),
            current_state: `${ctx.recent_events.slice(-3).join('; ')} | ${ctx.current_cognitive_episode}`,
        };
    }
}
exports.default = ActionPlanner.getInstance();
//# sourceMappingURL=ActionPlanner.js.map