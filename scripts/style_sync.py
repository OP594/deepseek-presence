#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 style_rules.json 同步进人格和检查表。

改忌语只改 data/style_rules.json，然后跑这个脚本：
人格里【不要说的话】那一节会按文件重写一遍。
插件那边的检查表是运行时读文件的，不用重启。
"""

import json
import sqlite3
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
RULES = BASE / "QQ机器人" / "data" / "style_rules.json"
DB = BASE / "deps" / "astrbot-home" / "data" / "data_v4.db"
HEAD = "【不要说的话】"


def build_block(rules: dict) -> str:
    lines = [HEAD] + list(rules.get("persona_block") or [])
    return "\n".join(lines)


def main() -> None:
    rules = json.loads(RULES.read_text(encoding="utf-8"))
    block = build_block(rules)

    conn = sqlite3.connect(str(DB))
    row = conn.execute(
        "select system_prompt from personas where persona_id='default'"
    ).fetchone()
    if not row:
        print("没有 default 人格")
        return
    persona = row[0]

    i = persona.find(HEAD)
    if i == -1:
        print("人格里没有【不要说的话】，不改")
        return
    j = persona.find("【", i + len(HEAD))
    if j == -1:
        j = len(persona)

    new = persona[:i] + block + "\n\n" + persona[j:].lstrip()
    if new == persona:
        print("人格已经是同步的")
    else:
        conn.execute(
            "update personas set system_prompt=? where persona_id='default'", (new,)
        )
        conn.commit()
        print(f"人格已同步：{len(rules.get('banned', []))} 条忌语，"
              f"{len(rules.get('dialect', []))} 条方言")
    conn.close()


if __name__ == "__main__":
    main()
