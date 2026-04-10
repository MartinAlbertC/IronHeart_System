import express, { Request, Response, NextFunction } from 'express';
import { ExecutionTrigger, ExecuteDraftRequest, ExecutionResponse } from './types/core';
import ActionPlanner from './ActionPlanner';
import Dispatcher, { SystemConfig } from './Dispatcher';
import DraftStore from './store/DraftStore';
import { FeishuApiExecutor } from './executors/FeishuApiExecutor';

const app = express();
app.use(express.json());

const PORT = process.env.PORT ?? 3000;
const feishuApi = new FeishuApiExecutor();

// ============================================================
// POST /api/v1/trigger_plan — 接收 D 层输入，规划并执行
// ============================================================
app.post('/api/v1/trigger_plan', async (req: Request, res: Response) => {
  const trigger = req.body as ExecutionTrigger;

  if (!trigger.plan_id || !trigger.payload) {
    res.status(400).json({ success: false, data: 'Missing required fields: plan_id, payload' });
    return;
  }

  try {
    // Step 1: ActionPlanner 将语义事件转换为 PlannedAction
    const action = await ActionPlanner.plan(trigger);

    // Step 2: Dispatcher 路由执行
    const result = await Dispatcher.dispatch(action);
    res.json(result);
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    if (message.startsWith('Unsupported action type') || message.startsWith('Unsupported semantic_type')) {
      res.status(400).json({ success: false, data: message });
    } else {
      res.status(500).json({ success: false, data: message });
    }
  }
});

// ============================================================
// GET /api/v1/drafts — 拉取所有草稿列表
// ============================================================
app.get('/api/v1/drafts', (_req: Request, res: Response) => {
  const drafts = DraftStore.getAll();
  res.json({ success: true, data: drafts });
});

// ============================================================
// GET /api/v1/drafts/:draft_id — 拉取单条草稿详情
// ============================================================
app.get('/api/v1/drafts/:draft_id', (req: Request, res: Response) => {
  const draft = DraftStore.get(req.params.draft_id);
  if (!draft) {
    res.status(404).json({ success: false, data: 'Draft not found' });
    return;
  }
  res.json({ success: true, data: draft });
});

// ============================================================
// POST /api/v1/drafts/:draft_id/execute — 确认并发送草稿
// ============================================================
app.post('/api/v1/drafts/:draft_id/execute', async (req: Request, res: Response) => {
  const draft = DraftStore.get(req.params.draft_id);
  if (!draft) {
    res.status(404).json({ success: false, data: 'Draft not found' });
    return;
  }
  if (draft.status !== 'pending_approval') {
    res.status(409).json({
      success: false,
      data: `Draft is not in pending_approval state (current: ${draft.status})`,
    });
    return;
  }

  const body = req.body as ExecuteDraftRequest;

  try {
    // 若提供了修改内容，先更新 content
    if (body.modified_content !== undefined) {
      DraftStore.updateContent(draft.draft_id, body.modified_content);
    }

    // 重新获取最新 draft（内容可能已被修改）
    const finalDraft = DraftStore.get(draft.draft_id)!;
    await feishuApi.send(finalDraft.recipient_id, finalDraft.content);

    // 更新状态为 executed
    DraftStore.updateStatus(draft.draft_id, 'executed');

    res.json({ success: true, data: null });
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    res.status(500).json({ success: false, data: message });
  }
});

// ============================================================
// POST /api/v1/drafts/:draft_id/reject — 拒绝草稿
// ============================================================
app.post('/api/v1/drafts/:draft_id/reject', (req: Request, res: Response) => {
  const draft = DraftStore.get(req.params.draft_id);
  if (!draft) {
    res.status(404).json({ success: false, data: 'Draft not found' });
    return;
  }
  if (draft.status !== 'pending_approval') {
    res.status(409).json({
      success: false,
      data: `Draft is not in pending_approval state (current: ${draft.status})`,
    });
    return;
  }

  DraftStore.updateStatus(draft.draft_id, 'rejected');
  res.json({ success: true, data: null });
});

// ============================================================
// 全局错误处理
// ============================================================
app.use((_err: Error, _req: Request, res: Response, _next: NextFunction) => {
  console.error('[Server] Unhandled error:', _err);
  res.status(500).json({ success: false, data: _err.message });
});

app.listen(PORT, () => {
  console.log(`[Server] Jarvis E-Layer 启动成功，监听端口 ${PORT}`);
  console.log(`[Server] dangerousMode: ${SystemConfig.dangerousMode}`);
});

export default app;
