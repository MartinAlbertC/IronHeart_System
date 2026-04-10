"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.mockSkillRunner = mockSkillRunner;
const deepseekClient_1 = __importDefault(require("../llm/deepseekClient"));
/**
 * mockSkillRunner — LLM 文案生成（第二阶段）
 * 使用 DeepSeek API 生成完整输出：消息正文、语音反馈、附加行动
 */
async function mockSkillRunner(intent, recipientName, llmContext) {
    const prompt = buildPrompt(intent, recipientName, llmContext);
    const systemPrompt = '你是 Jarvis AI 的消息生成模块。根据用户意图和上下文，生成三部分内容：1) 发给收件人的消息 2) 给用户的语音反馈 3) 建议的附加行动。以 JSON 格式输出。';
    const response = await deepseekClient_1.default.chat(prompt, systemPrompt);
    console.log('[mockSkillRunner] Generated output:', response);
    // 解析 JSON 响应
    const cleanedResponse = response.trim().replace(/^```json\s*/, '').replace(/\s*```$/, '');
    const output = JSON.parse(cleanedResponse);
    return output;
}
/**
 * buildPrompt — 组装文案生成 Prompt
 */
function buildPrompt(intent, recipientName, llmContext) {
    const lines = [];
    lines.push('## 任务');
    lines.push('根据以下背景，生成三部分内容：');
    lines.push('1. message_to_recipient: 发给收件人的飞书消息正文（正式、简洁）');
    lines.push('2. voice_feedback: 给用户的语音提示（包含建议、关怀、鼓励）');
    lines.push('3. additional_actions: 建议的附加行动（如日程提醒），可选');
    lines.push('');
    lines.push('## 发送意图');
    lines.push(intent);
    lines.push('');
    if (recipientName) {
        lines.push('## 收件人');
        lines.push(recipientName);
        lines.push('');
    }
    lines.push('## 触发背景');
    lines.push(llmContext.trigger_summary);
    lines.push('');
    if (llmContext.user_constraints.length > 0) {
        lines.push('## 用户健康与偏好约束');
        llmContext.user_constraints.forEach((c) => lines.push(`- ${c}`));
        lines.push('');
    }
    if (llmContext.relevant_memory) {
        lines.push('## 相关历史记忆');
        lines.push(llmContext.relevant_memory);
        lines.push('');
    }
    if (llmContext.current_state) {
        lines.push('## 用户当前状态');
        lines.push(llmContext.current_state);
        lines.push('');
    }
    lines.push('## 输出格式');
    lines.push('以 JSON 格式输出：');
    lines.push('{');
    lines.push('  "message_to_recipient": "发给收件人的消息正文",');
    lines.push('  "voice_feedback": "给用户的语音提示",');
    lines.push('  "additional_actions": [');
    lines.push('    { "type": "calendar_reminder", "description": "提醒描述" }');
    lines.push('  ]');
    lines.push('}');
    lines.push('');
    lines.push('## 要求');
    lines.push('- message_to_recipient: 中文，简短正式，适合发给收件人');
    lines.push('- voice_feedback: 中文，温暖友好，包含建议和鼓励，不超过100字');
    lines.push('- additional_actions: 根据用户状态建议健康提醒（如喝水、休息），可为空数组');
    return lines.join('\n');
}
//# sourceMappingURL=mockSkillRunner.js.map