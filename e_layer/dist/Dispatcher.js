"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.SystemConfig = void 0;
const CalendarExecutor_1 = require("./executors/CalendarExecutor");
const FeishuExecutor_1 = require("./executors/FeishuExecutor");
const VoiceFeedbackExecutor_1 = require("./executors/VoiceFeedbackExecutor");
const DraftStore_1 = __importDefault(require("./store/DraftStore"));
exports.SystemConfig = {
    dangerousMode: false,
};
class Dispatcher {
    constructor() {
        this.feishuExecutor = new FeishuExecutor_1.FeishuExecutor();
        this.calendarExecutor = new CalendarExecutor_1.CalendarExecutor();
        this.voiceExecutor = new VoiceFeedbackExecutor_1.VoiceFeedbackExecutor();
    }
    static getInstance() {
        if (!Dispatcher.instance) {
            Dispatcher.instance = new Dispatcher();
        }
        return Dispatcher.instance;
    }
    async dispatch(action) {
        let draftId = null;
        let voiceFeedback;
        const calendarEvents = [];
        for (const item of action.actions) {
            if (item.action_type === 'feishu') {
                draftId = await this.feishuExecutor.execute(item, action.llm_context, action.plan_id);
            }
            else if (item.action_type === 'calendar') {
                const event = await this.calendarExecutor.execute(item, action.llm_context);
                calendarEvents.push(event);
            }
            else if (item.action_type === 'voice_feedback') {
                voiceFeedback = await this.voiceExecutor.execute(item, action.llm_context);
            }
        }
        // 更新草稿的 voice_feedback
        if (draftId && voiceFeedback) {
            const draft = DraftStore_1.default.get(draftId);
            if (draft) {
                draft.voice_feedback = voiceFeedback;
            }
        }
        return {
            success: true,
            data: {
                draft_id: draftId || undefined,
                voice_feedback: voiceFeedback,
                calendar_events: calendarEvents.length > 0 ? calendarEvents : undefined,
            },
        };
    }
}
exports.default = Dispatcher.getInstance();
//# sourceMappingURL=Dispatcher.js.map