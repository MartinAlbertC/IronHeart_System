"""飞书 Bot 客户端，支持 WebSocket 和 Webhook 两种模式接收事件。"""

import logging
import json
import threading
from typing import Callable, Dict, Optional
from datetime import datetime

from src.core import config
from src.core.utils import setup_logger

logger = setup_logger(config.FEISHU_LOG_FILE)


class FeishuClient:
    """
    飞书 Bot 客户端。

    支持 WebSocket（长连接，本地直接运行）和 Webhook（HTTP 回调，需公网 IP）两种模式。
    通过 register() 注册事件回调，收到飞书事件后自动分发。

    支持的事件类型：
        - im.message.receive_v1          收到消息
        - im.chat.member.bot.added_v1    Bot 被加入群聊
        - im.chat.updated_v6             群聊信息更新
        - calendar.calendar.event.created_v6  日历事件创建
    """

    def __init__(
        self,
        app_id: str = config.FEISHU_APP_ID,
        app_secret: str = config.FEISHU_APP_SECRET,
        mode: str = config.FEISHU_BOT_MODE,
        verification_token: str = config.FEISHU_VERIFICATION_TOKEN,
        encrypt_key: str = config.FEISHU_ENCRYPT_KEY,
        webhook_port: int = config.FEISHU_WEBHOOK_PORT,
    ):
        self._app_id = app_id
        self._app_secret = app_secret
        self._mode = mode
        self._verification_token = verification_token
        self._encrypt_key = encrypt_key
        self._webhook_port = webhook_port
        self._callbacks: Dict[str, Callable] = {}
        self._running = False

    def register(self, event_type: str, callback: Callable):
        """
        注册事件回调。

        Args:
            event_type: 事件类型，如 'im.message.receive_v1'
            callback: 回调函数，签名为 callback(data: dict)
        """
        self._callbacks[event_type] = callback
        logger.info(f"注册事件回调: {event_type}")

    def start(self):
        """启动事件监听（阻塞）。"""
        import lark_oapi as lark

        if not self._app_id or not self._app_secret:
            raise ValueError(
                "飞书 App ID / App Secret 未配置。"
                "请在 config.py 或环境变量中设置。"
            )

        self._running = True
        logger.info(f"飞书客户端启动，模式: {self._mode}")

        # 构建 lark 事件分发器
        handler = self._build_dispatcher()

        if self._mode == "websocket":
            self._start_ws(handler)
        else:
            self._start_webhook(handler)

    def stop(self):
        """停止监听。"""
        self._running = False
        logger.info("飞书客户端停止")

    # ------------------------------------------------------------------
    # 事件分发器构建
    # ------------------------------------------------------------------

    def _build_dispatcher(self):
        """构建 lark-oapi 事件分发器，注册所有已有回调。"""
        import lark_oapi as lark

        builder = lark.EventDispatcherHandler.builder(
            self._verification_token, self._encrypt_key
        )

        # 消息事件
        if "im.message.receive_v1" in self._callbacks:
            builder.register_p2_im_message_receive_v1(self._on_message)

        # Bot 被加入群聊
        if "im.chat.member.bot.added_v1" in self._callbacks:
            builder.register_p2_im_chat_member_bot_added_v1(self._on_bot_added)

        # 群聊更新
        if "im.chat.updated_v6" in self._callbacks:
            builder.register_p2_im_chat_updated_v6(self._on_chat_updated)

        # 日历事件创建
        if "calendar.calendar.event.created_v6" in self._callbacks:
            builder.register_p2_calendar_calendar_event_created_v6(
                self._on_calendar_created
            )

        return builder.build()

    # ------------------------------------------------------------------
    # lark SDK 回调适配层
    # ------------------------------------------------------------------

    def _on_message(self, ctx, conf, event):
        """收到消息事件"""
        data = self._extract_event_data(event)
        self._dispatch("im.message.receive_v1", data)

    def _on_bot_added(self, ctx, conf, event):
        """Bot 被加入群聊"""
        data = self._extract_event_data(event)
        self._dispatch("im.chat.member.bot.added_v1", data)

    def _on_chat_updated(self, ctx, conf, event):
        """群聊信息更新"""
        data = self._extract_event_data(event)
        self._dispatch("im.chat.updated_v6", data)

    def _on_calendar_created(self, ctx, conf, event):
        """日历事件创建"""
        data = self._extract_event_data(event)
        self._dispatch("calendar.calendar.event.created_v6", data)

    @staticmethod
    def _extract_event_data(event) -> dict:
        """
        从 lark SDK 事件对象中提取数据字典。
        兼容不同版本的 lark-oapi 返回格式。
        """
        if hasattr(event, 'event'):
            obj = event.event
            if hasattr(obj, 'model_dump'):
                return obj.model_dump()
            elif hasattr(obj, 'to_dict'):
                return obj.to_dict()
            elif hasattr(obj, '__dict__'):
                return {k: v for k, v in obj.__dict__.items() if not k.startswith('_')}
        if hasattr(event, 'model_dump'):
            return event.model_dump()
        if hasattr(event, 'to_dict'):
            return event.to_dict()
        return {"raw": str(event)}

    def _dispatch(self, event_type: str, data: dict):
        """分发事件到已注册的回调。"""
        logger.debug(f"分发事件: {event_type}")
        if event_type in self._callbacks:
            try:
                self._callbacks[event_type](data)
            except Exception as e:
                logger.error(f"处理事件 {event_type} 时异常: {e}", exc_info=True)
        else:
            logger.warning(f"未注册回调的事件类型: {event_type}")

    # ------------------------------------------------------------------
    # WebSocket 模式
    # ------------------------------------------------------------------

    def _start_ws(self, handler):
        """WebSocket 长连接模式（推荐，无需公网 IP）。"""
        import lark_oapi as lark

        logger.info("WebSocket 模式启动...")
        ws_client = lark.ws.Client(
            self._app_id,
            self._app_secret,
            event_handler=handler,
            log_level=lark.LogLevel.DEBUG,
        )
        ws_client.start()

    # ------------------------------------------------------------------
    # Webhook 模式
    # ------------------------------------------------------------------

    def _start_webhook(self, handler):
        """Webhook HTTP 回调模式（需要公网 IP 或 ngrok 内网穿透）。"""
        try:
            from flask import Flask, request, make_response
        except ImportError:
            raise ImportError(
                "Webhook 模式需要 Flask，请安装: pip install flask"
            )

        logger.info(f"Webhook 模式启动，端口: {self._webhook_port}")

        app = Flask(__name__)

        @app.route("/webhook/event", methods=["POST"])
        def webhook():
            resp = handler.do(request)
            return resp

        app.run(host="0.0.0.0", port=self._webhook_port)
