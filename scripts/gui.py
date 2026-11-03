#!/usr/bin/env python3
# -*- coding: utf-8 -*-
""" 一个程序，两种用法。

双击（或 start-gui.bat）= 打开窗口，用按钮看：
    状态 / 今天 / 昨天 / 前天 / 日期 + 看这天 / 搜索
    记忆 / 日志 / 日期列表 / 生成总览

命令行 = 同样的东西打在终端里：
    py gui.py 状态
    py gui.py 日期
    py gui.py 对话 [10-30|昨天]
    py gui.py 找 拿铁
    py gui.py 记忆 / 日志
    py gui.py 忘记 某某
"""

import os
import socket
import sqlite3
import subprocess
import sys
import threading
import tkinter as tk
from datetime import datetime, timedelta
from pathlib import Path

from settings import name
from tkinter import ttk

BASE = Path(__file__).resolve().parent.parent
ASTRBOT = BASE / "deps" / "astrbot-home"
QQ = BASE / "QQ机器人"
OUT = QQ / "out" / "总览.md"
MEM = ASTRBOT / "data" / "plugins" / "astrbot_plugin_fish_memory" / "memory.db"
CJK = "Microsoft YaHei UI"


# ---------------- 数据 ----------------
def conn():
    c = sqlite3.connect(str(MEM))
    c.row_factory = sqlite3.Row
    return c


def port_open(p: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.4)
        return s.connect_ex(("127.0.0.1", p)) == 0


def parse_day(arg: str) -> str:
    today = datetime.now()
    if arg in ("今天", "today"):
        return today.strftime("%Y-%m-%d")
    if arg in ("昨天", "yesterday"):
        return (today - timedelta(days=1)).strftime("%Y-%m-%d")
    if arg == "前天":
        return (today - timedelta(days=2)).strftime("%Y-%m-%d")
    if len(arg) == 5:
        return f"{today.year}-{arg}"
    return arg


def status_lines() -> list[str]:
    lines = ["## 状态", ""]
    for name, p in (("AstrBot (6185)", 6185), ("OneBot (3000)", 3000), ("SnowLuma (5099)", 5099)):
        lines.append(f"- {name}：{'在跑' if port_open(p) else '**没起来**'}")
    try:
        c = conn()
        n_msg = c.execute("select count(*) from messages").fetchone()[0]
        n_fact = c.execute("select count(*) from facts").fetchone()[0]
        n_ref = c.execute("select count(*) from reflections").fetchone()[0]
        c.close()
        lines.append(f"- 记忆：{n_msg} 条对话、{n_fact} 条事实、{n_ref} 条反思")
    except Exception as exc:  # noqa: BLE001
        lines.append(f"- 记忆：读不到（{exc}）")
    return lines + [""]


def days_lines() -> list[str]:
    lines = ["## 有记录的日子", ""]
    try:
        c = conn()
        rows = c.execute(
            "select substr(ts,1,10) d, count(*) n from messages group by d order by d desc"
        ).fetchall()
        c.close()
        for r in rows:
            lines.append(f"- {r['d']}　{r['n']} 条")
    except Exception as exc:  # noqa: BLE001
        lines.append(f"（读不到：{exc}）")
    return lines + [""]


def dialogue_lines(day: str, limit: int = 2000) -> list[str]:
    lines = [f"## {day} 的对话", ""]
    try:
        c = conn()
        rows = c.execute(
            "select ts, role, content from messages where ts like ? order by id limit ?",
            (f"{day}%", limit),
        ).fetchall()
        c.close()
    except Exception as exc:  # noqa: BLE001
        return lines + [f"（读不到：{exc}）", ""]
    if not rows:
        return lines + ["（这天没有记录）", ""]
    lines += [f"共 {len(rows)} 条。", ""]
    for r in rows:
        who = "你" if r["role"] == "user" else "她"
        lines.append(f"**{r['ts'][11:16]}　{who}**　{r['content']}")
    return lines + [""]


def search_lines(kw: str) -> list[str]:
    lines = [f"## 含“{kw}”的记录", ""]
    try:
        c = conn()
        msgs = c.execute(
            "select ts, role, content from messages where content like ? order by id desc limit 60",
            (f"%{kw}%",),
        ).fetchall()
        facts = c.execute("select content from facts where content like ?", (f"%{kw}%",)).fetchall()
        c.close()
    except Exception as exc:  # noqa: BLE001
        return lines + [f"（读不到：{exc}）", ""]
    if facts:
        lines += ["**事实**", ""] + [f"- {f['content']}" for f in facts] + [""]
    if not msgs:
        return lines + ["（对话里没提过）", ""]
    lines += [f"**对话（最近 {len(msgs)} 条）**", ""]
    for r in reversed(msgs):
        who = "你" if r["role"] == "user" else "她"
        lines.append(f"**{r['ts'][5:16].replace('T', ' ')}　{who}**　{r['content']}")
    return lines + [""]


def diary_lines(limit: int = 40) -> list[str]:
    lines = ["## 她的日记", ""]
    try:
        text = (QQ / "out" / "日记.md").read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        return lines + ["（还没写过）", ""]
    body = [ln for ln in text.splitlines() if ln.strip() and not ln.startswith("# 日记")]
    if not body:
        return lines + ["（还没写过）", ""]
    lines += body[-limit:]
    return lines + [""]


def memory_lines() -> list[str]:
    lines = ["## 她记着的事", ""]
    try:
        c = conn()
        facts = [r["content"] for r in c.execute("select content from facts order by id desc")]
        refl = [
            r["content"]
            for r in c.execute("select content from reflections order by id desc limit 10")
        ]
        c.close()
    except Exception as exc:  # noqa: BLE001
        return lines + [f"（读不到：{exc}）", ""]
    lines += ["**事实**", ""] + [f"- {f}" for f in (facts or ["（空）"])]
    lines += ["", "**反思**", ""] + [f"- {r}" for r in (refl or ["（空）"])]
    return lines + [""]


def log_lines() -> list[str]:
    lines = ["## 她自己的动静", ""]
    for name, path in (
        ("说说/签名", QQ / "qzone.log"),
        ("补发", QQ / "catchup.log"),
    ):
        lines += [f"**{name}**", ""]
        try:
            tail = path.read_text(encoding="utf-8", errors="replace").splitlines()[-6:]
            lines += [f"- {t}" for t in tail] if tail else ["- （空）"]
        except Exception:  # noqa: BLE001
            lines.append("- （还没有）")
        lines.append("")
    return lines



PLUGIN_DATA = BASE / "deps" / "astrbot-home" / "data" / "plugin_data" / "astrbot_plugin_virtual_activity"


def activity_lines(limit: int = 15) -> list[str]:
    """她最近在屋里做了什么。"""
    import json as _json

    try:
        room = _json.loads((PLUGIN_DATA / "room.json").read_text(encoding="utf-8"))
        state = _json.loads((PLUGIN_DATA / "state_default.json").read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return [f"读不到她的屋子：{exc}"]

    names = {str(i.get("id")): i.get("name") for i in (room.get("furniture") or [])}
    beh = state.get("behavior") or {}
    lines = ["## 她现在"]
    if beh:
        lines.append(f"- 在{beh.get('furniture_name') or ''}，{beh.get('name') or ''}")
    else:
        lines.append("- 没在做什么")
    lines.append(f"- 精力 {int(state.get('energy') or 0)}　社交需求 {int(state.get('social_hunger') or 0)}")
    nxt = state.get("next_tick_at") or ""
    if nxt:
        lines.append(f"- 下次活动 {str(nxt)[11:16]}")
    lines.append("")
    lines.append("## 最近做过的事")
    for r in (state.get("recent_behaviors") or [])[-limit:][::-1]:
        when = str(r.get("at") or "")[11:16]
        lines.append(f"- {when}　{r.get('furniture_name') or names.get(str(r.get('furniture_id')), '')}：{r.get('effect_name') or r.get('name') or ''}")
    if not state.get("recent_behaviors"):
        lines.append("（还没有记录）")
    return lines



def build() -> Path:
    today = datetime.now().strftime("%Y-%m-%d")
    lines = ["# deepseek-presence · 总览", "", f"生成于 {datetime.now():%Y-%m-%d %H:%M}", ""]
    lines += status_lines()
    lines += dialogue_lines(today, limit=16)
    lines += memory_lines()
    lines += log_lines()
    lines += ["---", "", "翻历史：换日期重看，或者用搜索。", ""]
    OUT.write_text("\n".join(lines), encoding="utf-8")
    return OUT


def tidy(md: str) -> str:
    out = []
    for line in md.splitlines():
        line = line.replace("**", "")
        for pre in ("## ", "### ", "# ", "> ", "- "):
            if line.startswith(pre):
                line = ("· " + line[len(pre):]) if pre == "- " else line[len(pre):]
                break
        out.append(line)
    return "\n".join(out)


def _open_path(path: Path, notepad: bool = False) -> None:
    """在后台线程里打开文件，别把界面卡死。"""

    def _run() -> None:
        if notepad:
            try:
                subprocess.Popen(["notepad.exe", str(path)])
                return
            except Exception:  # noqa: BLE001
                pass
        try:
            os.startfile(str(path))
        except Exception:  # noqa: BLE001
            pass

    threading.Thread(target=_run, daemon=True).start()


# ---------------- 窗口 ----------------
class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title(name())
        root.geometry("1000x700")
        root.configure(bg="#faf8f4")

        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TButton", font=(CJK, 10), padding=6)
        style.configure("TLabel", font=(CJK, 10), background="#faf8f4")
        style.configure("TEntry", font=(CJK, 10))

        top = ttk.Frame(root, padding=(10, 10, 10, 4))
        top.pack(fill="x")
        for text, fn in (
            ("状态", self.show_status),
            ("今天", lambda: self.show_day(datetime.now())),
            ("昨天", lambda: self.show_day(datetime.now() - timedelta(days=1))),
            ("前天", lambda: self.show_day(datetime.now() - timedelta(days=2))),
        ):
            ttk.Button(top, text=text, command=fn).pack(side="left", padx=(0, 6))
        ttk.Label(top, text="  日期").pack(side="left")
        self.day_var = tk.StringVar(value=datetime.now().strftime("%m-%d"))
        ttk.Entry(top, textvariable=self.day_var, width=10).pack(side="left", padx=4)
        ttk.Button(top, text="看这天", command=self.show_custom_day).pack(side="left")
        ttk.Label(top, text="   搜").pack(side="left")
        self.kw_var = tk.StringVar()
        ttk.Entry(top, textvariable=self.kw_var, width=12).pack(side="left", padx=4)
        ttk.Button(top, text="搜索", command=self.do_search).pack(side="left")

        mid = ttk.Frame(root, padding=(10, 0, 10, 4))
        mid.pack(fill="x")
        for text, fn in (
            ("她的家", self.show_web),
            ("活动", self.show_activity),
            ("日记", self.show_diary),
            ("记忆", self.show_memory),
            ("日志", self.show_log),
            ("日期列表", self.show_days),
            ("生成总览", self.make_overview),
        ):
            ttk.Button(mid, text=text, command=fn).pack(side="left", padx=(0, 6))

        body = ttk.Frame(root, padding=(10, 4, 10, 6))
        body.pack(fill="both", expand=True)
        self.text = tk.Text(
            body,
            wrap="word",
            font=(CJK, 11),
            bg="#fffdf9",
            fg="#3a322d",
            relief="flat",
            padx=14,
            pady=12,
            spacing1=2,
            spacing3=2,
        )
        bar = ttk.Scrollbar(body, command=self.text.yview)
        self.text.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        self.text.pack(side="left", fill="both", expand=True)

        self.status = ttk.Label(root, text="就绪", padding=(12, 2))
        self.status.pack(fill="x")
        self.show_status()

    def put(self, md: str, note: str = "") -> None:
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("1.0", tidy(md))
        self.text.configure(state="disabled")
        self.status.configure(text=note or f"更新于 {datetime.now():%H:%M:%S}")



    def show_web(self) -> None:
        """在窗口里看她的家（画布版，不依赖浏览器）。"""
        try:
            import room_app

            msg = room_app.open_window(self.root)
        except Exception as exc:  # noqa: BLE001
            self.put(f"打不开房间窗口：{type(exc).__name__}: {exc}")
            return
        self.put(
            f"{msg}\n\n"
            "· 点一件家具 → 让她过去\n"
            "· 拖动家具 → 摆位置（自动保存）\n"
            "· 每 10 秒刷新她的状态\n\n"
            "浏览器版（手动打开）：http://127.0.0.1:6186/room",
            msg,
        )

    def show_activity(self) -> None:
        self.put("\n".join(activity_lines()), "她最近的活动")

    def show_status(self) -> None:
        self.put("\n".join(status_lines()), "状态")

    def show_days(self) -> None:
        self.put("\n".join(days_lines()), "日期列表")

    def show_day(self, dt: datetime) -> None:
        day = dt.strftime("%Y-%m-%d")
        self.day_var.set(dt.strftime("%m-%d"))
        self.put("\n".join(dialogue_lines(day)), f"{day} 的对话")

    def show_custom_day(self) -> None:
        raw = self.day_var.get().strip()
        day = parse_day(raw) if raw else datetime.now().strftime("%Y-%m-%d")
        self.put("\n".join(dialogue_lines(day)), f"{day} 的对话")

    def do_search(self) -> None:
        kw = self.kw_var.get().strip()
        if not kw:
            self.status.configure(text="先输入要搜的词")
            return
        self.put("\n".join(search_lines(kw)), f"搜“{kw}”")

    def show_memory(self) -> None:
        self.put("\n".join(memory_lines()), "她记着的事")

    def show_diary(self) -> None:
        self.put("\n".join(diary_lines()), "她的日记")

    def show_log(self) -> None:
        self.put("\n".join(log_lines()), "她自己的动静")

    def make_overview(self) -> None:
        path = build()
        self.put(path.read_text(encoding="utf-8"), "总览已生成")
        _open_path(path, notepad=True)


# ---------------- 入口 ----------------
def console(args: list[str]) -> None:
    arg = args[0]
    if arg == "状态":
        print("\n".join(status_lines()))
    elif arg == "日期":
        print("\n".join(days_lines()))
    elif arg == "对话":
        day = parse_day(args[1]) if len(args) > 1 else datetime.now().strftime("%Y-%m-%d")
        print("\n".join(dialogue_lines(day)))
    elif arg == "找":
        if len(args) < 2:
            print("用法：py gui.py 找 关键词")
            return
        print("\n".join(search_lines(args[1])))
    elif arg == "网页":
        print("房间页地址（浏览器手动打开）：http://127.0.0.1:6186/room")
    elif arg == "活动":
        print("\n".join(activity_lines()))
    elif arg == "日记":
        print("\n".join(diary_lines()))
    elif arg == "记忆":
        print("\n".join(memory_lines()))
    elif arg == "日志":
        print("\n".join(log_lines()))
    elif arg == "忘记":
        if len(args) < 2:
            print("用法：py gui.py 忘记 关键词")
            return
        c = conn()
        n1 = c.execute("delete from facts where content like ?", (f"%{args[1]}%",)).rowcount
        n2 = c.execute("delete from reflections where content like ?", (f"%{args[1]}%",)).rowcount
        c.commit()
        c.close()
        print(f"忘了：事实 {n1} 条、反思 {n2} 条（含“{args[1]}”）")
    else:
        print(__doc__)


def main() -> None:
    if len(sys.argv) > 1:
        console(sys.argv[1:])
        return
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
