#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""看门狗：每 3 分钟敲一下 SnowLuma 的 OneBot 接口。

连续两次敲不通，就把监听 3000/5099 的那个 node 进程杀掉，让 start-all.bat 里的循环
把它重新拉起来。覆盖的是「进程还活着、但已经不收消息」那种卡死。

只杀占着这两个端口的进程，不再 taskkill /IM node.exe 全杀（那会连别的 node 一起带走）。
"""

import json
import subprocess
import time
import urllib.request

import common

PROBE = "http://127.0.0.1:3000/get_login_info"
INTERVAL = 180
MAX_FAILS = 2
PORTS = (3000, 5099)


def log(msg: str) -> None:
    common.log("watchdog", msg)


def probe(tok: str) -> bool:
    try:
        req = urllib.request.Request(
            PROBE,
            data=b"{}",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {tok}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        return data.get("status") == "ok"
    except Exception:  # noqa: BLE001
        return False


def listening_pids() -> set[str]:
    """谁在监听 3000/5099，就从 netstat 里把它的 pid 拿出来。"""
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
        if any(local.endswith(f":{port}") for port in PORTS):
            pids.add(parts[4])
    return pids


def restart_node() -> None:
    pids = listening_pids()
    if not pids:
        log("敲不通，但找不到监听 3000/5099 的进程；交给 keeper 处理")
        return
    for pid in sorted(pids):
        try:
            subprocess.run(
                ["taskkill", "/F", "/PID", pid],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=20,
            )
            log(f"已杀掉卡住的 SnowLuma（pid {pid}）")
        except Exception as exc:  # noqa: BLE001
            log(f"杀 pid {pid} 失败：{type(exc).__name__}: {exc}")


def main() -> None:
    if not common.single_instance("watchdog"):
        return
    common.heartbeat("watchdog")
    fails = 0
    while True:
        time.sleep(INTERVAL)
        tok = common.onebot_token()
        if not tok:
            continue
        if probe(tok):
            fails = 0
        else:
            fails += 1
            log(f"探测失败（{fails}/{MAX_FAILS}）")
            if fails >= MAX_FAILS:
                restart_node()
                fails = 0
                time.sleep(30)


if __name__ == "__main__":
    main()
