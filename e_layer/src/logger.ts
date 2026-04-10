/**
 * Structured Logger — E Layer
 * Writes JSON-formatted log lines to both console and ../logs/e_layer.log
 */

import * as fs from 'fs';
import * as path from 'path';

const LOG_FILE = path.resolve(__dirname, '../../logs/e_layer.log');

/** Ensure log directory exists */
function ensureLogDir(): void {
  const dir = path.dirname(LOG_FILE);
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }
}

export type LogLevel = 'DEBUG' | 'INFO' | 'WARN' | 'ERROR';

interface LogEntry {
  timestamp: string;
  level: LogLevel;
  module: string;
  message: string;
  data?: unknown;
}

function write(entry: LogEntry): void {
  const line = JSON.stringify(entry);
  // Console output (human-readable)
  const ts = entry.timestamp;
  switch (entry.level) {
    case 'ERROR':
      console.error(`[${ts}] [${entry.level}] [${entry.module}] ${entry.message}`, entry.data ?? '');
      break;
    case 'WARN':
      console.warn(`[${ts}] [${entry.level}] [${entry.module}] ${entry.message}`, entry.data ?? '');
      break;
    default:
      console.log(`[${ts}] [${entry.level}] [${entry.module}] ${entry.message}`, entry.data ?? '');
  }
  // File output (structured JSON)
  try {
    ensureLogDir();
    fs.appendFileSync(LOG_FILE, line + '\n');
  } catch {
    // Silently ignore file write errors
  }
}

export interface Logger {
  debug(message: string, data?: unknown): void;
  info(message: string, data?: unknown): void;
  warn(message: string, data?: unknown): void;
  error(message: string, data?: unknown): void;
}

export function createLogger(module: string): Logger {
  const now = () => new Date().toISOString();

  return {
    debug(message: string, data?: unknown) {
      write({ timestamp: now(), level: 'DEBUG', module, message, data });
    },
    info(message: string, data?: unknown) {
      write({ timestamp: now(), level: 'INFO', module, message, data });
    },
    warn(message: string, data?: unknown) {
      write({ timestamp: now(), level: 'WARN', module, message, data });
    },
    error(message: string, data?: unknown) {
      write({ timestamp: now(), level: 'ERROR', module, message, data });
    },
  };
}
