#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""她的自主时间：自己决定要不要发说说、要不要改签名。

每 45-90 分钟醒一次，看看要不要发。发不发、发什么、发多长，都由她自己定。
  只有一条硬限制：两次之间至少隔 30 分钟防抽风；其余不设上限
  签名：至少隔 12 小时，免得一小时改八遍

测试：
  python qzone_daemon.py --dry     只让她想，不真的发
  python qzone_daemon.py --once    立刻走一轮（会真的发）
"""

import json
import random
import sys
import time
import urllib.request
from datetime import datetime

import common

STATE = common.QQ / "data" / "qzone_state.json"

CHECK_EVERY = (45 * 60, 90 * 60)
POST_GAP = 30 * 60
POST_PER_DAY = 999
SIGN_GAP = 24 * 3600


def log(msg: str) -> None:
    common.log("qzone", msg)


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


def recent_chat(limit: int = 8) -> str:
    import sqlite3

    conn = sqlite3.connect(str(common.ASTRBOT / "data" / "data_v4.db"))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "select content from conversations order by updated_at desc limit 1"
    ).fetchone()
    conn.close()
    if not row:
        return ""
    msgs = json.loads(row["content"])[-limit:]
    out = []
    for m in msgs:
        t = m.get("content")
        if isinstance(t, list):
            t = " ".join(str(x.get("text", "")) for x in t if isinstance(x, dict))
        t = str(t or "").split("<system_reminder>")[0].strip()
        if t:
            out.append(f"{'ta' if m.get('role') == 'user' else '你'}: {t}")
    return "\n".join(out)


def ask(kind: str) -> str:
    api_base, key, model = common.llm_config()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    if kind == "post":
        task = (
            f"现在是 {now}。\n下面是你和 ta 最近的对话：\n{recent_chat()}\n\n"
            "你现在可以自己发一条 QQ 空间说说。"
            "除非你此刻特别想发，否则只输出 SKIP。"
            "如果想发，只输出正文。写多长随你，但说说是短东西，别写成小作文。别加引号、别解释、别写话题标签。"
        )
    else:
        task = (
            f"现在是 {now}。\n下面是你和 ta 最近的对话：\n{recent_chat()}\n\n"
            "你现在可以改一次 QQ 个性签名。"
            "除非你特别想改，否则只输出 SKIP。"
            "如果想改，只输出新签名，25 字以内，别加引号、别解释。"
        )

    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": common.persona()},
            {"role": "user", "content": task},
        ],
        "temperature": 0.9,
        "max_tokens": 2048,
    }
    req = urllib.request.Request(
        api_base.rstrip("/") + "/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as r:
        data = json.loads(r.read())
    text = (data["choices"][0]["message"].get("content") or "").strip()
    text = text.strip("「」\"'“”").strip()
    if not text or text.upper().startswith("SKIP") or len(text) > 200:
        return ""
    return text


def load_state() -> dict:
    if STATE.exists():
        try:
            return json.loads(STATE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"last_post": 0, "last_sign": 0, "day": "", "posts_today": 0}


def save_state(state: dict) -> None:
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def tick(dry: bool = False) -> None:
    state = load_state()
    now = time.time()
    today = datetime.now().strftime("%Y-%m-%d")
    if state.get("day") != today:
        state["day"] = today
        state["posts_today"] = 0

    if now - state.get("last_post", 0) >= POST_GAP and state.get("posts_today", 0) < POST_PER_DAY:
        text = ask("post")
        if text:
            if dry:
                print("[dry] 想发说说:", text)
            else:
                onebot("send_qzone_msg", {"content": text, "ugc_right": 4})
                state["last_post"] = now
                state["posts_today"] = state.get("posts_today", 0) + 1
                log(f"发说说：{text}")
                print("已发说说：", text)
        else:
            log("看了下，没发说说")
            print("这轮不发说说。")

    if now - state.get("last_sign", 0) >= SIGN_GAP:
        text = ask("sign")
        if text:
            if dry:
                print("[dry] 想改签名:", text)
            else:
                onebot("set_self_longnick", {"longNick": text})
                state["last_sign"] = now
                log(f"改签名：{text}")
                print("已改签名：", text)
        else:
            log("看了下，没改签名")
            print("这轮不改签名。")

    save_state(state)


def main() -> None:
    if not common.single_instance("qzone"):
        return
    if "--dry" in sys.argv:
        tick(dry=True)
        return
    if "--once" in sys.argv:
        tick()
        return
    common.heartbeat("qzone")
    log("自主时间启动")
    time.sleep(random.randint(300, 600))  # 刚启动别急着发
    while True:
        try:
            tick()
        except Exception as exc:  # noqa: BLE001
            log(f"出错：{type(exc).__name__}: {exc}")
        time.sleep(random.randint(*CHECK_EVERY))


if __name__ == "__main__":
    main()
