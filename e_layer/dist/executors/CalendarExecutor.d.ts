import { ActionItem, LLMContext } from '../types/core';
export declare class CalendarExecutor {
    execute(action: ActionItem, llmContext: LLMContext): Promise<{
        title: string;
        time: string;
    }>;
    private buildPrompt;
}
//# sourceMappingURL=CalendarExecutor.d.ts.map