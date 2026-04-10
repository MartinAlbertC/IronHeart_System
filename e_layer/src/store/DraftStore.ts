import { v4 as uuidv4 } from 'uuid';
import { DraftRecord, DraftStatus } from '../types';

/**
 * DraftStore — 内存草稿存储单例
 * 职责：增删改查草稿记录
 * 不知道飞书业务，不做任何决策
 */
class DraftStore {
  private static instance: DraftStore;
  private store: Map<string, DraftRecord> = new Map();

  private constructor() {}

  static getInstance(): DraftStore {
    if (!DraftStore.instance) {
      DraftStore.instance = new DraftStore();
    }
    return DraftStore.instance;
  }

  /** 保存新草稿，返回生成的 draft_id */
  save(params: {
    plan_id: string;
    recipient_id: string;
    content: string;
    voice_feedback: string;
  }): DraftRecord {
    const now = new Date().toISOString();
    const record: DraftRecord = {
      draft_id: uuidv4(),
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
  get(draft_id: string): DraftRecord | undefined {
    return this.store.get(draft_id);
  }

  /** 获取所有草稿列表 */
  getAll(): DraftRecord[] {
    return Array.from(this.store.values());
  }

  /** 更新草稿状态 */
  updateStatus(draft_id: string, status: DraftStatus): DraftRecord {
    const record = this.store.get(draft_id);
    if (!record) {
      throw new Error(`Draft not found: ${draft_id}`);
    }
    record.status = status;
    record.updated_at = new Date().toISOString();
    return record;
  }

  /** 更新草稿内容（同时更新 updated_at） */
  updateContent(draft_id: string, content: string): DraftRecord {
    const record = this.store.get(draft_id);
    if (!record) {
      throw new Error(`Draft not found: ${draft_id}`);
    }
    record.content = content;
    record.updated_at = new Date().toISOString();
    return record;
  }
}

export default DraftStore.getInstance();
