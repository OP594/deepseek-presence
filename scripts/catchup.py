#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""开机补发：把她不在时收到的消息找出来，合成一次回复。

启动时跑一次。做法是拿 QQ 的聊天记录，找到她最后说过的那句，
之后所有用户消息都算"没回的"，合并成一次问她才回。

密钥不在本文件里：OneBot token 读 SnowLuma 的配置，模型和 key 读 AstrBot 的配置。
"""

import json
import sqlite3
import urllib.request
from datetime import datetime

import common

PLUGIN = common.ASTRBOT / "data" / "plugins" / "astrbot_plugin_fish_memory"

from settings import conf

UMO = str(conf("umo", ""))
FRIEND = int(conf("owner_qq", 0) or 0)


def log(msg: str) -> None:
    common.log("catchup", msg)


def onebot(action: str, payload: dict) -> dict:
    req = urllib.request.Request(
        f"http://127.0.0.1:3000/{action}",
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {common.onebot_token()}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def last_her_message() -> str:
    conn = sqlite3.connect(str(PLUGIN / "memory.db"))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "select content from messages where role='assistant' order by id desc limit 1"
    ).fetchone()
    conn.close()
    return (row["content"] if row else "").strip()


def new_messages_after(anchor: str) -> list[str]:
    data = onebot("get_friend_msg_history", {"user_id": FRIEND, "count": 40})
    msgs = (data.get("data") or {}).get("messages") or []
    texts: list[str] = []
    found = not anchor
    for m in msgs:
        raw = (m.get("raw_message") or "").strip()
        if not found:
            if anchor[:12] and anchor[:12] in raw:
                found = True
            continue
        if m.get("user_id") == FRIEND and raw:
            texts.append(raw)
    return texts


def main() -> None:
    anchor = last_her_message()
    pending = new_messages_after(anchor)
    # 去掉图片占位这类没信息量的
    pending = [t for t in pending if t not in ("[图片]", "[视频]", "[语音]")]
    if not pending:
        log("启动检查：没有漏回的消息")
        print("没有漏回的消息")
        return
    log(f"发现 {len(pending)} 条没回的消息：" + " / ".join(pending)[:200])

    conn = sqlite3.connect(str(common.ASTRBOT / "data" / "data_v4.db"))
    conn.row_factory = sqlite3.Row
    persona = common.persona()
    row = conn.execute(
        "select rowid as rid, content from conversations order by updated_at desc limit 1"
    ).fetchone()
    msgs = json.loads(row["content"])

    def text_of(m):
        t = m.get("content")
        if isinstance(t, list):
            t = " ".join(
                str(x.get("text", "")) for x in t if isinstance(x, dict) and x.get("type") == "text"
            )
        return str(t or "").split("<system_reminder>")[0].strip()

    convo = [{"role": "system", "content": persona}]
    for m in msgs[-8:]:
        if m.get("role") in ("user", "assistant"):
            convo.append({"role": m["role"], "content": text_of(m)})
    convo.append(
        {
            "role": "user",
            "content": "（你刚才不在线，这期间 ta 发来这些，按顺序：）\n"
            + "\n".join(pending),
        }
    )

    api_base, key, model = common.llm_config()
    body = {"model": model, "messages": convo, "temperature": 0.95, "max_tokens": 4096}
    req = urllib.request.Request(
        api_base.rstrip("/") + "/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=240) as r:
        res = json.loads(r.read())
    reply = (res["choices"][0]["message"].get("content") or "").strip()
    if not reply:
        log("模型没给出回复")
        return

    onebot("send_private_msg", {"user_id": FRIEND, "message": reply})
    msgs.append({"role": "user", "content": "\n".join(pending)})
    msgs.append({"role": "assistant", "content": reply})
    conn.execute(
        "update conversations set content=? where rowid=?",
        (json.dumps(msgs, ensure_ascii=False), row["rid"]),
    )
    conn.commit()

    mem = sqlite3.connect(str(PLUGIN / "memory.db"))
    for t in pending:
        mem.execute(
            "insert into messages(ts, umo, role, content) values (?,?,?,?)",
            (datetime.now().astimezone().isoformat(timespec="seconds"), UMO, "user", t),
        )
    mem.execute(
        "insert into messages(ts, umo, role, content) values (?,?,?,?)",
        (datetime.now().astimezone().isoformat(timespec="seconds"), UMO, "assistant", reply),
    )
    mem.commit()
    log("已补发：" + reply[:100])
    print("已补发：", reply)


if __name__ == "__main__":
    main()
