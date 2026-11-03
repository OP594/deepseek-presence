#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""每 1 小时自动备份一次。开机时由 start-all.bat 静默拉起。

注意：启动后先立刻备份一次，再按小时循环。
（以前是先睡一小时——小工一重启计时就重置，结果可能永远等不到第一次备份。）
"""

import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import backup  # noqa: E402
import common  # noqa: E402


def main() -> None:
    if not common.single_instance("backup"):
        return
    common.heartbeat("backup")
    while True:
        try:
            backup.main()
            common.log("backup", "备份完成")
        except Exception as exc:  # noqa: BLE001
            common.log("backup", f"备份失败：{type(exc).__name__}: {exc}")
        time.sleep(3600)


if __name__ == "__main__":
    main()
