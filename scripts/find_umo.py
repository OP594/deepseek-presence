#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 AstrBot 的库里翻出会话 ID（umo），方便填进 config.json。

    py find_umo.py

先让机器人收到至少一条消息，再跑这个。
"""

import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "deps" / "astrbot-home" / "data" / "data_v4.db"


def rows_from(conn: sqlite3.Connection) -> list[tuple[str, int]]:
    for sql in (
        "select user_id, count(*) from conversations"
        " where user_id like '%FriendMessage%' group by user_id order by 2 desc limit 10",
        "select user_id, count(*) from conversations"
        " where user_id like '%:%' group by user_id order by 2 desc limit 10",
    ):
        try:
            got = conn.execute(sql).fetchall()
        except Exception:  # noqa: BLE001
            continue
        if got:
            return [(str(a), int(b)) for a, b in got]
    return []


def main() -> None:
    if not DB.exists():
        print(f"找不到库：{DB}")
        return
    conn = sqlite3.connect(str(DB))
    try:
        rows = rows_from(conn)
    finally:
        conn.close()

    if not rows:
        print("还没收到过消息。先让她收到一条，再跑一次。")
        return
    print("找到这些会话（把要用的那条填进 config.json 的 umo）：")
    for umo, n in rows:
        print(f"  {umo}    （{n} 条会话记录）")


if __name__ == "__main__":
    main()
