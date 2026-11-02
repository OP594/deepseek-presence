#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一键装环境：AstrBot、SnowLuma、四个第三方插件，再生成 config.json。

    py bootstrap.py            跟着提示走
    py bootstrap.py --yes      不问，直接装（表示你已读过 SnowLuma 的 EULA）

不打包这些依赖，是因为许可：
  - AstrBot 是 AGPL-3.0，从 PyPI 装最干净
  - SnowLuma 的 EULA 不允许公开再分发官方发行包，只能各自下载并同意条款
这里做的是「替你下载、替你放好」，不是「替你再发一份」。
"""

import argparse
import io
import json
import os
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
DEPS = ROOT / "deps"
VENV = DEPS / "venv"
ASTRBOT = DEPS / "astrbot-home"
SNOWLUMA = DEPS / "SnowLuma"
CONFIG = ROOT / "config.json"

ASTRBOT_VERSION = "4.29.4"
SNOWLUMA_VERSION = "v2.3.4"
MIRRORS = ("", "https://ghproxy.net/", "https://gh-proxy.com/")

PLUGINS = {
    "proactive_chat": "https://github.com/Pancakes-Labs/astrbot_plugin_proactive_chat/archive/refs/heads/main.zip",
    "shoubanhua": "https://github.com/shskjw/astrbot_plugin_shoubanhua/archive/refs/heads/master.zip",
    "virtual_activity": "https://github.com/Kasenoon/astrbot_plugin_virtual_activity/archive/refs/heads/main.zip",
    "sugar_debounce": "https://github.com/SucroseZT/astrbot_plugin_sugar_debounce/archive/refs/heads/main.zip",
}


def say(msg: str) -> None:
    print(f"[bootstrap] {msg}", flush=True)


def download(url: str) -> bytes:
    """带镜像回退的下载。"""
    last = None
    for prefix in MIRRORS:
        target = prefix + url if prefix else url
        try:
            req = urllib.request.Request(target, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            last = e
            if prefix:
                say(f"镜像失败 {prefix}，换下一个")
    raise RuntimeError(f"下载失败：{url}（{last}）")


def ensure_venv() -> Path:
    py = VENV / "Scripts" / "python.exe"
    if py.exists():
        say(f"虚拟环境已存在：{VENV}")
        return py
    say("建虚拟环境 deps\\venv …")
    subprocess.run([sys.executable, "-m", "venv", str(VENV)], check=True)
    return py


def install_astrbot(py: Path) -> None:
    say(f"安装 AstrBot {ASTRBOT_VERSION}（从 PyPI）…")
    subprocess.run(
        [str(py), "-m", "pip", "install", "--upgrade", "pip", "-q"], check=False
    )
    subprocess.run(
        [str(py), "-m", "pip", "install", f"astrbot=={ASTRBOT_VERSION}"], check=True
    )
    req = ROOT / "requirements.txt"
    if req.exists():
        subprocess.run([str(py), "-m", "pip", "install", "-r", str(req)], check=True)


def install_snowluma(accept: bool) -> None:
    if SNOWLUMA.exists() and any(SNOWLUMA.iterdir()):
        say("SnowLuma 已存在，跳过")
        return
    if not accept:
        print(
            "\nSnowLuma 有自己的 EULA（源码可见、非商业许可），"
            "官方发行包不允许再分发。\n"
            "继续即表示你自己下载并同意它的条款：https://github.com/SnowLuma/SnowLuma/blob/main/EULA.md\n"
        )
        if input("输入 yes 继续：").strip().lower() not in ("yes", "y"):
            say("跳过了 SnowLuma。没有它就跑不起来，稍后自己装。")
            return

    url = (
        f"https://github.com/SnowLuma/SnowLuma/releases/download/"
        f"{SNOWLUMA_VERSION}/SnowLuma-{SNOWLUMA_VERSION}-win-x64.zip"
    )
    say("下载 SnowLuma …")
    data = download(url)
    SNOWLUMA.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        z.extractall(SNOWLUMA)
    say(f"SnowLuma 解压到 {SNOWLUMA}")


def install_plugins(py: Path) -> None:
    plugins_dir = ASTRBOT / "data" / "plugins"
    plugins_dir.mkdir(parents=True, exist_ok=True)

    bundled = ROOT / "plugins"
    if bundled.exists():
        say("放入仓库自带的插件 …")
        for p in bundled.iterdir():
            if p.is_dir():
                dst = plugins_dir / p.name
                if dst.exists():
                    continue
                import shutil

                shutil.copytree(p, dst)

    # 仓库里已经 vendored 的那几个优先，省得再下
    vendored = ROOT / "vendor" / "plugins"
    if vendored.exists():
        say("放入 vendor/plugins 里的四个第三方插件 …")
        for p in vendored.iterdir():
            if p.is_dir():
                dst = plugins_dir / p.name
                if not dst.exists():
                    import shutil

                    shutil.copytree(p, dst)

    for name, url in PLUGINS.items():
        dst = plugins_dir / f"astrbot_plugin_{name}"
        if dst.exists():
            say(f"{name} 已存在，跳过")
            continue
        say(f"下载插件 {name} …")
        try:
            data = download(url)
        except Exception as e:  # noqa: BLE001
            say(f"  {name} 下载失败：{e}")
            continue
        tmp = DEPS / f".{name}.zip"
        tmp.write_bytes(data)
        with zipfile.ZipFile(tmp) as z:
            root_name = z.namelist()[0].split("/")[0]
            z.extractall(DEPS / ".plugin_tmp")
        src = DEPS / ".plugin_tmp" / root_name
        if src.exists():
            import shutil

            shutil.copytree(src, dst)
            shutil.rmtree(src, ignore_errors=True)
        tmp.unlink(missing_ok=True)
    say("插件放好了")


def write_config() -> None:
    if CONFIG.exists():
        say("config.json 已存在，不改")
        return
    print("\n填几个东西（回车用默认值）：")
    name = input("  她叫什么 [companion]：").strip() or "companion"
    owner = input("  你的 QQ 号：").strip()
    self_qq = input("  机器人的 QQ 号：").strip()
    umo = input("  私聊会话 ID（形如 snowluma:FriendMessage:123456，可留空）：").strip()
    cfg = {
        "name": name,
        "owner_qq": int(owner) if owner.isdigit() else 0,
        "self_qq": int(self_qq) if self_qq.isdigit() else 0,
        "umo": umo,
        "persona_id": "default",
        "onebot_port": 3000,
        "astrbot_port": 6185,
        "proxy_port": 6186,
    }
    CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    say(f"config.json 写好了：{CONFIG}")


def init_persona(py: Path) -> None:
    script = SCRIPTS / "init_persona.py"
    if script.exists():
        say("把人格写进 AstrBot …")
        subprocess.run([str(py), str(script)], cwd=str(SCRIPTS), check=False)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--yes", action="store_true", help="不问，直接装（表示已同意 SnowLuma 的 EULA）")
    args = ap.parse_args()

    DEPS.mkdir(parents=True, exist_ok=True)
    py = ensure_venv()
    install_astrbot(py)
    install_snowluma(args.yes)
    install_plugins(py)
    write_config()
    init_persona(py)

    print(
        "\n装完了。下一步：\n"
        "  1. 打开 http://127.0.0.1:6185 配 provider 和 key\n"
        "  2. 双击 scripts\\start-all.bat 启动\n"
        "  3. 双击 scripts\\start-gui.bat 看状态\n"
    )


if __name__ == "__main__":
    main()
