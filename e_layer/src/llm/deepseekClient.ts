import OpenAI from 'openai';

/**
 * DeepSeek API 客户端
 * 使用 OpenAI SDK 访问 DeepSeek API（兼容格式）
 */
class DeepSeekClient {
  private static instance: DeepSeekClient;
  private client: OpenAI;

  private constructor() {
    this.client = new OpenAI({
      baseURL: 'https://api.deepseek.com',
      apiKey: 'sk-51da30b4ce9c4712a3a9035f4c405441',
    });
  }

  static getInstance(): DeepSeekClient {
    if (!DeepSeekClient.instance) {
      DeepSeekClient.instance = new DeepSeekClient();
    }
    return DeepSeekClient.instance;
  }

  /**
   * 调用 DeepSeek Chat API
   * @param prompt 用户提示词
   * @param systemPrompt 系统提示词（可选）
   * @returns LLM 生成的文本
   */
  async chat(prompt: string, systemPrompt?: string): Promise<string> {
    const messages: OpenAI.Chat.ChatCompletionMessageParam[] = [];

    if (systemPrompt) {
      messages.push({ role: 'system', content: systemPrompt });
    }
    messages.push({ role: 'user', content: prompt });

    const response = await this.client.chat.completions.create({
      model: 'deepseek-chat',
      messages,
      temperature: 0.7,
    });

    return response.choices[0]?.message?.content || '';
  }
}

export default DeepSeekClient.getInstance();
