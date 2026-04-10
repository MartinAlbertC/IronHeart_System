"use strict";
var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __importStar = (this && this.__importStar) || (function () {
    var ownKeys = function(o) {
        ownKeys = Object.getOwnPropertyNames || function (o) {
            var ar = [];
            for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) ar[ar.length] = k;
            return ar;
        };
        return ownKeys(o);
    };
    return function (mod) {
        if (mod && mod.__esModule) return mod;
        var result = {};
        if (mod != null) for (var k = ownKeys(mod), i = 0; i < k.length; i++) if (k[i] !== "default") __createBinding(result, mod, k[i]);
        __setModuleDefault(result, mod);
        return result;
    };
})();
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
const express_1 = __importDefault(require("express"));
const ActionPlanner_1 = __importDefault(require("./ActionPlanner"));
const Dispatcher_1 = __importStar(require("./Dispatcher"));
const DraftStore_1 = __importDefault(require("./store/DraftStore"));
const FeishuApiExecutor_1 = require("./executors/FeishuApiExecutor");
const app = (0, express_1.default)();
app.use(express_1.default.json());
const PORT = process.env.PORT ?? 3000;
const feishuApi = new FeishuApiExecutor_1.FeishuApiExecutor();
// ============================================================
// POST /api/v1/trigger_plan — 接收 D 层输入，规划并执行
// ============================================================
app.post('/api/v1/trigger_plan', async (req, res) => {
    const trigger = req.body;
    if (!trigger.plan_id || !trigger.payload) {
        res.status(400).json({ success: false, data: 'Missing required fields: plan_id, payload' });
        return;
    }
    try {
        // Step 1: ActionPlanner 将语义事件转换为 PlannedAction
        const action = await ActionPlanner_1.default.plan(trigger);
        // Step 2: Dispatcher 路由执行
        const result = await Dispatcher_1.default.dispatch(action);
        res.json(result);
    }
    catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        if (message.startsWith('Unsupported action type') || message.startsWith('Unsupported semantic_type')) {
            res.status(400).json({ success: false, data: message });
        }
        else {
            res.status(500).json({ success: false, data: message });
        }
    }
});
// ============================================================
// GET /api/v1/drafts — 拉取所有草稿列表
// ============================================================
app.get('/api/v1/drafts', (_req, res) => {
    const drafts = DraftStore_1.default.getAll();
    res.json({ success: true, data: drafts });
});
// ============================================================
// GET /api/v1/drafts/:draft_id — 拉取单条草稿详情
// ============================================================
app.get('/api/v1/drafts/:draft_id', (req, res) => {
    const draft = DraftStore_1.default.get(req.params.draft_id);
    if (!draft) {
        res.status(404).json({ success: false, data: 'Draft not found' });
        return;
    }
    res.json({ success: true, data: draft });
});
// ============================================================
// POST /api/v1/drafts/:draft_id/execute — 确认并发送草稿
// ============================================================
app.post('/api/v1/drafts/:draft_id/execute', async (req, res) => {
    const draft = DraftStore_1.default.get(req.params.draft_id);
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
    const body = req.body;
    try {
        // 若提供了修改内容，先更新 content
        if (body.modified_content !== undefined) {
            DraftStore_1.default.updateContent(draft.draft_id, body.modified_content);
        }
        // 重新获取最新 draft（内容可能已被修改）
        const finalDraft = DraftStore_1.default.get(draft.draft_id);
        await feishuApi.send(finalDraft.recipient_id, finalDraft.content);
        // 更新状态为 executed
        DraftStore_1.default.updateStatus(draft.draft_id, 'executed');
        res.json({ success: true, data: null });
    }
    catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        res.status(500).json({ success: false, data: message });
    }
});
// ============================================================
// POST /api/v1/drafts/:draft_id/reject — 拒绝草稿
// ============================================================
app.post('/api/v1/drafts/:draft_id/reject', (req, res) => {
    const draft = DraftStore_1.default.get(req.params.draft_id);
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
    DraftStore_1.default.updateStatus(draft.draft_id, 'rejected');
    res.json({ success: true, data: null });
});
// ============================================================
// 全局错误处理
// ============================================================
app.use((_err, _req, res, _next) => {
    console.error('[Server] Unhandled error:', _err);
    res.status(500).json({ success: false, data: _err.message });
});
app.listen(PORT, () => {
    console.log(`[Server] Jarvis E-Layer 启动成功，监听端口 ${PORT}`);
    console.log(`[Server] dangerousMode: ${Dispatcher_1.SystemConfig.dangerousMode}`);
});
exports.default = app;
//# sourceMappingURL=server.js.map