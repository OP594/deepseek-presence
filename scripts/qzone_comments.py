#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""盯着她发过的说说，把别人留下的评论记下来。

SnowLuma 有 get_qzone_msg_detail，能读到某条说说下的评论。
这里只读不写——写评论要 qzonetoken，拿不到。
"""

import json
import time
import urllib.request

import common

OUT = common.QQ / "data" / "qzone_comments.json"
API = "http://127.0.0.1:3000"
from settings import conf

SELF_UIN = int(conf("self_qq", 0) or 0)
MAX_KEEP = 50


def log(msg: str) -> None:
    common.log("comments", msg)


def call(action: str, payload: dict | None = None) -> dict:
    req = urllib.request.Request(
        f"{API}/{action}",
        data=json.dumps(payload or {}).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + common.onebot_token(),
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read())


def load() -> dict:
    try:
        return json.loads(OUT.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def save(data: dict) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    items = sorted(data.values(), key=lambda c: c.get("time", 0))[-MAX_KEEP:]
    OUT.write_text(
        json.dumps({f"{c['tid']}:{c['cid']}": c for c in items}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )


def scan() -> int:
    data = load()
    try:
        lst = call("get_qzone_msg_list", {"count": 10})
        moods = ((lst.get("data") or {}).get("msglist") or [])
    except Exception as e:  # noqa: BLE001
        log(f"拉说说列表失败: {e}")
        return 0

    fresh = 0
    cutoff = time.time() - 7 * 86400
    for mood in moods:
        tid = str(mood.get("tid") or "")
        if not tid:
            continue
        try:
            d = call("get_qzone_msg_detail", {"tid": tid})
            comments = ((d.get("data") or {}).get("comments") or [])
        except Exception:  # noqa: BLE001
            continue
        for c in comments:
            uin = c.get("uin")
            if uin == SELF_UIN:
                continue
            ts = float(c.get("time") or 0)
            if ts < cutoff:
                continue
            cid = str(c.get("comment_id") or c.get("id") or "")
            key = f"{tid}:{cid}"
            if key in data:
                continue
            data[key] = {
                "tid": tid,
                "cid": cid,
                "uin": uin,
                "name": str(c.get("name") or ""),
                "content": str(c.get("content") or ""),
                "time": ts,
                "seen": False,
                "post": str(mood.get("content") or "")[:60],
            }
            fresh += 1
            log(f"新评论 {c.get('name')}: {c.get('content')}")
        time.sleep(1)
    save(data)
    return fresh


def main() -> None:
    if not common.single_instance("comments"):
        return
    # 心跳必须 30 秒一次，否则看护会以为它死了，重复拉起好几个。
    common.heartbeat("comments")
    log("评论监控启动")
    while True:
        try:
            n = scan()
            if n:
                log(f"本轮新增 {n} 条")
        except Exception as e:  # noqa: BLE001
            log(f"扫描异常: {e}")
        time.sleep(180)


if __name__ == "__main__":
    main()
