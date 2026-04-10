import { ExecutionTrigger, PlannedAction } from './types/core';
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
declare class ActionPlanner {
    private static instance;
    private constructor();
    static getInstance(): ActionPlanner;
    /**
     * plan — 将 ExecutionTrigger 转换为 PlannedAction
     */
    plan(trigger: ExecutionTrigger): Promise<PlannedAction>;
    /**
     * callPlanningLLM — 调用 DeepSeek API 进行行动规划
     */
    private callPlanningLLM;
    /**
     * buildPlanningPrompt — 组装规划 Prompt
     */
    private buildPlanningPrompt;
    /**
     * buildLLMContext — 将 D 层上下文转换为 LLMContext
     */
    private buildLLMContext;
}
declare const _default: ActionPlanner;
export default _default;
//# sourceMappingURL=ActionPlanner.d.ts.map