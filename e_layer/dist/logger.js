"use strict";
/**
 * Structured Logger — E Layer
 * Writes JSON-formatted log lines to both console and ../logs/e_layer.log
 */
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
Object.defineProperty(exports, "__esModule", { value: true });
exports.createLogger = createLogger;
const fs = __importStar(require("fs"));
const path = __importStar(require("path"));
const LOG_FILE = path.resolve(__dirname, '../../logs/e_layer.log');
/** Ensure log directory exists */
function ensureLogDir() {
    const dir = path.dirname(LOG_FILE);
    if (!fs.existsSync(dir)) {
        fs.mkdirSync(dir, { recursive: true });
    }
}
function write(entry) {
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
    }
    catch {
        // Silently ignore file write errors
    }
}
function createLogger(module) {
    const now = () => new Date().toISOString();
    return {
        debug(message, data) {
            write({ timestamp: now(), level: 'DEBUG', module, message, data });
        },
        info(message, data) {
            write({ timestamp: now(), level: 'INFO', module, message, data });
        },
        warn(message, data) {
            write({ timestamp: now(), level: 'WARN', module, message, data });
        },
        error(message, data) {
            write({ timestamp: now(), level: 'ERROR', module, message, data });
        },
    };
}
//# sourceMappingURL=logger.js.map