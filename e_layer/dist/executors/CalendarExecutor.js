"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.CalendarExecutor = void 0;
const deepseekClient_1 = __importDefault(require("../llm/deepseekClient"));
class CalendarExecutor {
    async execute(action, llmContext) {
        const prompt = this.buildPrompt(action.intent, llmContext);
        const systemPrompt = '你是 Jarvis AI 的日程管理模块。根据意图生成日程事件，以 JSON 格式输出。';
        const response = await deepseekClient_1.default.chat(prompt, systemPrompt);
        console.log('[CalendarExecutor] Generated:', response);
        const cleanedResponse = response.trim().replace(/^```json\s*/, '').replace(/\s*```$/, '');
        const event = JSON.parse(cleanedResponse);
        return {
            title: event.title,
            time: event.time,
        };
    }
    buildPrompt(intent, llmContext) {
        const lines = [];
        lines.push('## 任务');
        lines.push('根据意图生成日程事件。');
        lines.push('');
        lines.push('## 意图');
        lines.push(intent);
        lines.push('');
        lines.push('## 背景');
        lines.push(llmContext.trigger_summary);
        lines.push('');
        lines.push('## 输出格式');
        lines.push('{ "title": "事件标题", "time": "时间描述" }');
        return lines.join('\n');
    }
}
exports.CalendarExecutor = CalendarExecutor;
//# sourceMappingURL=CalendarExecutor.js.map