import { ActionItem, FeishuPayload, LLMContext } from '../types/core';
import { FeishuApiExecutor } from './FeishuApiExecutor';
import deepseekClient from '../llm/deepseekClient';
import DraftStore from '../store/DraftStore';
import { SystemConfig } from '../Dispatcher';

export class FeishuExecutor {
  private feishuApi = new FeishuApiExecutor();

  async execute(action: ActionItem, llmContext: LLMContext, planId: string): Promise<string | null> {
    const payload = action.payload as FeishuPayload;
    const messageText = await this.generateMessage(action.intent, payload.recipient_name, llmContext);

    if (SystemConfig.dangerousMode) {
      await this.feishuApi.send(payload.recipient_id, messageText);
      console.log(`[FeishuExecutor] 危险模式 — 已发送`);
      return null;
    } else {
      const draft = DraftStore.save({
        plan_id: planId,
        recipient_id: payload.recipient_id,
        content: messageText,
        voice_feedback: '',
      });
      console.log(`[FeishuExecutor] 草稿已创建 (draft_id: ${draft.draft_id})`);
      return draft.draft_id;
    }
  }

  private async generateMessage(intent: string, recipientName: string | undefined, llmContext: LLMContext): Promise<string> {
    const prompt = this.buildPrompt(intent, recipientName, llmContext);
    const systemPrompt = '你是 Jarvis AI 的消息生成模块。生成发给收件人的飞书消息正文。';

    const response = await deepseekClient.chat(prompt, systemPrompt);
    return response.trim();
  }

  private buildPrompt(intent: string, recipientName: string | undefined, llmContext: LLMContext): string {
    const lines: string[] = [];

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
