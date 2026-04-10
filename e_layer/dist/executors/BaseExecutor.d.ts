import { PlannedAction, ExecutionResponse } from '../types/core';
/**
 * BaseExecutor — 所有执行器的抽象基类
 */
export declare abstract class BaseExecutor {
    abstract execute(action: PlannedAction): Promise<ExecutionResponse>;
}
//# sourceMappingURL=BaseExecutor.d.ts.map