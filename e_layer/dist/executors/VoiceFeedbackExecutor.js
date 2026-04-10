"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.VoiceFeedbackExecutor = void 0;
const deepseekClient_1 = __importDefault(require("../llm/deepseekClient"));
class VoiceFeedbackExecutor {
    async execute(action, llmContext) {
        const prompt = this.buildPrompt(action.intent, llmContext);
        const systemPrompt = '你是 Jarvis AI 的语音反馈模块。生成专业友好的语音提示，包含建议和鼓励。';
        const response = await deepseekClient_1.default.chat(prompt, systemPrompt);
        console.log('[VoiceFeedbackExecutor] Generated:', response);
        return response.trim();
    }
    buildPrompt(intent, llmContext) {
        const lines = [];
        lines.push('## 任务');
        lines.push('生成给用户的语音提示，专业友好，包含建议和鼓励。');
        lines.push('');
        lines.push('## 意图');
        lines.push(intent);
        lines.push('');
        lines.push('## 背景');
        lines.push(llmContext.trigger_summary);
        lines.push('');
        if (llmContext.current_state) {
            lines.push('## 用户状态');
            lines.push(llmContext.current_state);
            lines.push('');
        }
        lines.push('## 要求');
        lines.push('- 中文，不超过100字');
        lines.push('- 第二人称"你"，直接对用户说话');
        lines.push('- 专业友好，避免过于亲密的称呼（如"亲爱的"）');
        lines.push('- 包含关心和鼓励，但保持适当距离感');
        return lines.join('\n');
    }
}
exports.VoiceFeedbackExecutor = VoiceFeedbackExecutor;
//# sourceMappingURL=VoiceFeedbackExecutor.js.map