#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""给 VBS 用的 AstrBot 入口：不带控制台窗口，日志按 UTF-8 写到 logs/astrbot.log。"""

import sys

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

sys.argv = ["astrbot", "run", "-p", "6185"]

from astrbot.cli.__main__ import cli  # noqa: E402

cli()
