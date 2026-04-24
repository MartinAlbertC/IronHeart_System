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
const net = __importStar(require("net"));
const ActionPlanner_1 = __importDefault(require("./ActionPlanner"));
const Dispatcher_1 = __importDefault(require("./Dispatcher"));
const logger_1 = require("./logger");
const log = (0, logger_1.createLogger)('MQConsumer');
const SEP = '═'.repeat(70);
// Inline MQ Client
class MQClient {
    constructor(host = 'localhost', port = 6380) {
        this.host = host;
        this.port = port;
    }
    send(queueName, data) {
        return new Promise((resolve, reject) => {
            const msg = JSON.stringify({ op: 'send', queue: queueName, data }) + '\n';
            const sock = net.createConnection({ host: this.host, port: this.port }, () => {
                sock.write(msg);
            });
            let buffer = '';
            sock.on('data', (data) => {
                buffer += data.toString('utf-8');
                if (buffer.includes('\n')) {
                    sock.end();
                    resolve();
                }
            });
            sock.on('error', reject);
        });
    }
    recv(queueName) {
        return new Promise((resolve, reject) => {
            const sock = net.createConnection({ host: this.host, port: this.port }, () => {
                const msg = JSON.stringify({ op: 'recv', queue: queueName });
                sock.write(msg + '\n');
            });
            let buffer = '';
            sock.on('data', (data) => {
                buffer += data.toString('utf-8');
                if (buffer.includes('\n')) {
                    const resp = JSON.parse(buffer.trim());
                    sock.end();
                    if (resp.status === 'ok') {
                        resolve(resp.data);
                    }
                    else {
                        reject(new Error(resp.message || 'Unknown error'));
                    }
                }
            });
            sock.on('error', reject);
        });
    }
    /** 非阻塞接收：有消息返回数据，无消息返回 null */
    tryRecv(queueName) {
        return new Promise((resolve, reject) => {
            const msg = JSON.stringify({ op: 'try_recv', queue: queueName }) + '\n';
            const sock = net.createConnection({ host: this.host, port: this.port }, () => {
                sock.write(msg);
            });
            let buffer = '';
            sock.on('data', (data) => {
                buffer += data.toString('utf-8');
                if (buffer.includes('\n')) {
                    const resp = JSON.parse(buffer.trim());
                    sock.end();
                    if (resp.status === 'ok' && resp.data !== undefined) {
                        resolve(resp.data);
                    }
                    else {
                        resolve(null); // empty queue
                    }
                }
            });
            sock.on('error', (err) => {
                log.error(`tryRecv error: ${err.message}`);
                resolve(null); // on error, return null so loop can continue
            });
            // Timeout safety: if broker doesn't respond in 2s, close
            setTimeout(() => {
                sock.destroy();
                resolve(null);
            }, 2000);
        });
    }
}
const SLEEP_MS = 300; // polling interval when both queues empty
async function processTrigger(dataStr) {
    const trigger = JSON.parse(dataStr);
    // Enhanced logging: complete inbound ExecutionTrigger from D-Layer
    log.info('');
    log.info(SEP);
    log.info('>>> INBOUND [ExecutionTrigger] from D-Layer');
    log.info(SEP);
    log.info(JSON.stringify(trigger, null, 2));
    log.info(SEP);
    log.info('');
    // Step 1: ActionPlanner
    const action = await ActionPlanner_1.default.plan(trigger);
    // Enhanced logging: planned actions
    log.info('');
    log.info(SEP);
    log.info('>>> PLANNED ACTIONS');
    log.info(SEP);
    action.actions.forEach((item, index) => {
        log.info(`  [${index + 1}] ${item.action_type.toUpperCase()}: ${item.intent}`);
        if (item.payload) {
            log.info(`       Payload: ${JSON.stringify(item.payload, null, 2)}`);
        }
    });
    log.info(SEP);
    log.info('');
    // Step 2: Dispatcher
    const result = await Dispatcher_1.default.dispatch(action);
    // Enhanced logging: execution result
    log.info('');
    log.info(SEP);
    log.info('<<< OUTBOUND [ExecutionResponse]');
    log.info(SEP);
    log.info(JSON.stringify(result, null, 2));
    log.info(SEP);
    log.info('');
    // Step 3: 将结果写回 MQ（供 API Gateway 读取）
    try {
        const actionResult = {
            action_id: `act_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
            source: trigger.source || 'pipeline',
            plan_id: trigger.plan_id,
            opportunity_id: trigger.opportunity_id,
            type: _mapActionType(action.actions),
            title: _generateTitle(action, trigger),
            content: _generateContent(action, result, trigger),
            confidence: trigger.llm_context ? 0.8 : 0.5,
            status: 'pending',
            context: {
                trigger_summary: trigger.payload?.trigger_summary || '',
            },
            created_at: new Date().toISOString(),
        };
        await mq.send('e_results', JSON.stringify(actionResult));
        log.info(`[e_results] 已发送 action_id=${actionResult.action_id}`);
    }
    catch (e) {
        log.error(`[e_results] 发送失败: ${e instanceof Error ? e.message : String(e)}`);
    }
}
let mq;
async function main() {
    mq = new MQClient();
    log.info('E Layer MQ Consumer initializing');
    log.info('优先处理 command_execution_plans，再处理 execution_plans');
    while (true) {
        try {
            // 1. 优先检查指令执行计划队列（非阻塞）
            const cmdData = await mq.tryRecv('command_execution_plans');
            if (cmdData) {
                await processTrigger(cmdData);
                continue; // 处理完指令后立即再检查指令队列
            }
            // 2. 再检查常规执行计划队列（非阻塞）
            const data = await mq.tryRecv('execution_plans');
            if (data) {
                await processTrigger(data);
                continue;
            }
            // 3. 两个队列都为空，短暂等待
            await new Promise(resolve => setTimeout(resolve, SLEEP_MS));
        }
        catch (err) {
            log.error('Error in main loop', { error: String(err) });
            const errMsg = err instanceof Error ? err.message : String(err);
            if (errMsg.includes('timeout') || errMsg.includes('ECONNREFUSED') || errMsg.includes('socket')) {
                log.info(`Reconnecting in 3000ms...`);
                await new Promise(resolve => setTimeout(resolve, 3000));
            }
        }
    }
}
main().catch(err => log.error('Fatal error', { error: String(err) }));
// === 辅助函数 ===
function _mapActionType(actions) {
    if (actions.some(a => a.action_type === 'feishu'))
        return 'message';
    if (actions.some(a => a.action_type === 'calendar'))
        return 'calendar';
    if (actions.some(a => a.action_type === 'voice_feedback'))
        return 'notification';
    return 'task';
}
function _generateTitle(action, trigger) {
    const types = action.actions.map(a => a.action_type).join('+');
    return `${types} 建议`;
}
function _generateContent(action, result, trigger) {
    const parts = [];
    const summary = trigger.payload?.trigger_summary || '';
    if (summary)
        parts.push(`触发: ${summary}`);
    action.actions.forEach(a => {
        parts.push(`[${a.action_type}] ${a.intent || ''}`);
        if (a.payload)
            parts.push(`  内容: ${JSON.stringify(a.payload)}`);
    });
    return parts.join('\n');
}
//# sourceMappingURL=mqConsumer.js.map