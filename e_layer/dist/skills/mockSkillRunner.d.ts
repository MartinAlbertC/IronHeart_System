import { LLMContext, SkillOutput } from '../types/core';
/**
 * mockSkillRunner — LLM 文案生成（第二阶段）
 * 使用 DeepSeek API 生成完整输出：消息正文、语音反馈、附加行动
 */
export declare function mockSkillRunner(intent: string, recipientName: string | undefined, llmContext: LLMContext): Promise<SkillOutput>;
//# sourceMappingURL=mockSkillRunner.d.ts.map