#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""她的日记：每天 2-3 次，翻一翻今天做了什么、聊了什么，自己写一两句。

数据来源：
  · virtual_activity 的状态（现在在干嘛、最近的活动）
  · AstrBot 的对话库（最近几轮聊天）
写进 data/diary/YYYY-MM-DD.jsonl，同时渲染 out/日记.md。

    py diary.py          常驻（开机由 start-all 拉起，看护兜底）
    py diary.py --once   立刻写一条（测试用）
"""

import json
import random
import sys
import time
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

import common

QQ = common.QQ
STATE = (
    common.ASTRBOT
    / "data"
    / "plugin_data"
    / "astrbot_plugin_virtual_activity"
    / "state_default.json"
)
DIARY_DIR = QQ / "data" / "diary"
VIEW = QQ / "out" / "日记.md"

SLOTS = ("12:30", "19:30", "23:00")  # 一天写几次
JITTER_MIN = 20                     # 每个时间点前后随机挪几分钟
MIN_GAP_MIN = 90                    # 两条日记至少隔这么久


def log(msg: str) -> None:
    common.log("diary", msg)


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def recent_chat(limit: int = 10) -> str:
    import sqlite3

    try:
        conn = sqlite3.connect(str(common.ASTRBOT / "data" / "data_v4.db"))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "select content from conversations order by updated_at desc limit 1"
        ).fetchone()
        conn.close()
    except Exception:  # noqa: BLE001
        return ""
    if not row:
        return ""
    out = []
    try:
        msgs = json.loads(row["content"])[-limit:]
    except Exception:  # noqa: BLE001
        return ""
    for m in msgs:
        t = m.get("content")
        if isinstance(t, list):
            t = " ".join(
                str(x.get("text", "")) for x in t if isinstance(x, dict) and x.get("type") == "text"
            )
        t = str(t or "").split("<system_reminder>")[0].strip()
        if t:
            out.append(("ta" if m.get("role") == "user" else "你") + "：" + t)
    return "\n".join(out)


def ask(state: dict, recent: list, chat: str) -> str:
    api_base, key, model = common.llm_config()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    acts = "\n".join(
        f"- {str(r.get('at') or '')[11:16]} {r.get('furniture_name') or ''} {r.get('effect_name') or ''}".strip()
        for r in recent[-6:]
    )
    beh = state.get("behavior") or {}
    here = f"{beh.get('furniture_name') or '屋里'}·{beh.get('name') or ''}" if beh else "没在做什么"
    prompt = (
        f"现在是 {now}。\n"
        f"你今天在家的活动（最近几条）：\n{acts or '（没有记录）'}\n\n"
        f"你现在在：{here}\n"
        f"你和 ta 最近聊到：\n{chat or '（最近没聊什么）'}\n\n"
        "ta 是女生，提到她一律用“她”，不要写成“他”。\n"
        "用第一人称写一两句今天的日记，像随手记下来的那样，20 到 80 个字，句子要完整。"
        "不要汇报口吻、不要列举、不要加引号、不要话题标签。只输出正文。"
    )
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": common.persona()},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.95,
        "max_tokens": 2048,
    }
    req = urllib.request.Request(
        api_base.rstrip("/") + "/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        data = json.loads(r.read())
    text = (data["choices"][0]["message"].get("content") or "").strip()
    text = text.strip("「」\"'“”").strip()
    if not text:
        return ""
    if len(text) > 300:
        # 写长了就截一下，别把它丢掉
        text = text[:300].rstrip() + "…"
    return text


def render() -> None:
    days: dict[str, list] = {}
    for p in sorted(DIARY_DIR.glob("*.jsonl")):
        try:
            lines = p.read_text(encoding="utf-8").splitlines()
        except Exception:  # noqa: BLE001
            continue
        for line in lines:
            try:
                e = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            days.setdefault(str(e.get("ts") or "")[:10], []).append(e)
    if not days:
        return
    out = ["# 日记", ""]
    for day in sorted(days, reverse=True):
        out.append(f"## {day}")
        for e in days[day]:
            out.append(f"- **{str(e.get('ts') or '')[11:16]}** {e.get('text') or ''}")
        out.append("")
    VIEW.parent.mkdir(parents=True, exist_ok=True)
    VIEW.write_text("\n".join(out), encoding="utf-8")


def last_entry_at() -> datetime | None:
    p = DIARY_DIR / f"{datetime.now():%Y-%m-%d}.jsonl"
    try:
        lines = [l for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
        if not lines:
            return None
        return datetime.fromisoformat(json.loads(lines[-1])["ts"])
    except Exception:  # noqa: BLE001
        return None


def tick() -> None:
    last = last_entry_at()
    if last is not None and (datetime.now().astimezone() - last).total_seconds() < MIN_GAP_MIN * 60:
        log("刚写过没多久，跳过")
        return
    state = load_state()
    recent = state.get("recent_behaviors") or []
    chat = recent_chat()
    if not recent and not chat:
        log("没有可写的内容，跳过")
        return
    try:
        text = ask(state, recent, chat)
    except Exception as exc:  # noqa: BLE001
        log(f"写不出来：{type(exc).__name__}: {exc}")
        return
    if not text:
        log("模型没有给出内容")
        return
    now = datetime.now().astimezone()
    p = DIARY_DIR / f"{now:%Y-%m-%d}.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": now.isoformat(timespec="seconds"), "text": text}, ensure_ascii=False) + "\n")
    render()
    log("写了：" + text[:60])


def next_due(now: datetime) -> datetime:
    picks = []
    for offset in (0, 1):
        day = (now + timedelta(days=offset)).date()
        for slot in SLOTS:
            h, m = map(int, slot.split(":"))
            t = datetime(day.year, day.month, day.day, h, m).astimezone()
            t += timedelta(minutes=random.uniform(-JITTER_MIN, JITTER_MIN))
            if t > now:
                picks.append(t)
    return min(picks)


def main() -> None:
    if not common.single_instance("diary"):
        return
    if "--once" in sys.argv:
        tick()
        return
    common.heartbeat("diary")
    render()
    log("日记启动")
    while True:
        due = next_due(datetime.now().astimezone())
        while True:
            wait = (due - datetime.now().astimezone()).total_seconds()
            if wait <= 0:
                break
            time.sleep(min(wait, 300))
        tick()
        time.sleep(30)


if __name__ == "__main__":
    main()
