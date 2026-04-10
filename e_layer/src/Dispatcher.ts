import { PlannedAction, ExecutionResponse } from './types/core';
import { CalendarExecutor } from './executors/CalendarExecutor';
import { FeishuExecutor } from './executors/FeishuExecutor';
import { VoiceFeedbackExecutor } from './executors/VoiceFeedbackExecutor';
import DraftStore from './store/DraftStore';

export const SystemConfig = {
  dangerousMode: false,
};

class Dispatcher {
  private static instance: Dispatcher;
  private feishuExecutor = new FeishuExecutor();
  private calendarExecutor = new CalendarExecutor();
  private voiceExecutor = new VoiceFeedbackExecutor();

  private constructor() {}

  static getInstance(): Dispatcher {
    if (!Dispatcher.instance) {
      Dispatcher.instance = new Dispatcher();
    }
    return Dispatcher.instance;
  }

  async dispatch(action: PlannedAction): Promise<ExecutionResponse> {
    let draftId: string | null = null;
    let voiceFeedback: string | undefined;
    const calendarEvents: Array<{ title: string; time: string }> = [];

    for (const item of action.actions) {
      if (item.action_type === 'feishu') {
        draftId = await this.feishuExecutor.execute(item, action.llm_context, action.plan_id);
      } else if (item.action_type === 'calendar') {
        const event = await this.calendarExecutor.execute(item, action.llm_context);
        calendarEvents.push(event);
      } else if (item.action_type === 'voice_feedback') {
        voiceFeedback = await this.voiceExecutor.execute(item, action.llm_context);
      }
    }

    // 更新草稿的 voice_feedback
    if (draftId && voiceFeedback) {
      const draft = DraftStore.get(draftId);
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

export default Dispatcher.getInstance();
