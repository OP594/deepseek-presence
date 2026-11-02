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
import time
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


def init_astrbot_home(py: Path) -> None:
    """astrbot init -y：建好 data/ 和配置骨架。"""
    exe = py.parent / "astrbot.exe"
    ASTRBOT.mkdir(parents=True, exist_ok=True)
    if not (ASTRBOT / ".astrbot").exists():
        say("初始化 AstrBot 目录 …")
        subprocess.run([str(exe), "init", "-y"], cwd=str(ASTRBOT), check=False)
    else:
        say("AstrBot 目录已初始化过")

    db = ASTRBOT / "data" / "data_v4.db"
    if db.exists():
        say("数据库已存在，跳过首次启动")
        return

    say("第一次启动 AstrBot，让它把库建出来（大约 10 秒）…")
    boot = SCRIPTS / "_boot_once.py"
    proc = subprocess.Popen(
        [str(py), "-X", "utf8", str(boot), "6399"],
        cwd=str(ASTRBOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(60):
        time.sleep(2)
        if db.exists():
            say("库建好了")
            break
        if proc.poll() is not None:
            break
    subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2)


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


def write_plugin_configs() -> None:
    """按 config.json 把几个插件的关键项填好，省得用户一个个点。"""
    if not CONFIG.exists():
        return
    cfg = json.loads(CONFIG.read_text(encoding="utf-8-sig"))
    name = cfg.get("name") or "companion"
    owner = int(cfg.get("owner_qq") or 0)
    umo = cfg.get("umo") or ""
    conf_dir = ASTRBOT / "data" / "config"
    conf_dir.mkdir(parents=True, exist_ok=True)

    if owner and not (conf_dir / "astrbot_plugin_proactive_chat_config.json").exists():
        (conf_dir / "astrbot_plugin_proactive_chat_config.json").write_text(
            json.dumps(
                {
                    "friend_settings": {
                        "enable": True,
                        "session_list": [umo] if umo else [],
                        "schedule_settings": {
                            "min_interval_minutes": 60,
                            "max_interval_minutes": 240,
                            "quiet_hours": "2-8",
                            "max_unanswered_times": 2,
                        },
                        "tts_settings": {"enable_tts": False},
                    },
                    "group_settings": {"enable": False},
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    if owner and not (conf_dir / "astrbot_plugin_virtual_activity_config.json").exists():
        (conf_dir / "astrbot_plugin_virtual_activity_config.json").write_text(
            json.dumps(
                {
                    "enable_auto_tick": True,
                    "tick_min_minutes": 25,
                    "tick_max_minutes": 50,
                    "active_hours": "09:00-23:30",
                    "quiet_hours": "01:00-08:30",
                    "admin_qq": str(owner),
                    "admin_umo": umo,
                    "inject_prompt": True,
                    "weather_enabled": False,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    say("几个插件的配置也填好了")


IMAGE_PROVIDERS = {
    "1": {
        "label": "智谱（推荐，cogview-4）",
        "interface_mode": "custom_endpoint",
        "base_url": "https://open.bigmodel.cn/api/paas/v4/images/generations",
        "model": "cogview-4-250304",
        "key_url": "https://open.bigmodel.cn/usercenter/apikeys",
    },
    "2": {
        "label": "硅基流动（FLUX，注册送额度）",
        "interface_mode": "openai_image",
        "base_url": "https://api.siliconflow.cn/v1",
        "model": "Kwai-Kolors/Kolors",
        "key_url": "https://cloud.siliconflow.cn/account/ak",
    },
    "3": {
        "label": "火山方舟（Seedream）",
        "interface_mode": "custom_endpoint",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3/images/generations",
        "model": "doubao-seedream-4-0-250828",
        "key_url": "https://console.volcengine.com/ark",
    },
}


def write_image_config(key: str = "", provider: str = "", assume_yes: bool = False) -> None:
    """问一句要不要配画图，一个 key 就够。"""
    conf = ASTRBOT / "data" / "config" / "astrbot_plugin_shoubanhua_config.json"
    if conf.exists():
        say("画图配置已存在，不改")
        return

    if not key and assume_yes:
        say("跳过了画图（--yes 模式没给 key）")
        return
    print(
        "\n要不要现在就配画图？（只填一个 key 就能让她画）\n"
        "  1 智谱 cogview-4　2 硅基流动 FLUX　3 火山方舟 Seedream　0 先跳过"
    )
    pick = (provider or input("  选 [1]：").strip()) or "1"
    if pick in ("0", "n", "no"):
        say("跳过了画图，以后可以在 AstrBot 插件设置里填")
        return
    prov = IMAGE_PROVIDERS.get(pick)
    if not prov:
        say("没这个选项，跳过")
        return

    if not key:
        print(f"  用 {prov['label']}，key 在这里拿：{prov['key_url']}")
    if not key:
        key = input("  贴 key（回车跳过）：").strip()
    if not key:
        say("没填 key，跳过画图")
        return

    cfg = {
        "interface_mode": prov["interface_mode"],
        "base_url": prov["base_url"],
        "api_keys": key,
        "model": prov["model"],
        "text_to_image_model": prov["model"],
        "enable_llm_tool": True,
        "enable_llm_auto_detect": True,
        "llm_cooldown_seconds": 10,
        "enable_persona_mode": False,
        "enable_preset_ref_images": False,
        "image_resolution": "1K",
        "image_aspect_ratio": "4:3",
    }
    conf.parent.mkdir(parents=True, exist_ok=True)
    conf.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    say(f"画图配好了：{prov['model']}")


def init_persona(py: Path) -> None:
    script = SCRIPTS / "init_persona.py"
    if script.exists():
        say("把人格写进 AstrBot …")
        subprocess.run([str(py), str(script)], cwd=str(SCRIPTS), check=False)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--yes", action="store_true", help="不问，直接装（表示已同意 SnowLuma 的 EULA）")
    ap.add_argument("--reuse-python", action="store_true", help="自测用：用当前解释器，不建 venv")
    ap.add_argument("--image-key", default="", help="画图 key（给了就不问）")
    ap.add_argument("--image-provider", default="", help="1 智谱 / 2 硅基流动 / 3 火山方舟")
    args = ap.parse_args()

    DEPS.mkdir(parents=True, exist_ok=True)
    if args.reuse_python:
        py = Path(sys.executable)
        say(f"用当前解释器：{py}")
    else:
        py = ensure_venv()
        install_astrbot(py)
    install_snowluma(args.yes)
    init_astrbot_home(py)
    install_plugins(py)
    write_config()
    write_plugin_configs()
    write_image_config(args.image_key, args.image_provider, args.yes)
    init_persona(py)

    print(
        "\n装完了。还差三步，都是没法替你做的：\n"
        "  1. 双击 deps\\SnowLuma\\launcher.bat，用机器人 QQ 扫码登录（它要同意自己的 EULA）\n"
        "  2. 双击 scripts\\start-all.bat，等它起来\n"
        "  3. 打开 http://127.0.0.1:6185，设网页密码、填 DeepSeek key\n"
        "\n等她收到第一条消息后，跑一遍 scripts\\find_umo.py，把会话 ID 填进 config.json 的 umo，\n"
        "主动消息和屋子活动才会生效。\n"
    )


if __name__ == "__main__":
    main()
