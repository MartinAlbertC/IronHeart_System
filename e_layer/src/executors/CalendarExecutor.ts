import { ActionItem, LLMContext } from '../types/core';
import deepseekClient from '../llm/deepseekClient';

export class CalendarExecutor {
  async execute(action: ActionItem, llmContext: LLMContext): Promise<{ title: string; time: string }> {
    const prompt = this.buildPrompt(action.intent, llmContext);
    const systemPrompt = '你是 Jarvis AI 的日程管理模块。根据意图生成日程事件，以 JSON 格式输出。';

    const response = await deepseekClient.chat(prompt, systemPrompt);
    console.log('[CalendarExecutor] Generated:', response);

    const cleanedResponse = response.trim().replace(/^```json\s*/, '').replace(/\s*```$/, '');
    const event = JSON.parse(cleanedResponse);

    return {
      title: event.title,
      time: event.time,
    };
  }

  private buildPrompt(intent: string, llmContext: LLMContext): string {
    const lines: string[] = [];

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
