/**
 * FeishuApiExecutor — 飞书 HTTP API 调用器
 * 职责：调用飞书 API 发送消息
 * 不知道草稿概念，只负责发送
 * 当前为 Mock 实现，后续替换为真实飞书 Open API（含 User Token 鉴权）
 */
export class FeishuApiExecutor {
  async send(recipient_id: string, content: string): Promise<void> {
    // Mock：打印日志模拟调用飞书 API
    console.log(`[FeishuApiExecutor] 发送飞书消息:`, {
      recipient_id,
      content,
    });

    // 后续替换为：
    // await axios.post('https://open.feishu.cn/open-apis/im/v1/messages', {
    //   receive_id: recipient_id,
    //   msg_type: 'text',
    //   content: JSON.stringify({ text: content }),
    // }, { headers: { Authorization: `Bearer ${userToken}` } });
  }
}
