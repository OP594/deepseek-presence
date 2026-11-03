#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""给 AstrBot 的网页套一层本地代理，自动带上登录 cookie。

这样打开 http://127.0.0.1:6186/ 就已经是登录状态，不用输密码，
也不用折腾浏览器配置。

    py webproxy.py        前台跑
"""

import common
import json
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent  # 项目根
CONF = BASE / "data" / "dashboard.json"
TARGET = "http://127.0.0.1:6185"
PORT = 6186

_token = {"value": "", "at": 0.0}
_lock = threading.Lock()


def creds() -> tuple[str, str]:
    try:
        d = json.loads(CONF.read_text(encoding="utf-8"))
        return d.get("username") or "astrbot", d.get("password") or ""
    except Exception:  # noqa: BLE001
        return "astrbot", ""


def token() -> str:
    """拿一个登录 token，缓存 6 天。"""
    with _lock:
        if _token["value"] and time.time() - _token["at"] < 6 * 86400:
            return _token["value"]
        user, pwd = creds()
        body = json.dumps({"username": user, "password": pwd}).encode()
        req = urllib.request.Request(
            TARGET + "/api/auth/login",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read())["data"]
        _token["value"] = data["token"]
        _token["at"] = time.time()
        return _token["value"]




def beat(name: str = "webproxy") -> None:
    """心跳，看护靠它判断我还活着。"""
    d = BASE / "QQ机器人" / "logs" / "beat"
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{name}.txt"

    def _run() -> None:
        while True:
            try:
                f.write_text(str(time.time()), encoding="utf-8")
            except Exception:  # noqa: BLE001
                pass
            time.sleep(30)

    threading.Thread(target=_run, daemon=True).start()


HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "content-length", "host",
}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # noqa: A003
        pass

    def handle_one_request(self) -> None:
        # 浏览器/客户端半路断开是正常的，别每次都往 .err 里刷一屏 traceback
        try:
            super().handle_one_request()
        except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
            self.close_connection = True

    PAGE = Path(__file__).resolve().parent / "room_page.html"

    def _serve_page(self) -> None:
        try:
            data = self.PAGE.read_bytes()
        except Exception as e:  # noqa: BLE001
            data = f"room_page.html 读不到: {e}".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _proxy(self, method: str) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None

        try:
            auth = token()
        except Exception:  # noqa: BLE001
            auth = ""

        headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP}
        if auth:
            headers["Cookie"] = f"astrbot_dashboard_jwt={auth}"

        req = urllib.request.Request(
            TARGET + self.path, data=body, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = resp.read()
                status = resp.status
                out_headers = [(k, v) for k, v in resp.getheaders() if k.lower() not in HOP]
        except urllib.error.HTTPError as e:
            data = e.read()
            status = e.code
            out_headers = [(k, v) for k, v in e.headers.items() if k.lower() not in HOP]
        except Exception as e:  # noqa: BLE001
            data = f"proxy error: {e}".encode()
            status = 502
            out_headers = [("Content-Type", "text/plain; charset=utf-8")]

        self.send_response(status)
        for k, v in out_headers:
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if method != "HEAD":
            self.wfile.write(data)

    def do_GET(self):  # noqa: N802
        if self.path.split("?")[0] in ("/room", "/room/", "/"):
            self._serve_page()
            return
        self._proxy("GET")

    def do_POST(self):  # noqa: N802
        self._proxy("POST")

    def do_PATCH(self):  # noqa: N802
        self._proxy("PATCH")

    def do_PUT(self):  # noqa: N802
        self._proxy("PUT")

    def do_DELETE(self):  # noqa: N802
        self._proxy("DELETE")

    def do_HEAD(self):  # noqa: N802
        self._proxy("HEAD")


def main() -> None:
    if not common.single_instance("webproxy"):
        return
    common.heartbeat("webproxy")
    beat()
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"代理已启动：http://127.0.0.1:{PORT}/  →  {TARGET}")
    srv.serve_forever()


if __name__ == "__main__":
    main()
