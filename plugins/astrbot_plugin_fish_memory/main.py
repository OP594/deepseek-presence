from __future__ import annotations

"""deepseek-presence · 长期记忆插件

纯后台运行，不注册任何聊天命令：
- 每次回话前，把相关记忆塞进系统提示
- 每聊 8 轮，复盘一次：提炼长期事实 + 写一句反思
"""

import asyncio
import glob
import json
import re
import sqlite3
import time
import urllib.request
from pathlib import Path

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.core.message.components import Image
from astrbot.api.provider import LLMResponse, ProviderRequest
from astrbot.api.star import Context, Star, register

from .memory import (
    CONSOLIDATE_EVERY,
    FACTS_LIMIT,
    CONSOLIDATE_INSTRUCTION,
    Memory,
    parse_json_object,
)

ASTRBOT_DIR = Path(__file__).resolve().parents[3]  # .../deps/astrbot-home
_ALLOW_JIEZHE = ("接着说", "接着聊", "接着讲", "接着做", "接着走", "接着干",
                 "接着问", "接着看", "接着写", "接着听", "接着待", "接着往下")


RULES_FILE = ASTRBOT_DIR.parent.parent / "data" / "style_rules.json"
_rules_cache: dict = {"mtime": -1.0, "data": None}


def style_rules() -> dict:
    """忌语/方言的唯一出处。改 JSON 不用重启，下一轮自动生效。"""
    try:
        mtime = RULES_FILE.stat().st_mtime
        if _rules_cache["data"] is not None and mtime == _rules_cache["mtime"]:
            return _rules_cache["data"]
        data = json.loads(RULES_FILE.read_text(encoding="utf-8"))
        _rules_cache["mtime"] = mtime
        _rules_cache["data"] = data
        return data
    except Exception:  # noqa: BLE001
        return {"banned": BANNED, "dialect": DIALECT, "allow": {}}


def _style_hits(text: str) -> list[str]:
    """返回这句里犯了哪些忌。"""
    rules = style_rules()
    hits = []
    for d in rules.get("dialect") or DIALECT:
        if d and d in text:
            hits.append(d)
    for b in rules.get("banned") or BANNED:
        if b not in text:
            continue
        if b == "我接着" and not re.search(r"我接着(?![说讲问聊看做走干写听待下])", text):
            continue
        hits.append(b)
    allows = (rules.get("allow") or {}).get("接着") or _ALLOW_JIEZHE
    if "接着" in text and not any(a in text for a in allows):
        if not re.search(r"接着(?=[说讲问聊看做走干写听待下])", text):
            hits.append("接着")
    return hits


def _salvage_calls(text: str) -> tuple[str, list[dict]]:
    """把泄露在正文里的 decorate_home 调用挖出来。"""
    calls: list[dict] = []
    if not text:
        return text, calls
    for m in re.finditer(r"decorate_home\s*\(\s*(\{.*?\})\s*\)", text, flags=re.S):
        try:
            calls.append(json.loads(m.group(1)))
        except Exception:  # noqa: BLE001
            pass
    for m in re.finditer(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.S):
        try:
            d = json.loads(m.group(1))
            if d.get("name") == "decorate_home" and isinstance(d.get("arguments"), dict):
                calls.append(d["arguments"])
        except Exception:  # noqa: BLE001
            pass
    return _strip_tool_leak(text), calls


def _strip_tool_leak(text: str) -> str:
    """模型偶尔把工具调用当成正文吐出来，这里把它剪掉。"""
    if not text:
        return text
    marks = ("<tool_code>", '"arguments"', "```json", '"action"', "decorate_home(")
    if not any(m in text for m in marks):
        return text
    text = re.sub(r"<tool_code>.*?</tool_code>", "", text, flags=re.S)
    text = re.sub(r"\[调用 [^\]]*\]", "", text)
    text = text.replace("\u201c", "“").replace("\u201d", "”")  # 直引号换成中文引号
    text = re.sub(r"\[工具[^\]]*\]", "", text)
    text = re.sub(r"```[a-zA-Z]*\s*\{.*?\}\s*```", "", text, flags=re.S)
    text = re.sub(r"\b[a-z_]+\s*\(\s*\{.*?\}\s*\)", "", text, flags=re.S)
    text = re.sub(r'\{\s*"name"\s*:.*', "", text, flags=re.S)
    text = re.sub(r'\{\s*"action"\s*:.*', "", text, flags=re.S)
    return text.strip()


HOME_WORDS = ("添", "放", "挪", "搬", "摆", "铺", "挂", "换", "收拾", "整理", "擦", "浇",
              "屋里", "小屋", "桌子上", "窗台", "墙角", "地上", "椅子")

BANNED = [
    "收下", "我收下",
    "我接着", "接不住", "接住", "兜住", "我听着", "我懂", "我知道你",
    "这很正常", "不丢人", "没什么大不了", "你已经很棒了", "我一直在",
    "我就在这", "我在这头", "耗着", "我认了", "认栽", "轻飘飘",
    "说起来你可能不信", "我说不准", "这词太大", "看不上你",
    "不早了", "该走了", "该睡了", "早点休息", "快去睡",
    "陪你熬", "陪你到", "我陪着你", "我在这儿", "我听着呢",
    "我理解", "能理解", "别多想", "放轻松", "你已经很",
]

DIALECT = [
    "啥", "咋", "呗", "咱", "唠", "贼", "嘞", "甭", "嘛呢",
    "干啥", "咋整", "整啥", "搁这", "搁那", "得劲", "蒙圈", "老铁", "嘎哈",
]


QQ_DIR = ASTRBOT_DIR.parent.parent  # 项目根
STATE = QQ_DIR / "data" / "qzone_state.json"


@register(
    "astrbot_plugin_fish_memory",
    "deepseek-presence",
    "长期记忆：提炼事实、写反思、回话前自动带上",
    "1.0.0",
)
class FishMemory(Star):
    def __init__(self, context: Context, config=None) -> None:
        self.context = context
        self.mem = Memory()
        self._busy: set[str] = set()
        self._state_ts = 0.0
        self._state_text = ""
        self._persona_ts = 0.0
        self._persona_text = ""
        self._home_ts = 0.0
        self._home_text = ""
        self._cfg_cache = None
        self._last_auto = 0.0
        self._img_seq = 0
        self._img_latest = 0
        self._img_buf = {}
        self._img_drop = set()
        self._img_parts = {}
        logger.info("记忆已加载")

    # -- OneBot 小工具 ------------------------------------------------------ #
    def _token(self) -> str:
        pattern = str(
            ASTRBOT_DIR.parent / "SnowLuma" / "config" / "onebot_*.json"
        )
        for path in glob.glob(pattern):
            try:
                data = json.load(open(path, encoding="utf-8-sig"))
                servers = data.get("networks", {}).get("httpServers") or []
                if servers:
                    return servers[0].get("accessToken") or ""
            except Exception:  # noqa: BLE001
                continue
        return ""

    def _onebot(self, action: str, payload: dict) -> dict:
        req = urllib.request.Request(
            f"http://127.0.0.1:3000/{action}",
            data=json.dumps(payload).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._token()}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())

    def _self_state(self, self_id: str) -> str:
        """她自己的昵称和签名，缓存 5 分钟。"""
        if self._state_text and time.time() - self._state_ts < 300:
            return self._state_text
        try:
            res = self._onebot("get_stranger_info", {"user_id": int(self_id or 0)})
            data = res.get("data") or {}
            nick = data.get("nickname") or ""
            sign = (data.get("long_nick") or "").strip()
            self._state_text = (
                "【你现在的状态】\n"
                f"你的昵称：{nick}\n"
                f"你的个性签名：{sign or '（还没写）'}"
            )
        except Exception:  # noqa: BLE001
            self._state_text = ""
        self._state_ts = time.time()
        return self._state_text

    def _mark_posted(self) -> None:
        try:
            state = (
                json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
            )
            state["last_post"] = time.time()
            STATE.write_text(
                json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception:  # noqa: BLE001
            pass

    # -- 她的空间，她自己做主 ---------------------------------------------- #
    @filter.llm_tool(name="post_qzone")
    async def post_qzone(self, event: AstrMessageEvent, content: str):
        """发一条 QQ 空间说说。这是你自己的空间，想发就发，不用问谁。

        Args:
            content(string): 说说正文，像随手写的一句，别太长
        """
        try:
            res = self._onebot("send_qzone_msg", {"content": content, "ugc_right": 4})
        except Exception as exc:  # noqa: BLE001
            logger.exception("发说说失败")
            return f"没发出去：{type(exc).__name__}"
        if res.get("status") == "ok":
            self._mark_posted()
            logger.info("她发了一条说说：%s", content)
            return "已发出去。"
        return f"没发成：{res.get('wording') or res}"

    @filter.llm_tool(name="web_search")
    async def web_search(self, event: AstrMessageEvent, query: str):
        """搜索互联网。需要查东西时立刻调用它，不要只回一句“我查一下”就结束这一轮；调用完再说话。

        Args:
            query(string): 搜索关键词，像人搜索时那样写
        """
        logger.info("开始搜索：%s", query)
        try:
            result = await self._search_text(query)
            logger.info("搜索返回：%s", result[:80])
            return result
        except Exception as exc:  # noqa: BLE001
            logger.exception("搜索失败")
            return f"搜不了：{type(exc).__name__}"

    async def _search_text(self, query: str) -> str:
        def _run() -> str:
            cfg = json.loads(
                (ASTRBOT_DIR / "data" / "cmd_config.json").read_text(encoding="utf-8-sig")
            )
            src = cfg["provider_sources"][0]
            key = src["key"][0] if isinstance(src["key"], list) else src["key"]
            body = {"query": query, "count": 6, "need_content": False}
            req = urllib.request.Request(
                "https://api.deepseek.com/v1/tools/search",
                data=json.dumps(body).encode(),
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read())
            items = data.get("results") or []
            if not items:
                return "没搜到结果。"
            lines = []
            for it in items[:6]:
                title = (it.get("title") or "").strip()
                url = (it.get("url") or "").strip()
                summary = (it.get("summary") or "").strip().replace("\n", " ")[:160]
                lines.append(f"- {title}\n  {summary}\n  {url}")
            return "搜索结果：\n" + "\n".join(lines)

        return await asyncio.to_thread(_run)

    _PROMISE = re.compile(
        r"(去搜|搜一下|搜一搜|搜搜|上网搜|帮你搜|我查(?![到过了])|查一下|查查|去查|找一下|找找|你等等|等我一下|稍等)"
    )

    async def _guess_query(self, event, text: str) -> str:
        prompt = (
            "她在说要去搜东西。根据下面这两句，判断她要搜什么，只输出搜索词，"
            "不超过 15 个字，不要标点，不要解释。\n"
            f"她刚才说：{event.message_str or ''}\n"
            f"她回了一句：{text}"
        )
        try:
            return (await self._quick_text("只输出搜索词。", prompt)).strip()[:40]
        except Exception:  # noqa: BLE001
            return ""

    async def _reply_with_results(self, event, query: str, result: str) -> str:
        provider = self.context.get_using_provider(event.unified_msg_origin)
        if provider is None:
            return ""
        system = (
            self._persona()
            + "\n\n你刚替她搜到了下面这些，用一两句话把有用的说给她，"
            "短，别列条目，别提“搜索”两个字，也别道歉。\n\n"
            + result[:1500]
        )
        try:
            resp = await provider.text_chat(
                prompt=(event.message_str or f"关于{query}"), system_prompt=system
            )
            return (resp.completion_text or "").strip()
        except Exception:  # noqa: BLE001
            logger.exception("用搜索结果回话失败")
            return ""

    async def _auto_search(self, event, text: str) -> str:
        """她说了要去搜却没搜，这里替她搜完再回。"""
        if not self._PROMISE.search(text):
            return ""
        now = time.time()
        if now - self._last_auto < 60:
            return ""
        self._last_auto = now
        query = await self._guess_query(event, text)
        if not query:
            return ""
        logger.info("她说了要搜但没搜，替她搜：%s", query)
        try:
            result = await self._search_text(query)
        except Exception:  # noqa: BLE001
            logger.exception("自动搜索失败")
            return ""
        if "没搜到" in result or result.startswith("搜不了"):
            return ""
        logger.info("自动搜索返回：%s", result[:80])
        return await self._reply_with_results(event, query, result)

    @filter.llm_tool(name="set_signature")
    async def set_signature(self, event: AstrMessageEvent, text: str):
        """改自己的 QQ 个性签名。想改就改，不用问谁。

        Args:
            text(string): 新签名，25 字以内
        """
        try:
            res = self._onebot("set_self_longnick", {"longNick": text})
        except Exception as exc:  # noqa: BLE001
            logger.exception("改签名失败")
            return f"没改成：{type(exc).__name__}"
        if res.get("status") == "ok":
            logger.info("她改了签名：%s", text)
            return "改好了。"
        return f"没改成：{res.get('wording') or res}"

    @filter.llm_tool(name="view_qzone_comments")
    async def view_qzone_comments(self, event: AstrMessageEvent, count: int = 5) -> str:
        """看自己发的说说下面别人留的评论。

        Args:
            count(number): 看最近几条，默认 5
        """
        import json as _json
        from pathlib import Path as _Path
        f = _Path(str(ASTRBOT_DIR.parent.parent / "data" / "qzone_comments.json"))
        try:
            data = _json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return "还没有人评论过你的说说。"
        items = sorted(data.values(), key=lambda c: c.get("time") or 0)[-max(1, min(int(count or 5), 10)):]
        if not items:
            return "还没有人评论过你的说说。"
        import datetime as _dt
        return "\n".join(
            f"{_dt.datetime.fromtimestamp(c.get('time') or 0).strftime('%m-%d %H:%M')} {c.get('name')}：{c.get('content')}（出自「{c.get('post')}」）"
            for c in items
        )

    # 已停用（小屋换成了 virtual_activity 插件）
    async def decorate_home(self, event: AstrMessageEvent, item: str, note: str = "", spot: str = ""):
        """往你自己的小家里添一样东西，或者把已有的换个说法。想添就添，不用问谁。

        Args:
            item(string): 东西的名字，比如“小软垫”“落地灯”
            note(string): 一句说明，是什么样
            spot(string): 放在哪，只能填这几个之一：窗台 / 窗边 / 中间 / 墙角 / 地上 / 门口
        """
        try:
            path = QQ_DIR / "data" / "home.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            name = item.strip()[:20]
            text = note.strip()[:80] or "放在屋里"
            existing = next((i for i in data["items"] if i["name"] == name), None)
            if existing:
                existing["note"] = text
                if spot.strip():
                    existing["spot"] = spot.strip()
            else:
                data["items"].append({"name": name, "note": text, "spot": spot.strip() or "地上"})
                if len(data["items"]) > 12:
                    data["items"] = data["items"][-12:]
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            self._home_ts = 0.0
            lines = [f"# {data.get('name', '家')}", "", "## 屋里的东西"]
            for it in data.get("items", []):
                lines.append(f"- **{it['name']}**：{it.get('note', '')}")
            lines.append(""); lines.append("## 日记")
            diary = data.get("diary", [])
            if not diary:
                lines.append("（还没写过）")
            for d in reversed(diary[-20:]):
                lines.append(f"**{d['ts'][:16].replace('T', ' ')}**")
                lines.append(d["text"]); lines.append("")
            (QQ_DIR / "out" / "家.md").write_text("\n".join(lines), encoding="utf-8")
            try:
                import sys as _sys

                if str(QQ_DIR) not in _sys.path:
                    _sys.path.insert(0, str(QQ_DIR))
                import home_draw

                home_draw.render()
            except Exception:  # noqa: BLE001
                pass
            logger.info("家里添了/换了：%s（%s）", name, text)
            return f"放好了：{name}，{text}"
        except Exception as exc:  # noqa: BLE001
            logger.exception("布置家失败")
            return f"没弄成：{type(exc).__name__}"

    # -- 回话前：注入记忆 -------------------------------------------------- #
    IMG_HOLD = 12.0

    def _has_image(self, event, req=None) -> bool:
        try:
            for comp in event.message_obj.message:
                if comp.__class__.__name__ in ("Image", "ImageComponent"):
                    logger.info("检测到图片组件")
                    return True
        except Exception as exc:  # noqa: BLE001
            logger.info("看图组件失败：%s", type(exc).__name__)
        text = (getattr(event, "message_str", "") or "")
        for mark in ("<image_caption>", "[图片]", "[CQ:image"):
            if mark in text:
                logger.info("按文本认出图片：%s", mark)
                return True
        if req is not None and "<image_caption>" in (getattr(req, "prompt", "") or ""):
            logger.info("按提示词认出图片")
            return True
        return False

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def merge_image_burst(self, event: AstrMessageEvent) -> None:
        return  # 交给插件
        """连发多张图时，只让最后一条继续，并把前面的图并进去。"""
        try:
            chain = list(event.message_obj.message)
            kinds = [type(c).__name__ for c in chain]
            logger.info("事件钩子进来：%s", kinds)
            imgs = [c for c in chain if isinstance(c, Image)]
        except Exception:  # noqa: BLE001
            logger.exception("事件钩子读消息失败")
            return
        if not imgs:
            return
        self._img_seq += 1
        me = self._img_seq
        self._img_latest = me
        self._img_parts[me] = imgs
        logger.info("收到第 %d 条图片消息", me)
        await asyncio.sleep(12.0)
        if self._img_latest != me:
            try:
                event.stop_event()
            except Exception:  # noqa: BLE001
                pass
            logger.info("这是前面那条图，丢掉，等最后一条一起说")
            return
        earlier = []
        for k in sorted(self._img_parts):
            if k != me:
                earlier.extend(self._img_parts[k])
        if earlier:
            try:
                event.message_obj.message = earlier + list(event.message_obj.message)
                logger.info("把 %d 张图并进同一条", len(earlier) + len(imgs))
            except Exception:  # noqa: BLE001
                logger.exception("拼图失败")
        self._img_parts.clear()

    @filter.on_llm_response()
    async def drop_merged_image_reply(self, event, response: LLMResponse) -> None:
        """连发多张图时，前面几张的回复要丢掉，只留最后一条。"""
        if False and id(event) in self._img_drop:
            self._img_drop.discard(id(event))
            try:
                event.stop_event()
            except Exception:  # noqa: BLE001
                pass
            response.completion_text = ""
            logger.info("这张图的回复被合并掉了")

    @filter.on_llm_request()
    async def inject_memory(self, event: AstrMessageEvent, req: ProviderRequest) -> None:
        if False and self._has_image(event, req):
            self._img_seq += 1
            my = self._img_seq
            self._img_latest = my
            self._img_buf[my] = req.prompt
            await asyncio.sleep(self.IMG_HOLD)
            if self._img_latest != my:
                self._img_drop.add(id(event))
                return
            extra = [self._img_buf[k] for k in sorted(self._img_buf) if k != my]
            if extra:
                req.prompt = "\n".join(extra + [req.prompt])
                logger.info("把 %d 张图并成了一次", len(extra))
            self._img_buf.clear()

        text = (event.message_str or "").strip()
        if not text:
            return
        umo = event.unified_msg_origin
        try:
            facts = self.mem.retrieve_facts(umo, text, FACTS_LIMIT)
            reflection = self.mem.last_reflection(umo)
            block = self.mem.render_block(facts, reflection)
            state = self._self_state(
                getattr(event, "get_self_id", lambda: "")() or ""
            )
            extra = "\n\n".join(x for x in (state, self._comments_state(), block) if x)
            if extra:
                # 记忆/状态每轮都在变。塞进 system_prompt 会把后面整段历史的前缀缓存冲掉，
                # 放进临时内容块里：内容照样给到模型，但系统提示和历史前缀保持稳定，缓存能命中。
                try:
                    from astrbot.core.agent.message import TextPart

                    req.extra_user_content_parts.append(
                        TextPart(text=extra).mark_as_temp()
                    )
                except Exception:  # noqa: BLE001
                    req.prompt = ((req.prompt or "") + "\n\n" + extra).strip()
            try:
                tools = req.func_tool.tools if req.func_tool else []
                logger.info("本轮工具: %s", [x.name for x in tools])
            except Exception:  # noqa: BLE001
                pass
            self.mem.add_message(umo, "user", text)
        except Exception:  # noqa: BLE001
            logger.exception("注入记忆失败")

    # -- 回话后：记下来，够数就复盘 ---------------------------------------- #
    @filter.on_llm_response()
    async def remember(self, event: AstrMessageEvent, response: LLMResponse) -> None:
        umo = event.unified_msg_origin
        try:
            text = (response.completion_text or "").strip()
            if text:
                cleaned, calls = _salvage_calls(text)
                if calls:
                    self._apply_home_calls(calls)
                if cleaned != text:
                    logger.info("剪掉了一段工具调用代码")
                    if not cleaned:
                        cleaned = await self._say_something(event)
                    text = cleaned
                    response.completion_text = cleaned
            user_len = len((event.message_str or "").strip())
            rich = user_len >= 80
            gate = 400 if rich else 300
            target = 300 if rich else 200
            msg_text = event.message_str or ""
            wants_long = any(
                k in msg_text
                for k in ("多说点", "说多点", "说长", "长一点", "多讲", "展开", "详细", "多发点", "多写")
            )
            if text and not wants_long and len(text) >= gate:
                before = len(text)
                short = await self._shorten(text, target)
                if short and len(short) < before:
                    text = short
                    response.completion_text = short
                    logger.info("压短了回复：%d -> %d 字", before, len(short))
            if text:
                auto = await self._auto_search(event, text)
                if auto:
                    text = auto
                    response.completion_text = auto
                    logger.info("用搜索结果替换了她的空承诺")
            if text and any(w in text for w in HOME_WORDS):
                await self._sync_home_from_text(event, text)
            original = text
            try:
                tcs = response.to_openai_tool_calls() if hasattr(response, "to_openai_tool_calls") else None
                if tcs:
                    names = [ (c.get("function") or {}).get("name") for c in tcs ]
                    logger.info("这一轮她调用了工具: %s", names)
            except Exception:  # noqa: BLE001
                pass
            if text:
                hits = _style_hits(text)
                if hits:
                    fixed = await self._rewrite(event, text, hits)
                    if fixed:
                        response.completion_text = fixed
                        text = fixed
                        logger.info("拦截重写 %s -> %s", hits, fixed[:60])
            if text and original != text:
                asyncio.create_task(self._fix_stored_reply(original, text))
            if text:
                self.mem.add_message(umo, "assistant", text)
            turns = self.mem.bump_turn(umo)
            if turns >= CONSOLIDATE_EVERY and umo not in self._busy:
                asyncio.create_task(self._consolidate(umo))
        except Exception:  # noqa: BLE001
            logger.exception("记录对话失败")

    def _comments_state(self) -> str:
        """说说下面别人的新评论，读到就标成已读。"""
        import json as _json
        from pathlib import Path as _Path
        f = _Path(str(ASTRBOT_DIR.parent.parent / "data" / "qzone_comments.json"))
        try:
            data = _json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return ""
        fresh = [c for c in data.values() if not c.get("seen")]
        if not fresh:
            return ""
        fresh.sort(key=lambda c: c.get("time") or 0)
        lines = []
        for c in fresh[:3]:
            import datetime as _dt
            when = _dt.datetime.fromtimestamp(c.get("time") or 0).strftime("%m-%d %H:%M")
            lines.append(f"- {c.get('name')}（{when}）：{c.get('content')}")
        for c in fresh:
            c["seen"] = True
        try:
            f.write_text(_json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
        return "【说说下面的评论】\n你发的说说下面有人留言，你看见了：\n" + "\n".join(lines)

    def _home_state(self) -> str:
        """她自己那间屋子，缓存 5 分钟。"""
        import json as _json

        now = time.time()
        if self._home_text and now - self._home_ts < 300:
            return self._home_text
        try:
            data = _json.loads((QQ_DIR / "data" / "home.json").read_text(encoding="utf-8"))
            items = "、".join(i["name"] for i in data.get("items", [])[:8])
            last = (data.get("diary") or [{}])[-1].get("text", "")
            self._home_text = f"【你的小家】{data.get('name','家')}。屋里有：{items}。"
            if last:
                self._home_text += f"你最近写下的：{last[:60]}"
        except Exception:  # noqa: BLE001
            self._home_text = ""
        self._home_ts = now
        return self._home_text

    def _persona(self) -> str:
        now = time.time()
        if self._persona_text and now - self._persona_ts < 60:
            return self._persona_text
        try:
            conn = sqlite3.connect(str(ASTRBOT_DIR / "data" / "data_v4.db"))
            row = conn.execute(
                "select system_prompt from personas where persona_id='default'"
            ).fetchone()
            conn.close()
            self._persona_text = row[0] if row else ""
        except Exception:  # noqa: BLE001
            self._persona_text = ""
        self._persona_ts = now
        return self._persona_text

    def _llm_cfg(self):
        if self._cfg_cache:
            return self._cfg_cache
        cfg = json.loads((ASTRBOT_DIR / "data" / "cmd_config.json").read_text(encoding="utf-8-sig"))
        src = cfg["provider_sources"][0]
        key = src["key"][0] if isinstance(src["key"], list) else src["key"]
        self._cfg_cache = (str(src["api_base"]), str(key))
        return self._cfg_cache

    async def _quick_json(self, prompt: str) -> dict:
        """用小模型抽一个 JSON 出来，不占主模型。"""
        import urllib.request as _u

        base, key = self._llm_cfg()
        body = {
            "model": "deepseek-flash",
            "messages": [
                {"role": "system", "content": "你是信息抽取器，只输出 JSON。"},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
            "max_tokens": 4000,
        }
        req = _u.Request(
            base.rstrip("/") + "/chat/completions",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
            method="POST",
        )

        def _run():
            with _u.urlopen(req, timeout=60) as r:
                return json.loads(r.read())

        data = await asyncio.to_thread(_run)
        raw = (data["choices"][0]["message"].get("content") or "").strip()
        raw = raw[raw.find("{"): raw.rfind("}") + 1]
        return json.loads(raw)

    async def _quick_text(self, system: str, prompt: str) -> str:
        import urllib.request as _u

        base, key = self._llm_cfg()
        body = {
            "model": "deepseek-flash",
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.8,
            "max_tokens": 2000,
        }
        req = _u.Request(
            base.rstrip("/") + "/chat/completions",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
            method="POST",
        )

        def _run():
            with _u.urlopen(req, timeout=60) as r:
                return json.loads(r.read())

        data = await asyncio.to_thread(_run)
        return (data["choices"][0]["message"].get("content") or "").strip()

    async def _shorten(self, text: str, target: int = 40) -> str:
        """太长的回复压成一两句（她写得多时可以放宽）。"""
        try:
            out = await self._quick_text(
                f"把这段话压成口语，不超过{target}个字，保留意思和语气，"
                "不要解释，不要加引号，只输出改写后的句子。",
                text,
            )
        except Exception:  # noqa: BLE001
            return text
        out = out.strip().strip("「」\"")
        if not out or len(out) >= len(text):
            parts = [s for s in text.replace("！", "。").replace("？", "。").split("。") if s.strip()]
            out = "。".join(parts[:2]) + "。" if parts else text
        return out

    async def _sync_home_from_text(self, event, text: str) -> None:
        return  # 小屋已交给 virtual_activity
        """她嘴上说改了什么，就把改动真的做出来。"""
        prompt = (
            "下面这句话是她说的。判断她对自己那间小屋做了什么实际改动，"
            "输出一个 JSON，字段是："
            "action（add 添 / move 挪 / remove 拿掉）、"
            "items（东西名的数组）、"
            "note（不超过20字的说明）、"
            "spot（窗台 / 窗边 / 中间 / 墙角 / 地上 / 门口）。"
            "没有实际改动就输出 " + '{"action":"none"}' + "。"
            "只算她自己屋里的东西；别人家的、比喻、将来的打算都不算；不确定也算没有。\n\n"
            f"她说的：{text}"
        )
        try:
            data = await self._quick_json(prompt)
        except Exception:  # noqa: BLE001
            logger.exception("抽取改动失败")
            return
        if not isinstance(data, dict) or str(data.get("action", "none")) == "none":
            return
        logger.info("从她的话里抽出改动：%s", data)
        self._apply_home_calls([data])

    async def _fix_stored_reply(self, original: str, sent: str) -> None:
        """她记住的应该是真正发出去的那句，不是改之前的原稿。"""
        if not original or not sent or original == sent:
            return
        await asyncio.sleep(2.5)
        try:
            conn = sqlite3.connect(str(ASTRBOT_DIR / "data" / "data_v4.db"))
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "select rowid as rid, content from conversations order by updated_at desc limit 1"
            ).fetchone()
            msgs = json.loads(row["content"])
            head = original[:18]
            for i in range(len(msgs) - 1, -1, -1):
                if msgs[i].get("role") != "assistant":
                    continue
                c = msgs[i].get("content")
                if isinstance(c, list):
                    text = " ".join(
                        str(x.get("text", ""))
                        for x in c
                        if isinstance(x, dict) and x.get("type") == "text"
                    )
                else:
                    text = str(c or "")
                if text.startswith(head):
                    msgs[i] = {"role": "assistant", "content": sent}
                    conn.execute(
                        "update conversations set content=? where rowid=?",
                        (json.dumps(msgs, ensure_ascii=False), row["rid"]),
                    )
                    conn.commit()
                    logger.info("把她记住的那版改成了发出去的版本")
                    break
            conn.close()
        except Exception:  # noqa: BLE001
            logger.exception("同步存下来的回复失败")

    def _render_home(self, data: dict) -> None:
        lines = [f"# {data.get('name', '家')}", "", "## 屋里的东西"]
        for it in data.get("items", []):
            lines.append(f"- **{it['name']}**：{it.get('note', '')}")
        lines.append("")
        lines.append("## 日记")
        diary = data.get("diary", [])
        if not diary:
            lines.append("（还没写过）")
        for d in reversed(diary[-20:]):
            lines.append(f"**{d['ts'][:16].replace('T', ' ')}**")
            lines.append(d["text"])
            lines.append("")
        (QQ_DIR / "out" / "家.md").write_text("\n".join(lines), encoding="utf-8")
        try:
            import sys as _sys

            if str(QQ_DIR) not in _sys.path:
                _sys.path.insert(0, str(QQ_DIR))
            import home_draw

            home_draw.render()
        except Exception:  # noqa: BLE001
            pass

    def _apply_home_calls(self, calls: list[dict]) -> None:
        """把她说要做的事真的做了。"""
        try:
            path = QQ_DIR / "data" / "home.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            names = {i["name"] for i in data["items"]}
            for c in calls:
                action = str(c.get("action") or "add").lower()
                spot = str(c.get("to") or c.get("spot") or "地上")
                raw = c.get("items") or ([c["item"]] if c.get("item") else [])
                if isinstance(raw, str):
                    raw = [raw]
                for nm in raw:
                    nm = str(nm).strip()[:20]
                    if not nm:
                        continue
                    if action == "move":
                        for it in data["items"]:
                            if it["name"] == nm:
                                it["spot"] = spot
                    elif action == "remove":
                        data["items"] = [i for i in data["items"] if i["name"] != nm]
                        names.discard(nm)
                    else:
                        if nm in names:
                            for it in data["items"]:
                                if it["name"] == nm:
                                    it["spot"] = spot
                                    if c.get("note"):
                                        it["note"] = str(c["note"])[:80]
                        else:
                            note = str(c.get("note") or f"放在{spot}")[:80]
                            data["items"].append({"name": nm, "note": note, "spot": spot})
                            names.add(nm)
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            self._home_ts = 0.0
            self._render_home(data)
            logger.info("替她执行了 %d 个布置动作", len(calls))
        except Exception:  # noqa: BLE001
            logger.exception("执行布置失败")

    async def _say_something(self, event) -> str:
        """只剩工具代码时，让她用一句话把话补上。"""
        provider = self.context.get_using_provider(event.unified_msg_origin)
        if provider is None:
            return ""
        system = (
            self._persona()
            + "\n\n【提醒】你刚才只输出了一段工具调用代码，没有回话。"
            + "现在只用一两句口语回她上一句，别提工具、别解释，直接说。"
        )
        try:
            resp = await provider.text_chat(
                prompt=(event.message_str or "继续说"), system_prompt=system
            )
            return (resp.completion_text or "").strip()
        except Exception:  # noqa: BLE001
            logger.exception("补话失败")
            return ""

    async def _rewrite(self, event, draft: str, hits: list[str]) -> str:
        provider = self.context.get_using_provider(event.unified_msg_origin)
        if provider is None:
            return ""
        system = (
            self._persona()
            + "\n\n【重写】你刚写的那句里出现了禁用的说法：" + "、".join(hits) + "。"
            + "重写它：意思不变，更短，不要出现这些词。只输出重写后的那一句，不要解释。\n"
            + "原句：" + draft
        )
        try:
            resp = await provider.text_chat(
                prompt=(event.message_str or "继续"), system_prompt=system
            )
        except Exception:  # noqa: BLE001
            logger.exception("重写调用失败")
            return ""
        new = (resp.completion_text or "").strip()
        if new and not _style_hits(new):
            return new
        return ""

    async def _consolidate(self, umo: str) -> None:
        if umo in self._busy:
            return
        self._busy.add(umo)
        try:
            rows = self.mem.pending_messages(umo, 80)
            if len(rows) < 6:
                return
            transcript = "\n".join(
                f"{'ta' if r['role'] == 'user' else '你'}: {r['content']}" for r in rows
            )[-6000:]

            provider = self.context.get_using_provider(umo)
            if provider is None:
                logger.warning("没有可用的模型，跳过整理")
                return

            resp = await provider.text_chat(
                prompt="对话如下：\n" + transcript,
                system_prompt=CONSOLIDATE_INSTRUCTION,
            )
            data = parse_json_object(resp.completion_text or "")
            if data is None:
                logger.warning("整理结果不是合法 JSON，跳过")
                return

            added = 0
            for item in (data.get("facts") or [])[:6]:
                if isinstance(item, dict) and item.get("content"):
                    if self.mem.add_fact(
                        umo, str(item.get("topic", "其他")), str(item["content"])
                    ):
                        added += 1

            reflection = str(data.get("reflection") or "").strip()
            if reflection:
                self.mem.add_reflection(umo, reflection)

            self.mem.mark_consolidated(umo, rows[-1]["id"])
            self.mem.reset_turn(umo)
            logger.info("记忆整理完成：新增 %s 条", added)
        except Exception:  # noqa: BLE001
            logger.exception("记忆整理失败")
        finally:
            self._busy.discard(umo)
