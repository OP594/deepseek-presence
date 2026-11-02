from __future__ import annotations

import json
import random
import time
from pathlib import Path

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register

PLUGIN_ID = "astrbot_plugin_room_nudge"
STATE = Path(__file__).resolve().parent / "state.json"

NUDGE = (
    "【屋里】你有阵子没动屋子了。今天想添一样小东西、或者把什么挪个位置吗？"
    "想好了就调 decorate_room，做完顺口跟她提一句就行，别反复说。"
)


@register(PLUGIN_ID, "deepseek-presence", "隔一阵提醒她动动屋子", "1.0.0")
class RoomNudgePlugin(Star):
    def __init__(self, context: Context, config=None) -> None:
        super().__init__(context)
        self.config = config or {}
        self.enabled = bool(self.config.get("enabled", True))
        self.min_hours = max(1, int(self.config.get("min_hours", 20) or 20))
        self.max_hours = max(self.min_hours, int(self.config.get("max_hours", 36) or 36))
        self._state: dict[str, dict] = self._load()

    def _load(self) -> dict:
        try:
            data = json.loads(STATE.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:  # noqa: BLE001
            return {}

    def _save(self) -> None:
        try:
            STATE.write_text(json.dumps(self._state, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[room_nudge] 状态写入失败: {exc}")

    def _next_gap(self) -> float:
        return random.uniform(self.min_hours, self.max_hours) * 3600

    @filter.on_llm_request()
    async def inject(self, event: AstrMessageEvent, req) -> None:
        if not self.enabled:
            return
        umo = event.unified_msg_origin
        now = time.time()
        item = self._state.get(umo) or {}
        due = float(item.get("next") or 0)
        if not due:
            self._state[umo] = {"next": now + self._next_gap()}
            self._save()
            return
        if now < due:
            return
        req.prompt = f"{req.prompt or ''}\n\n{NUDGE}".strip()
        self._state[umo] = {"last": now, "next": now + self._next_gap()}
        self._save()
        logger.info("[room_nudge] 注入了“动动屋子”的提醒")
