/**
 * DeepSeek API 客户端
 * 使用 OpenAI SDK 访问 DeepSeek API（兼容格式）
 */
declare class DeepSeekClient {
    private static instance;
    private client;
    private constructor();
    static getInstance(): DeepSeekClient;
    /**
     * 调用 DeepSeek Chat API
     * @param prompt 用户提示词
     * @param systemPrompt 系统提示词（可选）
     * @returns LLM 生成的文本
     */
    chat(prompt: string, systemPrompt?: string): Promise<string>;
}
declare const _default: DeepSeekClient;
export default _default;
//# sourceMappingURL=deepseekClient.d.ts.map