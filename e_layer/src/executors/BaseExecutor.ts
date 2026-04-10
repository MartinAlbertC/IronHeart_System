import { PlannedAction, ExecutionResponse } from '../types/core';

/**
 * BaseExecutor — 所有执行器的抽象基类
 */
export abstract class BaseExecutor {
  abstract execute(action: PlannedAction): Promise<ExecutionResponse>;
}
