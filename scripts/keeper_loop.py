#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""每分钟检查一次，缺什么补什么。开机时由 start-all.bat 静默拉起。

锁文件里记 pid：进程真的不在了才算过期，所以重启它不会被自己的旧锁挡住。
每轮重新加载 keeper 模块，改完 keeper.py 不用重启这个循环。
"""

import ctypes
import importlib
import json
import os
import time
from pathlib import Path

import keeper

LOCK = Path(__file__).resolve().parent / "logs" / "keeper.lock"
STALE = 180  # 没有 pid 可查时，锁文件超过这么久没刷新就当上一份已经死了
SYNCHRONIZE = 0x00100000


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    handle = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, pid)
    if not handle:
        return False
    ctypes.windll.kernel32.CloseHandle(handle)
    return True


def already_running() -> bool:
    """单实例：锁里的进程还活着就直接退出，免得重复拉小工。"""
    try:
        data = json.loads(LOCK.read_text(encoding="utf-8"))
        if isinstance(data, dict) and pid_alive(int(data.get("pid", 0))):
            return True
    except Exception:  # noqa: BLE001
        try:
            if time.time() - LOCK.stat().st_mtime < STALE:
                return True
        except Exception:  # noqa: BLE001
            pass
    write_lock()
    return False


def write_lock() -> None:
    try:
        LOCK.parent.mkdir(parents=True, exist_ok=True)
        LOCK.write_text(
            json.dumps({"pid": os.getpid(), "ts": time.time()}), encoding="utf-8"
        )
    except Exception:  # noqa: BLE001
        pass


def main() -> None:
    if already_running():
        return
    while True:
        write_lock()
        try:
            importlib.reload(keeper)
            keeper.main()
        except Exception:  # noqa: BLE001
            pass
        time.sleep(60)


if __name__ == "__main__":
    main()
