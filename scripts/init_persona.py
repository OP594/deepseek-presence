#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 persona.example.md 写进 AstrBot 的人格里。

    py init_persona.py            用 config.json 里的 name 替换 (名字)，写入 persona_id
    py init_persona.py 我的名字    临时指定名字

重复跑会覆盖同一条人格，不会重复插入。
"""

import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from settings import conf

ROOT = Path(__file__).resolve().parent.parent
PERSONA_FILE = ROOT / "persona.example.md"
DB = ROOT / "deps" / "astrbot-home" / "data" / "data_v4.db"


def main() -> None:
    if not DB.exists():
        print(f"找不到 AstrBot 的库：{DB}")
        print("先装好 AstrBot，再跑这个脚本。")
        return
    if not PERSONA_FILE.exists():
        print(f"找不到人格模板：{PERSONA_FILE}")
        return

    name = sys.argv[1] if len(sys.argv) > 1 else str(conf("name", "companion"))
    persona_id = str(conf("persona_id", "default"))

    text = PERSONA_FILE.read_text(encoding="utf-8").replace("(名字)", name)

    conn = sqlite3.connect(str(DB))
    try:
        row = conn.execute(
            "select 1 from personas where persona_id=?", (persona_id,)
        ).fetchone()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if row:
            conn.execute(
                "update personas set system_prompt=?, updated_at=? where persona_id=?",
                (text, now, persona_id),
            )
            action = "更新"
        else:
            conn.execute(
                "insert into personas (created_at, updated_at, persona_id, system_prompt,"
                " begin_dialogs, tools, skills, sort_order)"
                " values (?, ?, ?, ?, '[]', '[]', '[]', 0)",
                (now, now, persona_id, text),
            )
            action = "新建"
        conn.commit()
    finally:
        conn.close()

    print(f"人格已{action}：persona_id={persona_id}，名字={name}，{len(text)} 字")


if __name__ == "__main__":
    main()
