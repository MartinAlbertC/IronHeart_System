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
}
async function main() {
    const mq = new MQClient();
    log.info('E Layer MQ Consumer initializing');
    while (true) {
        try {
            const dataStr = await mq.recv('execution_plans');
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
        }
        catch (err) {
            log.error('Error in main loop', { error: String(err) });
            // Reconnect delay
            const errMsg = err instanceof Error ? err.message : String(err);
            if (errMsg.includes('timeout') || errMsg.includes('ECONNREFUSED') || errMsg.includes('socket')) {
                log.info(`Reconnecting in 3000ms...`);
                await new Promise(resolve => setTimeout(resolve, 3000));
            }
        }
    }
}
main().catch(err => log.error('Fatal error', { error: String(err) }));
//# sourceMappingURL=mqConsumer.js.map