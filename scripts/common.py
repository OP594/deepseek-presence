#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""小工共用的东西：心跳、日志、读 AstrBot 配置/人格、OneBot token。

心跳间隔、日志格式、token 和 key 的读法都只有这一处。改这里，所有小工一起变。
"""

import sys
import glob
import json
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
BASE = SCRIPTS.parent
QQ = BASE  # 运行数据（logs/ data/ out/）都放在项目根
ASTRBOT = BASE / "deps" / "astrbot-home"


def heartbeat(name: str, interval: int = 30) -> None:
    """每 interval 秒写一次 logs/beat/<name>.txt，看护靠它判断死活。"""
    d = QQ / "logs" / "beat"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception:  # noqa: BLE001
        return
    f = d / f"{name}.txt"

    def _run() -> None:
        while True:
            try:
                f.write_text(str(time.time()), encoding="utf-8")
            except Exception:  # noqa: BLE001
                pass
            time.sleep(interval)

    threading.Thread(target=_run, daemon=True).start()


def log(name: str, msg: str) -> None:
    """追加一行到 logs/<name>.log。"""
    try:
        p = QQ / "logs" / f"{name}.log"
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}\n")
    except Exception:  # noqa: BLE001
        pass


def onebot_token() -> str:
    """从 SnowLuma 的 onebot 配置里读 accessToken。"""
    for path in glob.glob(str(BASE / "deps" / "SnowLuma" / "config" / "onebot_*.json")):
        try:
            data = json.load(open(path, encoding="utf-8-sig"))
            servers = data.get("networks", {}).get("httpServers") or []
            if servers:
                return servers[0].get("accessToken") or ""
        except Exception:  # noqa: BLE001
            continue
    return ""


def llm_config() -> tuple[str, str, str]:
    """从 AstrBot 配置里读 (api_base, key, model)。"""
    cfg = json.loads((ASTRBOT / "data" / "cmd_config.json").read_text(encoding="utf-8-sig"))
    src = cfg["provider_sources"][0]
    key = src["key"][0] if isinstance(src["key"], list) else src["key"]
    return src["api_base"], key, cfg["provider"][0]["model"]


def persona() -> str:
    """从 AstrBot 的库里读 default 人格。"""
    conn = sqlite3.connect(str(ASTRBOT / "data" / "data_v4.db"))
    try:
        row = conn.execute(
            "select system_prompt from personas where persona_id='default'"
        ).fetchone()
    finally:
        conn.close()
    return row[0] if row else ""


_MUTEXES: dict[str, object] = {}


def single_instance(name: str) -> bool:
    """同一个名字只允许一个进程。第二个实例返回 False。"""
    if sys.platform != "win32":
        return True
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.CreateMutexW(None, False, f"Global\\companion_{name}")
        if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
            return False
        _MUTEXES[name] = handle
        return True
    except Exception:  # noqa: BLE001
        return True
