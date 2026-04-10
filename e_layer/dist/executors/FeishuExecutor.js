"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.FeishuExecutor = void 0;
const FeishuApiExecutor_1 = require("./FeishuApiExecutor");
const deepseekClient_1 = __importDefault(require("../llm/deepseekClient"));
const DraftStore_1 = __importDefault(require("../store/DraftStore"));
const Dispatcher_1 = require("../Dispatcher");
class FeishuExecutor {
    constructor() {
        this.feishuApi = new FeishuApiExecutor_1.FeishuApiExecutor();
    }
    async execute(action, llmContext, planId) {
        const payload = action.payload;
        const messageText = await this.generateMessage(action.intent, payload.recipient_name, llmContext);
        if (Dispatcher_1.SystemConfig.dangerousMode) {
            await this.feishuApi.send(payload.recipient_id, messageText);
            console.log(`[FeishuExecutor] 危险模式 — 已发送`);
            return null;
        }
        else {
            const draft = DraftStore_1.default.save({
                plan_id: planId,
                recipient_id: payload.recipient_id,
                content: messageText,
                voice_feedback: '',
            });
            console.log(`[FeishuExecutor] 草稿已创建 (draft_id: ${draft.draft_id})`);
            return draft.draft_id;
        }
    }
    async generateMessage(intent, recipientName, llmContext) {
        const prompt = this.buildPrompt(intent, recipientName, llmContext);
        const systemPrompt = '你是 Jarvis AI 的消息生成模块。生成发给收件人的飞书消息正文。';
        const response = await deepseekClient_1.default.chat(prompt, systemPrompt);
        return response.trim();
    }
    buildPrompt(intent, recipientName, llmContext) {
        const lines = [];
        lines.push('## 任务');
        lines.push('生成发给收件人的飞书消息正文。');
        lines.push('');
        lines.push('## 意图');
        lines.push(intent);
        lines.push('');
        if (recipientName) {
            lines.push('## 收件人');
            lines.push(recipientName);
            lines.push('');
        }
        lines.push('## 背景');
        lines.push(llmContext.trigger_summary);
        lines.push('');
        lines.push('## 要求');
        lines.push('- 中文，简短正式');
        lines.push('- 第一人称，直接对收件人说话');
        lines.push('- 适合发送的消息正文');
        return lines.join('\n');
    }
}
exports.FeishuExecutor = FeishuExecutor;
//# sourceMappingURL=FeishuExecutor.js.map