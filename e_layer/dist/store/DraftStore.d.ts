import { DraftRecord, DraftStatus } from '../types';
/**
 * DraftStore — 内存草稿存储单例
 * 职责：增删改查草稿记录
 * 不知道飞书业务，不做任何决策
 */
declare class DraftStore {
    private static instance;
    private store;
    private constructor();
    static getInstance(): DraftStore;
    /** 保存新草稿，返回生成的 draft_id */
    save(params: {
        plan_id: string;
        recipient_id: string;
        content: string;
        voice_feedback: string;
    }): DraftRecord;
    /** 按 draft_id 查找草稿 */
    get(draft_id: string): DraftRecord | undefined;
    /** 获取所有草稿列表 */
    getAll(): DraftRecord[];
    /** 更新草稿状态 */
    updateStatus(draft_id: string, status: DraftStatus): DraftRecord;
    /** 更新草稿内容（同时更新 updated_at） */
    updateContent(draft_id: string, content: string): DraftRecord;
}
declare const _default: DraftStore;
export default _default;
//# sourceMappingURL=DraftStore.d.ts.map