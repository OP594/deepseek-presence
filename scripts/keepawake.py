#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按住系统不许睡：屏幕可以灭，机器不许进入睡眠。

Windows 的“现代待机”不看 powercfg 的空闲时间，屏幕一灭就可能进 S0 待机，
一待机她就断线。这个进程只要活着，系统就不会睡。
"""

import ctypes
import time

import common

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002  # 故意不加，屏幕该灭还灭


def main() -> None:
    common.heartbeat("awake")
    k32 = ctypes.windll.kernel32
    while True:
        # 每 30 秒重申一次，防止被别的程序顶掉
        k32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
        time.sleep(30)


if __name__ == "__main__":
    main()
