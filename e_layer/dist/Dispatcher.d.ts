import { PlannedAction, ExecutionResponse } from './types/core';
export declare const SystemConfig: {
    dangerousMode: boolean;
};
declare class Dispatcher {
    private static instance;
    private feishuExecutor;
    private calendarExecutor;
    private voiceExecutor;
    private constructor();
    static getInstance(): Dispatcher;
    dispatch(action: PlannedAction): Promise<ExecutionResponse>;
}
declare const _default: Dispatcher;
export default _default;
//# sourceMappingURL=Dispatcher.d.ts.map