#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在窗口里看她的家——tkinter 画布版，不依赖任何浏览器。

数据来自 AstrBot 的 virtual_activity 插件（经本地代理 6186）：
    GET  /room         房间（家具坐标、画布尺寸）
    GET  /state        她现在在哪、精力、社交需求、下次活动
    POST /trigger      让她去某件家具（点家具）
    POST /room/save    保存家具位置（拖动后）

用法：
    import room_app; room_app.open_window(root)
"""

import json
import subprocess
import sys
import threading
import time
import tkinter as tk
import urllib.request
from pathlib import Path

API = "http://127.0.0.1:6186/api/plug/astrbot_plugin_virtual_activity"
FONT = "Microsoft YaHei UI"
EMOJI_FONT = "Segoe UI Emoji"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

_window = None  # 单例：再次点「她的家」时把窗口提到前面


def _get(path: str) -> dict:
    with urllib.request.urlopen(API + path, timeout=4) as r:
        return json.loads(r.read())


def start_proxy() -> None:
    """房间接口没响应时，顺手把本地代理拉起来。"""
    q = Path(__file__).resolve().parent
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe")
    try:
        subprocess.Popen(
            [str(pyw if pyw.exists() else exe), str(q / "webproxy.py")],
            cwd=str(q),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=NO_WINDOW,
        )
    except Exception:  # noqa: BLE001
        return
    for _ in range(20):
        try:
            _get("/room")
            return
        except Exception:  # noqa: BLE001
            time.sleep(0.4)


def _post(path: str, payload: dict) -> dict:
    req = urllib.request.Request(
        API + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=8) as r:
        return json.loads(r.read())


class RoomWindow:
    def __init__(self, master: tk.Misc) -> None:
        self.top = tk.Toplevel(master)
        self.top.title("她的家")
        self.top.configure(bg="#f6f2ec")
        self.top.geometry("1040x820")

        head = tk.Frame(self.top, bg="#fffdf9")
        head.pack(fill="x")
        self.lbl_name = tk.Label(
            head, text="她的家", font=(FONT, 14, "bold"), bg="#fffdf9", fg="#2c2622"
        )
        self.lbl_name.pack(side="left", padx=(18, 12), pady=10)
        self.lbl_where = tk.Label(head, text="读状态中…", font=(FONT, 10), bg="#fffdf9", fg="#8c7f76")
        self.lbl_where.pack(side="left", padx=8)
        self.lbl_stats = tk.Label(head, text="", font=(FONT, 10), bg="#fffdf9", fg="#8c7f76")
        self.lbl_stats.pack(side="left", padx=8)
        self.lbl_next = tk.Label(head, text="", font=(FONT, 10), bg="#fffdf9", fg="#8c7f76")
        self.lbl_next.pack(side="left", padx=8)

        self.canvas = tk.Canvas(
            self.top, bg="#f3ece2", highlightthickness=0, width=1000, height=700
        )
        self.canvas.pack(padx=18, pady=(12, 6))

        self.status = tk.Label(
            self.top, text="点家具＝让她过去；拖动家具＝摆位置", font=(FONT, 9),
            bg="#f6f2ec", fg="#8c7f76",
        )
        self.status.pack(fill="x", pady=(0, 8))

        self.room = None
        self.state = None
        self.items = {}
        self.drag = None
        self.closed = False

        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.top.protocol("WM_DELETE_WINDOW", self.close)

        self.load()
        self.top.after(10000, self.poll)

    # ---------- 数据 ----------
    def load(self) -> None:
        def fetch() -> None:
            data = _get("/room")
            self.room = data["room"]
            self.state = data.get("status", {}).get("state") or _get("/state")["status"]["state"]

        try:
            fetch()
        except Exception as first:  # noqa: BLE001
            start_proxy()
            try:
                fetch()
            except Exception as second:  # noqa: BLE001
                self.status.configure(
                    text=f"房间接口没起来（6186）：{type(second).__name__}: {second}"
                    f"（首次：{type(first).__name__}）"
                )
                return
        self.draw()
        self.update_head()

    def poll(self) -> None:
        if self.closed:
            return
        try:
            self.state = _get("/state")["status"]["state"]
            self.update_head()
            self.draw_badge()
        except Exception:  # noqa: BLE001
            pass
        if not self.closed:
            self.top.after(10000, self.poll)

    # ---------- 画 ----------
    def draw(self) -> None:
        cv = self.canvas
        cv.delete("all")
        self.items.clear()
        if not self.room:
            return
        meta = self.room.get("room") or {}
        canvas_meta = meta.get("canvas") or {}
        w = int(canvas_meta.get("width") or 1000)
        h = int(canvas_meta.get("height") or 700)
        cv.configure(width=w, height=h, bg=canvas_meta.get("background") or "#f3ece2")
        self.lbl_name.configure(text=meta.get("name") or "她的家")

        for it in self.room.get("furniture", []):
            if it.get("enabled") is False:
                continue
            x, y = float(it.get("x", 0)), float(it.get("y", 0))
            fw, fh = float(it.get("w", 100)), float(it.get("h", 80))
            rect = cv.create_rectangle(
                x, y, x + fw, y + fh,
                fill=it.get("color") or "#d8cfc4", outline="#cec4ba", width=2,
                tags=("furn", it["id"]),
            )
            emoji = cv.create_text(
                x + fw / 2, y + fh / 2 - 10, text=it.get("emoji") or "▫",
                font=(EMOJI_FONT, 26), tags=("furn", it["id"]),
            )
            label = cv.create_text(
                x + fw / 2, y + fh - 16, text=it.get("name") or "",
                font=(FONT, 10), fill="#4a423c", tags=("furn", it["id"]),
            )
            self.items[rect] = it
            self.items[emoji] = it
            self.items[label] = it

        self.draw_badge()

    def draw_badge(self) -> None:
        self.canvas.delete("badge")
        pos = (self.state or {}).get("position") or {}
        x, y = pos.get("x"), pos.get("y")
        if x is None or y is None:
            return
        r = 19
        self.canvas.create_oval(
            x - r, y - r - 30, x + r, y + r - 30,
            fill="#347c68", outline="", tags="badge",
        )
        self.canvas.create_text(
            x, y - 30, text="鲸", font=(FONT, 11, "bold"), fill="#fff", tags="badge",
        )

    def update_head(self) -> None:
        st = self.state or {}
        b = st.get("behavior") or {}
        if b.get("furniture_name"):
            where = f"她现在：{b['furniture_name']}，{b.get('name') or ''}"
        else:
            where = "她现在：没在做什么"
        self.lbl_where.configure(text=where)
        self.lbl_stats.configure(
            text=f"精力 {round(st.get('energy') or 0)}　社交需求 {round(st.get('social_hunger') or 0)}"
        )
        n = st.get("next_tick_in_sec")
        self.lbl_next.configure(text=f"下次活动 {round(n / 60)} 分钟后" if n else "")

    # ---------- 交互 ----------
    def furniture_at(self, event):
        for item in self.canvas.find_overlapping(
            event.x - 1, event.y - 1, event.x + 1, event.y + 1
        ):
            if item in self.items:
                return self.items[item]
        return None

    def on_press(self, event) -> None:
        furn = self.furniture_at(event)
        if furn is None:
            self.drag = None
            return
        self.drag = {"furn": furn, "x": event.x, "y": event.y, "moved": False}

    def on_drag(self, event) -> None:
        if not self.drag:
            return
        furn = self.drag["furn"]
        dx, dy = event.x - self.drag["x"], event.y - self.drag["y"]
        if abs(dx) > 3 or abs(dy) > 3:
            self.drag["moved"] = True
        furn["x"] = max(0, min(1000 - float(furn.get("w", 100)), float(furn.get("x", 0)) + dx))
        furn["y"] = max(0, min(700 - float(furn.get("h", 80)), float(furn.get("y", 0)) + dy))
        self.drag["x"], self.drag["y"] = event.x, event.y
        self.draw()

    def on_release(self, event) -> None:
        if not self.drag:
            return
        furn, moved = self.drag["furn"], self.drag["moved"]
        self.drag = None
        if moved:
            self.status.configure(text="位置存好了")
            threading.Thread(target=self.save_room, daemon=True).start()
        else:
            self.status.configure(text=f"让她去{furn.get('name')}…")
            threading.Thread(target=self.trigger, args=(furn["id"],), daemon=True).start()

    def trigger(self, furniture_id: str) -> None:
        try:
            _post("/trigger", {"furniture_id": furniture_id})
        except Exception as exc:  # noqa: BLE001
            self.top.after(0, lambda: self.status.configure(text=f"没去成：{exc}"))
            return
        time.sleep(0.8)
        try:
            self.state = _get("/state")["status"]["state"]
        except Exception:  # noqa: BLE001
            pass
        self.top.after(0, self.update_head)
        self.top.after(0, self.draw_badge)

    def save_room(self) -> None:
        try:
            _post("/room/save", {"room": self.room})
        except Exception as exc:  # noqa: BLE001
            self.top.after(0, lambda: self.status.configure(text=f"存位置失败：{exc}"))

    def close(self) -> None:
        global _window
        self.closed = True
        _window = None
        self.top.destroy()


def open_window(master: tk.Misc) -> str:
    """打开（或提到前面）房间窗口。"""
    global _window
    if _window is not None and not _window.closed:
        try:
            _window.top.deiconify()
            _window.top.lift()
            _window.load()
            return "她的家已经在看着了"
        except Exception:  # noqa: BLE001
            _window = None
    _window = RoomWindow(master)
    return "已打开她的家（窗口里）"
