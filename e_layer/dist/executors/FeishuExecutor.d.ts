import { ActionItem, LLMContext } from '../types/core';
export declare class FeishuExecutor {
    private feishuApi;
    execute(action: ActionItem, llmContext: LLMContext, planId: string): Promise<string | null>;
    private generateMessage;
    private buildPrompt;
}
//# sourceMappingURL=FeishuExecutor.d.ts.map