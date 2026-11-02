#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""睡醒之后把连接拉回来。

Windows 一睡，所有 TCP 连接都会断；醒来以后 SnowLuma 的 QQ 连接和 AstrBot 的
websocket 可能已经死了，但进程还活着、端口还占着，看门狗要等好几分钟才反应过来。

这个进程只做一件事：发现“刚刚睡过”（循环间隔异常变长），立刻检查连接，
不通就重启对应的进程，让 keeper 把它拉起来。
"""

import subprocess
import time
import urllib.request

import common
import watchdog

GAP_SECONDS = 90       # 20 秒的循环，间隔超过 90 秒就当作睡过
CHECK_SECONDS = 60     # 醒来后给网络 60 秒恢复
PORTS_ASTRBOT = (6185, 6199)


def log(msg: str) -> None:
    common.log("wakeguard", msg)


def _listening_pids(ports: tuple[int, ...]) -> set[str]:
    pids: set[str] = set()
    try:
        out = subprocess.run(
            ["netstat", "-ano", "-p", "TCP"],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=20,
        ).stdout
    except Exception as exc:  # noqa: BLE001
        log(f"netstat 失败：{type(exc).__name__}: {exc}")
        return pids
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 5 or parts[3].upper() != "LISTENING":
            continue
        local = parts[1]
        if any(local.endswith(f":{port}") for port in ports):
            pids.add(parts[4])
    return pids


def _astrbot_alive() -> bool:
    try:
        with urllib.request.urlopen("http://127.0.0.1:6185/", timeout=5) as resp:
            return resp.status < 500
    except Exception:  # noqa: BLE001
        return False


def check_snowluma(seconds: int) -> bool:
    tok = common.onebot_token()
    if not tok:
        return False
    deadline = time.time() + seconds
    while time.time() < deadline:
        if watchdog.probe(tok):
            return True
        time.sleep(5)
    return False


def restart_astrbot() -> None:
    pids = _listening_pids(PORTS_ASTRBOT)
    if not pids:
        log("找不到监听 6185/6199 的进程，交给 keeper")
        return
    for pid in sorted(pids):
        try:
            subprocess.run(
                ["taskkill", "/F", "/PID", pid],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=20,
            )
            log(f"已杀掉卡住的 AstrBot（pid {pid}）")
        except Exception as exc:  # noqa: BLE001
            log(f"杀 pid {pid} 失败：{type(exc).__name__}: {exc}")


def main() -> None:
    common.heartbeat("wakeguard")
    last = time.monotonic()
    while True:
        time.sleep(20)
        now = time.monotonic()
        gap = now - last
        last = now
        if gap <= GAP_SECONDS:
            continue

        log(f"检测到睡眠 {gap:.0f} 秒，开始检查连接")
        if check_snowluma(CHECK_SECONDS):
            log("醒来后 SnowLuma 正常")
        else:
            log("醒来后 SnowLuma 不通，重启它")
            watchdog.restart_node()
            time.sleep(20)
            if check_snowluma(CHECK_SECONDS):
                log("SnowLuma 已恢复")
            else:
                log("SnowLuma 重启后仍不通，交给 keeper/watchdog")

        if _astrbot_alive():
            log("醒来后 AstrBot 正常")
        else:
            log("醒来后 AstrBot 不响应，重启它")
            restart_astrbot()


if __name__ == "__main__":
    main()
