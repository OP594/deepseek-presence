from __future__ import annotations

"""
deepseek-presence · 长期记忆插件

它做三件事：
  1. 每次她要回话之前，把「跟这句话有关的记忆」塞进系统提示
  2. 每聊 8 轮，让模型自己复盘一次：提炼出长期有价值的事实，再写一句反思
  3. 全部存在自己目录下的 memory.db 里，可以看、可以删

设计原则：只记「长期有用」的东西。不是流水账。
"""

import asyncio
import json
import re
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent
DB_PATH = DATA_DIR / "memory.db"

CONSOLIDATE_EVERY = 12
FACTS_LIMIT = 25

CONSOLIDATE_INSTRUCTION = """你在帮一个 AI 整理记忆。下面是你和对方最近的一段对话。

只输出一个 JSON 对象，不要任何其他文字：
{"facts": [{"topic": "身份|喜好|重要的人|经历|计划|情绪|边界|其他", "content": "..."}], "reflection": "..."}

规则：
- facts 只收长期有价值的信息：名字、习惯、在意的人、反复出现的情绪、明确说过的喜好或厌恶、重要日期、正在做的事。
- 不记录一次性的琐事，不复述对话，不编造。
- 每条 content 不超过 40 字，用第三人称写 ta。
- facts 最多 4 条；没有值得记的就给 []。
- reflection 用第一人称，一到两句，写这段对话让你对 ta 的理解或心情。
"""


# --------------------------------------------------------------------------- #
# 小工具
# --------------------------------------------------------------------------- #

def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def tokenize(text: str) -> set[str]:
    """中英混排的极简分词：英文按词，中文按二元组。"""
    text = (text or "").lower()
    words = re.findall(r"[a-z0-9_]+", text)
    grams: list[str] = []
    for run in re.findall(r"[\u4e00-\u9fff]+", text):
        if len(run) == 1:
            grams.append(run)
        else:
            grams.extend(run[i:i + 2] for i in range(len(run) - 1))
    return set(words) | set(grams)


def parse_json_object(raw: str):
    if not raw:
        return None
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        obj = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


# --------------------------------------------------------------------------- #
# 记忆库
# --------------------------------------------------------------------------- #

class Memory:
    def __init__(self, path: Path = DB_PATH):
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        with self.lock:
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    umo TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS facts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    umo TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    content TEXT NOT NULL,
                    hits INTEGER NOT NULL DEFAULT 1,
                    active INTEGER NOT NULL DEFAULT 1,
                    UNIQUE(umo, topic, content)
                );
                CREATE TABLE IF NOT EXISTS reflections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    umo TEXT NOT NULL,
                    content TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )
            self.conn.commit()

    # -- 消息 ------------------------------------------------------------- #
    def add_message(self, umo: str, role: str, content: str) -> int:
        with self.lock:
            cur = self.conn.execute(
                "INSERT INTO messages(ts, umo, role, content) VALUES (?,?,?,?)",
                (now_iso(), umo, role, content),
            )
            self.conn.commit()
            return int(cur.lastrowid)

    def pending_messages(self, umo: str, limit: int = 80) -> list[dict]:
        """上次整理之后新攒下的对话。"""
        last = int(self.meta_get(f"last_consolidated_id:{umo}", 0) or 0)
        with self.lock:
            rows = self.conn.execute(
                "SELECT id, role, content FROM messages "
                "WHERE umo=? AND id>? ORDER BY id ASC LIMIT ?",
                (umo, last, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    # -- 事实 ------------------------------------------------------------- #
    def add_fact(self, umo: str, topic: str, content: str) -> bool:
        topic = re.sub(r"\s+", "", topic or "")[:12] or "其他"
        content = (content or "").strip()[:120]
        if not content:
            return False
        with self.lock:
            cur = self.conn.execute(
                "INSERT OR IGNORE INTO facts(ts, umo, topic, content) VALUES (?,?,?,?)",
                (now_iso(), umo, topic, content),
            )
            if cur.rowcount == 0:
                self.conn.execute(
                    "UPDATE facts SET hits=hits+1 WHERE umo=? AND topic=? AND content=?",
                    (umo, topic, content),
                )
            self.conn.commit()
            return cur.rowcount > 0

    def list_facts(self, umo: str, limit: int = 500) -> list[dict]:
        with self.lock:
            rows = self.conn.execute(
                "SELECT id, ts, topic, content, hits FROM facts "
                "WHERE umo=? AND active=1 ORDER BY topic ASC, id ASC LIMIT ?",
                (umo, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def forget(self, fact_id: int) -> bool:
        with self.lock:
            cur = self.conn.execute("DELETE FROM facts WHERE id=?", (fact_id,))
            self.conn.commit()
            return cur.rowcount > 0

    def retrieve_facts(self, umo: str, query: str, limit: int) -> list[dict]:
        with self.lock:
            rows = self.conn.execute(
                "SELECT id, topic, content, hits FROM facts "
                "WHERE umo=? AND active=1 ORDER BY id DESC LIMIT 500",
                (umo,),
            ).fetchall()
        facts = [dict(r) for r in rows]
        if not facts:
            return []
        q = tokenize(query)
        top_id = max(f["id"] for f in facts) or 1

        def score(f: dict) -> float:
            overlap = len(q & tokenize(f["content"] + " " + f["topic"]))
            return overlap * 3.0 + (f["id"] / top_id) * 1.5 + min(f["hits"], 5) * 0.2

        picked = sorted(facts, key=score, reverse=True)[: max(1, limit)]
        picked.sort(key=lambda f: f["id"])
        return picked

    # -- 反思 ------------------------------------------------------------- #
    def add_reflection(self, umo: str, content: str) -> None:
        content = (content or "").strip()
        if not content:
            return
        with self.lock:
            self.conn.execute(
                "INSERT INTO reflections(ts, umo, content) VALUES (?,?,?)",
                (now_iso(), umo, content),
            )
            self.conn.commit()

    def last_reflection(self, umo: str) -> str:
        with self.lock:
            row = self.conn.execute(
                "SELECT content FROM reflections WHERE umo=? ORDER BY id DESC LIMIT 1",
                (umo,),
            ).fetchone()
        return row["content"] if row else ""

    # -- 元信息 ----------------------------------------------------------- #
    def meta_get(self, key: str, default=None):
        with self.lock:
            row = self.conn.execute(
                "SELECT value FROM meta WHERE key=?", (key,)
            ).fetchone()
        if not row:
            return default
        try:
            return json.loads(row["value"])
        except json.JSONDecodeError:
            return default

    def meta_set(self, key: str, value) -> None:
        with self.lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES (?,?)",
                (key, json.dumps(value, ensure_ascii=False)),
            )
            self.conn.commit()

    def bump_turn(self, umo: str) -> int:
        n = int(self.meta_get(f"turns:{umo}", 0) or 0) + 1
        self.meta_set(f"turns:{umo}", n)
        return n

    def reset_turn(self, umo: str) -> None:
        self.meta_set(f"turns:{umo}", 0)

    def mark_consolidated(self, umo: str, msg_id: int) -> None:
        self.meta_set(f"last_consolidated_id:{umo}", msg_id)

    # -- 组装 ------------------------------------------------------------- #
    def render_block(self, facts: list[dict], reflection: str) -> str:
        parts: list[str] = []
        if facts:
            lines = "\n".join(f"- {f['content']}" for f in facts)
            parts.append(f"【你记得关于 ta 的事】\n{lines}")
        if reflection:
            parts.append(f"【你独处时想到的】\n{reflection}")
        if not parts:
            return ""
        parts.append(
            "以上是记忆，不是剧本：自然地用，别生硬复述，别说「根据我的记忆」。"
            "拿不准的就说不确定，别编。"
        )
        return "\n\n".join(parts)
