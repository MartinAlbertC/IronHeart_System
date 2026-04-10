"""飞书管道核心模块。

监听飞书事件 → 转换为 A 层事件（ui_state_change / notification_event）→ 写入 EventSink。
"""
import json
import logging
from datetime import datetime
from typing import Optional

from src.core import config
from src.core.event_generator import EventGenerator, EventSink
from src.feishu.feishu_client import FeishuClient
from src.core.utils import setup_logger

logger = setup_logger(config.FEISHU_LOG_FILE)


class FeishuPipeline:
    """
    飞书管道：监听飞书事件，转换为标准 A 层事件输出。

    使用方式：
        pipeline = FeishuPipeline()
        pipeline.start()   # 阻塞运行
    """

    def __init__(
        self,
        app_id: str = config.FEISHU_APP_ID,
        app_secret: str = config.FEISHU_APP_SECRET,
        mode: str = config.FEISHU_BOT_MODE,
        output_file: str = config.EVENT_OUTPUT_FILE,
        event_sink: Optional[EventSink] = None,
        verification_token: str = config.FEISHU_VERIFICATION_TOKEN,
        encrypt_key: str = config.FEISHU_ENCRYPT_KEY,
        webhook_port: int = config.FEISHU_WEBHOOK_PORT,
    ):
        self.event_generator = EventGenerator(device_id=config.DEVICE_ID)

        # 共享 EventSink 或自建
        if event_sink is not None:
            self.event_sink = event_sink
            self._owns_sink = False
        else:
            self.event_sink = EventSink(output_file, append=False)
            self._owns_sink = True

        # 飞书客户端
        self.client = FeishuClient(
            app_id=app_id,
            app_secret=app_secret,
            mode=mode,
            verification_token=verification_token,
            encrypt_key=encrypt_key,
            webhook_port=webhook_port,
        )

        # 注册事件回调
        self.client.register("im.message.receive_v1", self._on_message)
        self.client.register("im.chat.member.bot.added_v1", self._on_bot_added)
        self.client.register("im.chat.updated_v6", self._on_chat_updated)
        self.client.register(
            "calendar.calendar.event.created_v6", self._on_calendar_created
        )

        self._event_count = 0

    # ------------------------------------------------------------------
    # 启动 / 停止
    # ------------------------------------------------------------------

    def start(self):
        """启动飞书管道（阻塞）。"""
        logger.info("飞书管道启动")
        try:
            self.client.start()
        except KeyboardInterrupt:
            logger.info("用户中断，飞书管道停止")
        finally:
            if self._owns_sink:
                self.event_sink.close()
            logger.info(f"飞书管道结束，共输出 {self._event_count} 个事件")

    def stop(self):
        """停止飞书管道。"""
        self.client.stop()

    # ------------------------------------------------------------------
    # 事件处理：消息
    # ------------------------------------------------------------------

    def _on_message(self, data: dict):
        """
        处理收到消息事件 → notification_event (message_notification)

        data 结构（lark-oapi P2ImMessageReceiveV1）：
            sender.sender_id.open_id / user_id / union_id
            sender.sender_type
            message.message_id
            message.chat_id
            message.chat_type          "p2p" | "group"
            message.message_type       "text" | "image" | ...
            message.content            JSON 字符串，如 '{"text":"hello"}'
        """
        now = datetime.now()

        # 提取发送者信息
        sender = data.get("sender", {})
        sender_id = sender.get("sender_id", {})
        sender_open_id = sender_id.get("open_id", "unknown")

        # 提取消息信息
        message = data.get("message", {})
        chat_id = message.get("chat_id", "")
        chat_type = message.get("chat_type", "unknown")
        msg_type = message.get("message_type", "unknown")
        content_str = message.get("content", "{}")

        # 解析消息内容，提取预览文本
        preview_text = self._extract_text_content(content_str, msg_type)

        # 获取聊天标题（尝试从 message 中取，否则用 chat_id）
        thread_title = data.get("message", {}).get("chat_id", "")

        # 判断通知子类型
        notif_type = "dm_message" if chat_type == "p2p" else "group_message"

        notif_info = {
            "subtype": "message_notification",
            "app_name": "Feishu",
            "notification_type": notif_type,
            "title": sender_open_id,
            "preview_text": preview_text[:200],  # 截断过长内容
            "thread_id": f"feishu_{chat_id}",
            "priority_hint": "unknown",
            "timestamp": now,
        }

        event = self.event_generator.generate_notification_event(notif_info)
        self.event_sink.write_event(event)
        self._event_count += 1

        logger.info(
            f"[消息] {chat_type} | {sender_open_id} | "
            f"{preview_text[:50]}"
        )

    # ------------------------------------------------------------------
    # 事件处理：Bot 被加入群聊
    # ------------------------------------------------------------------

    def _on_bot_added(self, data: dict):
        """
        处理 Bot 被加入群聊 → ui_state_change (chat_thread_opened)

        data 结构：
            chat_id
            operator.operator_id.open_id
        """
        now = datetime.now()
        chat_id = data.get("chat_id", "")

        ui_info = {
            "subtype": "chat_thread_opened",
            "app_name": "Feishu",
            "page_type": "group_chat",
            "thread_id": f"feishu_{chat_id}",
        }

        event = self.event_generator.generate_ui_state_change_event(ui_info)
        self.event_sink.write_event(event)
        self._event_count += 1

        logger.info(f"[群聊] Bot 被加入群: {chat_id}")

    # ------------------------------------------------------------------
    # 事件处理：群聊更新
    # ------------------------------------------------------------------

    def _on_chat_updated(self, data: dict):
        """
        处理群聊信息更新 → ui_state_change (group_updated)

        data 结构：
            chat_id
            operator.operator_id.open_id
            ...（更新内容因事件版本而异）
        """
        now = datetime.now()
        chat_id = data.get("chat_id", "")

        ui_info = {
            "subtype": "group_updated",
            "app_name": "Feishu",
            "page_type": "group_chat",
            "thread_id": f"feishu_{chat_id}",
        }

        event = self.event_generator.generate_ui_state_change_event(ui_info)
        self.event_sink.write_event(event)
        self._event_count += 1

        logger.info(f"[群聊] 群信息更新: {chat_id}")

    # ------------------------------------------------------------------
    # 事件处理：日历事件
    # ------------------------------------------------------------------

    def _on_calendar_created(self, data: dict):
        """
        处理日历事件创建 → notification_event (calendar_reminder)

        data 结构（因 lark-oapi 版本而异）：
            calendar_id
            event_id
            summary
            start_time / end_time
            ...
        """
        now = datetime.now()

        summary = data.get("summary", "未知日程")
        calendar_id = data.get("calendar_id", "")

        notif_info = {
            "subtype": "calendar_reminder",
            "app_name": "Feishu",
            "notification_type": "calendar_event",
            "title": summary,
            "preview_text": f"新日程: {summary}",
            "thread_id": f"feishu_cal_{calendar_id}",
            "priority_hint": "normal",
            "timestamp": now,
        }

        event = self.event_generator.generate_notification_event(notif_info)
        self.event_sink.write_event(event)
        self._event_count += 1

        logger.info(f"[日历] 新日程: {summary}")

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_text_content(content_str: str, msg_type: str) -> str:
        """
        从飞书消息 content JSON 中提取可读文本。

        Args:
            content_str: 飞书消息 content 字段（JSON 字符串）
            msg_type: 消息类型（text / image / ...）

        Returns:
            提取出的文本内容
        """
        if msg_type == "text":
            try:
                content = json.loads(content_str)
                return content.get("text", "")
            except (json.JSONDecodeError, TypeError):
                return content_str
        elif msg_type == "image":
            return "[图片]"
        elif msg_type == "file":
            return "[文件]"
        elif msg_type == "post":
            # 富文本，尝试提取所有文本段
            try:
                content = json.loads(content_str)
                texts = []
                for line in content.get("content", []):
                    for elem in line:
                        if isinstance(elem, dict) and "text" in elem:
                            texts.append(elem["text"])
                return " ".join(texts)
            except (json.JSONDecodeError, TypeError):
                return "[富文本]"
        else:
            return f"[{msg_type}]"
