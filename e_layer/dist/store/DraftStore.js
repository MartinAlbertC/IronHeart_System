"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
const uuid_1 = require("uuid");
/**
 * DraftStore — 内存草稿存储单例
 * 职责：增删改查草稿记录
 * 不知道飞书业务，不做任何决策
 */
class DraftStore {
    constructor() {
        this.store = new Map();
    }
    static getInstance() {
        if (!DraftStore.instance) {
            DraftStore.instance = new DraftStore();
        }
        return DraftStore.instance;
    }
    /** 保存新草稿，返回生成的 draft_id */
    save(params) {
        const now = new Date().toISOString();
        const record = {
            draft_id: (0, uuid_1.v4)(),
            plan_id: params.plan_id,
            action_type: 'feishu',
            recipient_id: params.recipient_id,
            content: params.content,
            original_content: params.content,
            voice_feedback: params.voice_feedback,
            status: 'pending_approval',
            created_at: now,
            updated_at: now,
        };
        this.store.set(record.draft_id, record);
        return record;
    }
    /** 按 draft_id 查找草稿 */
    get(draft_id) {
        return this.store.get(draft_id);
    }
    /** 获取所有草稿列表 */
    getAll() {
        return Array.from(this.store.values());
    }
    /** 更新草稿状态 */
    updateStatus(draft_id, status) {
        const record = this.store.get(draft_id);
        if (!record) {
            throw new Error(`Draft not found: ${draft_id}`);
        }
        record.status = status;
        record.updated_at = new Date().toISOString();
        return record;
    }
    /** 更新草稿内容（同时更新 updated_at） */
    updateContent(draft_id, content) {
        const record = this.store.get(draft_id);
        if (!record) {
            throw new Error(`Draft not found: ${draft_id}`);
        }
        record.content = content;
        record.updated_at = new Date().toISOString();
        return record;
    }
}
exports.default = DraftStore.getInstance();
//# sourceMappingURL=DraftStore.js.map