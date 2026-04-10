/**
 * Structured Logger — E Layer
 * Writes JSON-formatted log lines to both console and ../logs/e_layer.log
 */
export type LogLevel = 'DEBUG' | 'INFO' | 'WARN' | 'ERROR';
export interface Logger {
    debug(message: string, data?: unknown): void;
    info(message: string, data?: unknown): void;
    warn(message: string, data?: unknown): void;
    error(message: string, data?: unknown): void;
}
export declare function createLogger(module: string): Logger;
//# sourceMappingURL=logger.d.ts.map