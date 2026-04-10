import * as net from 'net';
import { ExecutionTrigger, ExecutionResponse } from './types/core';
import ActionPlanner from './ActionPlanner';
import Dispatcher from './Dispatcher';
import { createLogger } from './logger';

const log = createLogger('MQConsumer');
const SEP = '═'.repeat(70);

// Inline MQ Client
class MQClient {
  private host: string;
  private port: number;

  constructor(host = 'localhost', port = 6380) {
    this.host = host;
    this.port = port;
  }

  recv(queueName: string): Promise<string> {
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
          } else {
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
      const trigger: ExecutionTrigger = JSON.parse(dataStr);

      // Enhanced logging: complete inbound ExecutionTrigger from D-Layer
      log.info('');
      log.info(SEP);
      log.info('>>> INBOUND [ExecutionTrigger] from D-Layer');
      log.info(SEP);
      log.info(JSON.stringify(trigger, null, 2));
      log.info(SEP);
      log.info('');

      // Step 1: ActionPlanner
      const action = await ActionPlanner.plan(trigger);

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
      const result: ExecutionResponse = await Dispatcher.dispatch(action);

      // Enhanced logging: execution result
      log.info('');
      log.info(SEP);
      log.info('<<< OUTBOUND [ExecutionResponse]');
      log.info(SEP);
      log.info(JSON.stringify(result, null, 2));
      log.info(SEP);
      log.info('');

    } catch (err) {
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
