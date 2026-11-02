#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把她现在这间屋子画成一张图。

数据来自 virtual_activity 插件：
    room.json     家具和画布
    state_default.json  她在哪、在干嘛、精力

    py home_view.py          画一张 out/她的家.png
"""

import json
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

BASE = Path(__file__).resolve().parent.parent  # 项目根
PLUGIN = BASE / "deps" / "astrbot-home" / "data" / "plugin_data" / "astrbot_plugin_virtual_activity"
ROOM = PLUGIN / "room.json"
STATE = PLUGIN / "state_default.json"
OUT = BASE / "QQ机器人" / "out" / "她的家.png"

TEXT_FONT = r"C:\Windows\Fonts\msyh.ttc"
EMOJI_FONT = r"C:\Windows\Fonts\seguiemj.ttf"

INK = (44, 38, 34)
DIM = (108, 98, 92)
TOP = 96


def font(size: int, emoji: bool = False):
    path = EMOJI_FONT if emoji else TEXT_FONT
    try:
        return ImageFont.truetype(path, size)
    except Exception:  # noqa: BLE001
        try:
            return ImageFont.truetype(TEXT_FONT, size)
        except Exception:  # noqa: BLE001
            return ImageFont.load_default()


def load() -> tuple[dict, dict]:
    room = json.loads(ROOM.read_text(encoding="utf-8"))
    try:
        state = json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        state = {}
    return room, state


def where(state: dict) -> str:
    beh = state.get("behavior") or {}
    name = beh.get("furniture_name") or ""
    doing = beh.get("name") or ""
    if not name:
        return "不在屋里待着"
    return f"在{name}，{doing}" if doing else f"在{name}"


def render() -> Path:
    room, state = load()
    canvas = (room.get("room") or {}).get("canvas") or {}
    W = int(canvas.get("width") or 1000)
    H = int(canvas.get("height") or 700)
    bg = canvas.get("background") or "#f3ece2"

    img = Image.new("RGBA", (W, H + TOP), bg)
    d = ImageDraw.Draw(img)

    # 顶栏
    d.rectangle([0, 0, W, TOP], fill=(250, 247, 242, 255))
    d.line([(0, TOP), (W, TOP)], fill=(226, 218, 208, 255), width=2)
    d.text((26, 16), f"她现在：{where(state)}", font=font(26), fill=INK)

    bits = []
    energy = state.get("energy")
    social = state.get("social_hunger")
    if isinstance(energy, (int, float)):
        bits.append(f"精力 {int(energy)}")
    if isinstance(social, (int, float)):
        bits.append(f"社交需求 {int(social)}")
    nxt = state.get("next_tick_at") or ""
    if nxt:
        try:
            bits.append(f"下次活动 {datetime.fromisoformat(nxt):%H:%M}")
        except Exception:  # noqa: BLE001
            pass
    bits.append(f"{datetime.now():%H:%M} 画的")
    d.text((26, 52), "　".join(bits), font=font(16), fill=DIM)

    items = [i for i in (room.get("furniture") or []) if i.get("enabled") is not False]
    items.sort(key=lambda i: i.get("z") or 0)
    here = str((state.get("location") or {}).get("furniture_id") or "")

    # 先统一画影子，再合成一次，避免把已画的东西盖掉
    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    for it in items:
        x = float(it.get("x") or 0)
        y = float(it.get("y") or 0) + TOP
        w = float(it.get("w") or 200)
        h = float(it.get("h") or 140)
        sd.rounded_rectangle([x + 8, y + 12, x + w + 8, y + h + 12], radius=18,
                             fill=(0, 0, 0, 46))
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(9)))

    d = ImageDraw.Draw(img)
    for it in items:
        x = float(it.get("x") or 0)
        y = float(it.get("y") or 0) + TOP
        w = float(it.get("w") or 200)
        h = float(it.get("h") or 140)
        color = str(it.get("color") or "#d8cfc4")
        is_here = str(it.get("id")) == here
        d.rounded_rectangle([x, y, x + w, y + h], radius=18, fill=color,
                            outline=(52, 124, 104) if is_here else (206, 196, 186),
                            width=5 if is_here else 2)
        emoji = str(it.get("emoji") or "")
        if emoji:
            d.text((x + w / 2, y + h * 0.36), emoji,
                   font=font(int(min(h, w) * 0.40), emoji=True), fill=INK, anchor="mm")
        d.text((x + w / 2, y + h * 0.76), str(it.get("name") or ""), font=font(18),
               fill=(70, 62, 56), anchor="mm")
        if is_here:
            mx, my = x + w / 2, y - 26
            d.ellipse([mx - 19, my - 19, mx + 19, my + 19], fill=(52, 124, 104),
                      outline=(255, 255, 255), width=3)
            d.text((mx, my + 1), "鲸", font=font(20), fill=(255, 255, 255), anchor="mm")

    if not any(str(i.get("id")) == here for i in items):
        d.text((26, TOP + 20), "（她现在没在屋里）", font=font(18), fill=DIM)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(OUT, "PNG")
    return OUT


if __name__ == "__main__":
    print("画好了：", render())
