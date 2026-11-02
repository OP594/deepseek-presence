#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""唯一的配置入口。

项目根目录下放一个 config.json（从 config.example.json 复制一份改），
所有脚本都从这里读名字、QQ 号、会话 ID、端口。

    from settings import conf
    conf("owner_qq")
"""

import json
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parent
CONFIG = ROOT / "config.json"

DEFAULTS = {
    # 显示用：她叫什么
    "name": "companion",
    # 你自己的 QQ 号（消息发给他）
    "owner_qq": 0,
    # 机器人自己的 QQ 号
    "self_qq": 0,
    # 私聊会话 ID，形如 snowluma:FriendMessage:123456
    "umo": "",
    # 用哪个人格（AstrBot personas 表里的 persona_id）
    "persona_id": "default",
    # 端口
    "onebot_port": 3000,
    "astrbot_port": 6185,
    "proxy_port": 6186,
}

_cache: dict | None = None


def load() -> dict:
    global _cache
    if _cache is not None:
        return _cache
    data = dict(DEFAULTS)
    try:
        data.update(json.loads(CONFIG.read_text(encoding="utf-8-sig")))
    except Exception:  # noqa: BLE001
        pass
    _cache = data
    return data


def conf(key: str, default=None):
    v = load().get(key)
    return default if v in (None, "") else v


def name() -> str:
    return str(conf("name", "companion"))
