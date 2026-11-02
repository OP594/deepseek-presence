#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""备份：数据库快照 + 一份人能读的记忆导出。

写到项目根的 backups\\，每个种类保留最近 KEEP 份。
云端镜像默认关闭（MIRROR_TO_CLOUD）；打开后才往 OneDrive\\备份 复制。
"""

import json
import os
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from settings import name

BASE = Path(__file__).resolve().parent.parent
ASTRBOT = BASE / "deps" / "astrbot-home"
DB = ASTRBOT / "data" / "data_v4.db"
CONFIG = ASTRBOT / "data" / "cmd_config.json"
PLUGIN_DB = ASTRBOT / "data" / "plugins" / "astrbot_plugin_fish_memory" / "memory.db"

LOCAL = BASE / "backups"
STAGE = LOCAL / ".staging"
KEEP = 72  # 每个种类保留最近多少份（每小时一份，约三天）
MIRROR_TO_CLOUD = False  # 不用 OneDrive 时保持关闭

# 备份文件名。fish-memory 是改名前的旧前缀，仍要参与清理，不然会一直留着。
PATTERNS = (
    "memory-*.db",
    "fish-memory-*.db",
    f"{name()}-memory-*.db",
    f"{name()}记忆-*.md",
    "config-*.json",
)


def snapshot_db(src_path: Path, dest: Path) -> None:
    src = sqlite3.connect(f"file:{src_path}?mode=ro", uri=True)
    dst = sqlite3.connect(str(dest))
    try:
        with dst:
            src.backup(dst)
    finally:
        dst.close()
        src.close()


def export_markdown(path: Path, stamp: str) -> None:
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    persona = conn.execute(
        "select system_prompt from personas where persona_id='default'"
    ).fetchone()
    rows = conn.execute(
        "select user_id, content, updated_at from conversations order by updated_at"
    ).fetchall()
    conn.close()

    lines = [f"# {name()}的记忆", "", f"导出于 {stamp}", "", "## 她是谁", ""]
    lines.append(persona["system_prompt"] if persona else "（没有找到人格）")
    lines += ["", "## 对话", ""]

    for row in rows:
        lines.append(f"### {row['user_id']} · {row['updated_at']}")
        lines.append("")
        try:
            msgs = json.loads(row["content"])
        except (TypeError, json.JSONDecodeError):
            msgs = []
        for m in msgs:
            text = m.get("content")
            if isinstance(text, list):
                text = " ".join(
                    str(x.get("text", "")) for x in text if isinstance(x, dict)
                )
            text = str(text or "").split("<system_reminder>")[0].strip()
            who = "你" if m.get("role") == "user" else name()
            lines.append(f"**{who}**：{text}")
            lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def prune(target: Path) -> None:
    for pattern in PATTERNS:
        files = sorted(
            target.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True
        )
        for f in files[KEEP:]:
            try:
                f.unlink()
            except OSError:
                pass


def mirror_to_cloud() -> tuple[bool, str]:
    onedrive = os.environ.get("OneDrive") or str(Path.home() / "OneDrive")
    dest = Path(onedrive) / "备份"
    try:
        dest.mkdir(parents=True, exist_ok=True)
        copied = 0
        skipped = 0
        for pattern in PATTERNS:
            for f in LOCAL.glob(pattern):
                target = dest / f.name
                try:
                    if target.exists() and target.stat().st_size == f.stat().st_size:
                        continue
                    if target.exists():
                        try:
                            target.chmod(0o666)
                        except Exception:  # noqa: BLE001
                            pass
                    shutil.copy2(f, target)
                    copied += 1
                except Exception:  # noqa: BLE001
                    skipped += 1
        prune(dest)
        return True, f"{dest}（新复制 {copied} 个，跳过 {skipped} 个）"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


def main() -> None:
    if not DB.exists():
        print("[备份] 还没找到记忆库，跳过。")
        return

    stamp = datetime.now().strftime("%Y%m%d-%H%M")

    shutil.rmtree(STAGE, ignore_errors=True)
    STAGE.mkdir(parents=True, exist_ok=True)
    snapshot_db(DB, STAGE / f"memory-{stamp}.db")
    if PLUGIN_DB.exists():
        snapshot_db(PLUGIN_DB, STAGE / f"{name()}-memory-{stamp}.db")
    export_markdown(STAGE / f"{name()}记忆-{stamp}.md", stamp)
    if CONFIG.exists():
        shutil.copyfile(CONFIG, STAGE / f"config-{stamp}.json")

    LOCAL.mkdir(parents=True, exist_ok=True)
    for f in STAGE.iterdir():
        shutil.copyfile(f, LOCAL / f.name)
    prune(LOCAL)
    shutil.rmtree(STAGE, ignore_errors=True)

    size = DB.stat().st_size / 1024
    print(f"[备份] {stamp} 本地完成（记忆库 {size:.0f} KB）")

    if not MIRROR_TO_CLOUD:
        return
    ok, msg = mirror_to_cloud()
    print(("[备份] 已镜像到 " + msg) if ok else ("[备份] 云端镜像跳过：" + msg))


if __name__ == "__main__":
    main()
