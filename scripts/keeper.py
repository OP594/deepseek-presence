#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""看护：缺什么就起什么。

由 Windows 计划任务每分钟跑一次，或者开机时由 start-all.bat 拉起的 keeper_loop 每分钟跑一次。
不依赖任何对话窗口。

判断"活着"靠两件事：
    AstrBot    —— 6185 端口
    SnowLuma   —— 3000 端口
    五个小工   —— 每 30 秒写一次的 heartbeat 文件

子进程的 stdout/stderr 落在 logs/<名字>.err，这样"起来了但立刻退出"能留下痕迹。
"""

import json
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
BASE = SCRIPTS.parent
QQ = BASE  # 运行数据（logs/ data/ out/）都放在项目根
DEPS = BASE / "deps"
VENV = DEPS / "venv" / "Scripts"
BEAT = QQ / "logs" / "beat"
LOG = QQ / "logs" / "keeper.log"
MARK = QQ / "logs" / ".starting.json"

NODE = shutil.which("node") or r"C:\Program Files\nodejs\node.exe"
FLAGS = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS


def log(msg: str) -> None:
    LOG.parent.mkdir(exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}\n")


def up(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.4)
        return s.connect_ex(("127.0.0.1", port)) == 0


def alive(name: str, max_age: int = 180) -> bool:
    f = BEAT / f"{name}.txt"
    try:
        return time.time() - float(f.read_text(encoding="utf-8").strip()) < max_age
    except Exception:  # noqa: BLE001
        return False


def marks() -> dict:
    try:
        return json.loads(MARK.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def mark(name: str) -> None:
    m = marks()
    m[name] = time.time()
    MARK.write_text(json.dumps(m), encoding="utf-8")


def recently_tried(name: str, wait: int = 120) -> bool:
    m = marks()
    return name in m and time.time() - m[name] < wait


def spawn(args: list[str], cwd: Path, name: str | None = None) -> bool:
    """起一个后台进程；name 给定时把它的输出留到 logs/<name>.err。"""
    out = subprocess.DEVNULL
    handle = None
    if name is not None:
        try:
            LOG.parent.mkdir(parents=True, exist_ok=True)
            handle = open(LOG.parent / f"{name}.err", "ab")
            out = handle
        except Exception:  # noqa: BLE001
            out = subprocess.DEVNULL
    try:
        proc = subprocess.Popen(
            args,
            cwd=str(cwd),
            creationflags=FLAGS,
            close_fds=True,
            stdout=out,
            stderr=out,
        )
        time.sleep(1.5)
        if proc.poll() is not None:
            # 多半是单实例锁把它挡住了：已经有一份在跑，别记成“起来了”
            log(f"{name or Path(args[0]).name} 启动后立刻退出（已在运行），跳过")
            return False
        return True
    except Exception as exc:  # noqa: BLE001
        log(f"拉起失败 {args[0]}：{type(exc).__name__}: {exc}")
        return False
    finally:
        if handle is not None:
            handle.close()


DAEMONS = [
    ("qzone", "qzone_daemon.py"),
    ("backup", "backup_loop.py"),
    ("watchdog", "watchdog.py"),
    ("awake", "keepawake.py"),
    ("comments", "qzone_comments.py"),
    ("webproxy", "webproxy.py"),
    ("diary", "diary.py"),
    ("wakeguard", "wakeguard.py"),
]


def main() -> None:
    actions: list[str] = []

    if not up(3000) and not up(5099) and not recently_tried("snowluma"):
        mark("snowluma")
        if spawn([NODE, "index.mjs"], DEPS / "SnowLuma", "snowluma"):
            actions.append("SnowLuma 起来了")

    if (up(3000) or up(5099)) and not up(6185) and not up(6199) and not recently_tried("astrbot"):
        mark("astrbot")
        if spawn(["wscript.exe", str(QQ / "start-astrbot.vbs")], QQ):
            actions.append("AstrBot 起来了")

    for name, script in DAEMONS:
        if alive(name):
            continue
        if recently_tried(f"d-{name}", 150):
            continue
        path = QQ / script
        if not path.exists():
            # 脚本被删了就记一次，别每轮都重试
            if not recently_tried(f"missing-{name}", 3600):
                mark(f"missing-{name}")
                log(f"{script} 不存在，跳过")
            continue
        mark(f"d-{name}")
        if spawn([str(VENV / "pythonw.exe"), str(path)], QQ, name):
            actions.append(f"{script} 起来了")

    # 每 5 分钟补一次断线期间漏回的消息（catchup 自己会判断有没有）
    if not recently_tried("catchup", 300):
        mark("catchup")
        try:
            subprocess.Popen(
                [str(VENV / "python.exe"), str(QQ / "catchup.py")],
                cwd=str(QQ),
                creationflags=FLAGS,
                close_fds=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as exc:  # noqa: BLE001
            log(f"catchup 拉起失败：{type(exc).__name__}: {exc}")

    if actions:
        log("；".join(actions))
        print("；".join(actions))
    elif "--verbose" in sys.argv:
        print("都好好的")


if __name__ == "__main__":
    main()

