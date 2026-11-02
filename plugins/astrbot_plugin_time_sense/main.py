from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register

PLUGIN_ID = "astrbot_plugin_time_sense"
STATE = Path(__file__).resolve().parent / "state.json"


@register(PLUGIN_ID, "deepseek-presence", "让她知道你隔了多久才回来", "1.0.0")
class TimeSensePlugin(Star):
    """记住最后一条消息的时间，下次说话时把间隔带进上下文。"""

    def __init__(self, context: Context, config=None) -> None:
        super().__init__(context)
        self.config = config or {}
        self.enabled = bool(self.config.get("enabled", True))
        self.long_gap_hours = int(self.config.get("long_gap_hours", 24) or 24)
        self.note_gap_hours = int(self.config.get("note_gap_hours", 1) or 1)
        self.mention_long_gap = bool(self.config.get("mention_long_gap", True))
        self._last: dict[str, float] = self._load()
        self._gap: dict[str, tuple[float, float, float]] = {}  # umo -> (gap, computed_at, prev_ts)

    # ---------- 持久化 ----------
    def _load(self) -> dict[str, float]:
        try:
            data = json.loads(STATE.read_text(encoding="utf-8"))
            return {str(k): float(v) for k, v in data.items()}
        except Exception:  # noqa: BLE001
            return {}

    def _save(self) -> None:
        try:
            STATE.write_text(json.dumps(self._last, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[time_sense] 状态写入失败: {exc}")

    # ---------- 收消息：算间隔 ----------
    def _record(self, event: AstrMessageEvent) -> None:
        if not self.enabled:
            return
        umo = event.unified_msg_origin
        now = time.time()
        last = self._last.get(umo)
        if last:
            gap = now - last
            prev = self._gap.get(umo)
            if prev is None or gap > prev[0]:
                self._gap[umo] = (gap, now, last)
        self._last[umo] = now
        self._save()

    @filter.event_message_type(filter.EventMessageType.PRIVATE_MESSAGE, priority=-90)
    async def on_private(self, event: AstrMessageEvent) -> None:
        self._record(event)

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE, priority=-90)
    async def on_group(self, event: AstrMessageEvent) -> None:
        self._record(event)

    # ---------- 请求前：把间隔带进去 ----------
    @filter.on_llm_request()
    async def inject(self, event: AstrMessageEvent, req) -> None:
        if not self.enabled:
            return
        umo = event.unified_msg_origin
        item = self._gap.pop(umo, None)
        if not item:
            return
        gap, at, prev = item
        if time.time() - at > 600:  # 太久之前的间隔不算了
            return
        note_seconds = self.note_gap_hours * 3600
        if gap < note_seconds:
            return
        last_at = datetime.fromtimestamp(prev)
        if gap >= self.long_gap_hours * 3600:
            if gap >= 48 * 3600:
                desc = f"{gap / 86400:.0f} 天"
            else:
                desc = "一天多"
            text = (
                f"【时间感：她上次说话是 {last_at:%Y-%m-%d %H:%M}，到现在隔了 {desc}，"
                "她已经很久没来了。】"
            )
            if self.mention_long_gap:
                text += (
                    "你可以自然地表露一点想她，或者问问她这段时间怎么样；"
                    "别质问、别每次都提。"
                )
        else:
            text = f"【时间感：距上次对话 {gap / 3600:.0f} 小时（上次 {last_at:%m-%d %H:%M}）。】"
        req.prompt = f"{req.prompt or ''}\n\n{text}".strip()
        logger.info(f"[time_sense] 注入时间感：{gap / 3600:.1f} 小时")

