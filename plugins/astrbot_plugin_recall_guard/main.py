from __future__ import annotations

import json
import time

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register

PLUGIN_ID = "astrbot_plugin_recall_guard"
RECALL_NOTICES = ("friend_recall", "group_recall")


@register(PLUGIN_ID, "deepseek-presence", "撤回的消息不回复、也不留在上下文里", "1.1.0")
class RecallGuardPlugin(Star):
    """撤回处理：

    1. 撤回通知本身不回复；
    2. 被撤回消息的回复如果还没发出去，丢掉；
    3. 把被撤回的那条用户消息（连带它后面那条回复）从会话上下文里删掉。
    """

    def __init__(self, context: Context, config=None) -> None:
        super().__init__(context)
        self._recent: dict[str, dict] = {}   # message_id -> {"text", "umo", "ts"}
        self._recalled: dict[str, float] = {}
        self.recent_ttl = 1800
        self.recalled_ttl = 300

    # ---------- 记下每条消息的 id 和文字，撤回时才认得出是哪条 ----------
    def _record(self, event: AstrMessageEvent) -> None:
        raw = getattr(event.message_obj, "raw_message", None)
        if isinstance(raw, dict) and raw.get("post_type") == "notice":
            return
        mid = str(getattr(event.message_obj, "message_id", "") or "")
        text = str(getattr(event, "message_str", "") or "").strip()
        if not mid or not text:
            return
        self._recent[mid] = {
            "text": text,
            "umo": event.unified_msg_origin,
            "ts": time.time(),
        }
        now = time.time()
        self._recent = {
            k: v for k, v in self._recent.items() if now - v["ts"] < self.recent_ttl
        }

    def _recall_id(self, event: AstrMessageEvent) -> str | None:
        raw = getattr(event.message_obj, "raw_message", None)
        if not isinstance(raw, dict):
            return None
        if raw.get("post_type") != "notice":
            return None
        if raw.get("notice_type") not in RECALL_NOTICES:
            return None
        mid = raw.get("message_id")
        return str(mid) if mid is not None else "0"

    @filter.event_message_type(filter.EventMessageType.PRIVATE_MESSAGE, priority=-100)
    async def on_private(self, event: AstrMessageEvent) -> None:
        await self._handle(event)

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE, priority=-100)
    async def on_group(self, event: AstrMessageEvent) -> None:
        await self._handle(event)

    async def _handle(self, event: AstrMessageEvent) -> None:
        mid = self._recall_id(event)
        if mid is None:
            self._record(event)
            return
        self._recalled[mid] = time.time()
        info = self._recent.pop(mid, None)
        logger.info(f"[recall_guard] 收到撤回通知：message_id={mid}")
        if info:
            await self._drop_from_history(info["umo"], info["text"])
        event.stop_event()

    # ---------- 从上下文里删掉被撤回的消息 ----------
    async def _drop_from_history(self, umo: str, text: str) -> None:
        try:
            cm = self.context.conversation_manager
            cid = await cm.get_curr_conversation_id(umo)
            if not cid:
                return
            conv = await cm.get_conversation(umo, cid)
            if conv is None:
                return
            history = getattr(conv, "history", None)
            if isinstance(history, str):
                history = json.loads(history)
            history = history or []
            target = text.split("<system_reminder>")[0].strip()

            idx = None
            for i in range(len(history) - 1, -1, -1):
                item = history[i]
                if item.get("role") != "user":
                    continue
                content = item.get("content")
                if isinstance(content, list):
                    content = " ".join(
                        str(p.get("text", ""))
                        for p in content
                        if isinstance(p, dict) and p.get("type") == "text"
                    )
                if str(content or "").split("<system_reminder>")[0].strip() == target:
                    idx = i
                    break
            if idx is None:
                logger.info("[recall_guard] 上下文里没找到对应消息，跳过")
                return

            dropped_reply = False
            if idx + 1 < len(history) and history[idx + 1].get("role") == "assistant":
                history.pop(idx + 1)
                dropped_reply = True
            history.pop(idx)
            await cm.update_conversation(umo, cid, history=history)
            logger.info(
                f"[recall_guard] 已从上下文删除被撤回的消息：{target[:30]}"
                f"{'（连带 1 条回复）' if dropped_reply else ''}"
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[recall_guard] 清理上下文失败: {type(exc).__name__}: {exc}")

    # ---------- 回复还没发出去的话，丢掉 ----------
    @filter.on_decorating_result()
    async def drop_reply_for_recalled(self, event: AstrMessageEvent) -> None:
        now = time.time()
        self._recalled = {
            k: v for k, v in self._recalled.items() if now - v < self.recalled_ttl
        }
        mid = str(getattr(event.message_obj, "message_id", "") or "")
        if not mid or mid not in self._recalled:
            return
        result = event.get_result()
        if result is not None and getattr(result, "chain", None):
            result.chain.clear()
            logger.info(f"[recall_guard] 消息 {mid} 已被撤回，取消回复")
