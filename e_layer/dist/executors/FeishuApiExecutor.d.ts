/**
 * FeishuApiExecutor — 飞书 HTTP API 调用器
 * 职责：调用飞书 API 发送消息
 * 不知道草稿概念，只负责发送
 * 当前为 Mock 实现，后续替换为真实飞书 Open API（含 User Token 鉴权）
 */
export declare class FeishuApiExecutor {
    send(recipient_id: string, content: string): Promise<void>;
}
//# sourceMappingURL=FeishuApiExecutor.d.ts.map