"""
可选 HTTP Basic 访问鉴权中间件 + 多用户会话登录依赖。

Basic Auth 默认不启用：WEB_USER / WEB_PASSWORD 均未设置时完全放行（本地使用）。
两者都设置后，页面、静态资源与 /api 全部要求登录，适用于隧道、端口转发等公网暴露场景。

多用户模式使用 Cookie 会话：`current_user` 依赖从请求 Cookie 中解析当前账号，
未登录时返回 401。
"""
from __future__ import annotations

import base64
import binascii
import json
import secrets

from fastapi import Request, Response

from config import SESSION_TTL_DAYS
from helpers import error
from state import get_auth_mgr

SESSION_COOKIE = "nehchat_session"

_UNAUTHORIZED_BODY = json.dumps(
    {"code": "unauthorized", "message": "访问需要登录", "detail": ""},
    ensure_ascii=False,
).encode("utf-8")

_WWW_AUTHENTICATE = b'Basic realm="Nehchat Agent", charset="UTF-8"'


class BasicAuthMiddleware:
    """纯 ASGI 中间件，避免缓冲，不影响 SSE 流式响应。"""

    def __init__(self, app, username: str, password: str):
        self.app = app
        self._user = username.encode("utf-8")
        self._password = password.encode("utf-8")

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        if self._check(headers.get(b"authorization", b"")):
            await self.app(scope, receive, send)
            return

        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json; charset=utf-8"),
                    (b"www-authenticate", _WWW_AUTHENTICATE),
                    (b"content-length", str(len(_UNAUTHORIZED_BODY)).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": _UNAUTHORIZED_BODY})

    def _check(self, header: bytes) -> bool:
        prefix = b"basic "
        if not header.lower().startswith(prefix):
            return False
        try:
            decoded = base64.b64decode(header[len(prefix):], validate=True)
        except (binascii.Error, ValueError):
            return False
        username, sep, password = decoded.partition(b":")
        if not sep:
            return False
        return secrets.compare_digest(username, self._user) and secrets.compare_digest(
            password, self._password
        )


# ── 多用户会话 ──


def current_user(request: Request) -> dict:
    """FastAPI 依赖：解析当前登录用户，未登录返回 401。"""
    token = request.cookies.get(SESSION_COOKIE, "")
    if not token:
        error("unauthorized", "请先登录", 401)
    user = get_auth_mgr().resolve_session(token)
    if not user:
        error("unauthorized", "登录已过期，请重新登录", 401)
    return user


def _cookie_secure(request: Request) -> bool:
    """经 Cloudflare 隧道等 HTTPS 入口访问时给 Cookie 加 Secure。"""
    proto = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip().lower()
    return proto == "https"


def set_session_cookie(response: Response, request: Request, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_TTL_DAYS * 86400,
        httponly=True,
        samesite="lax",
        secure=_cookie_secure(request),
        path="/",
    )


def clear_session_cookie(response: Response, request: Request) -> None:
    response.delete_cookie(
        SESSION_COOKIE,
        path="/",
        httponly=True,
        samesite="lax",
        secure=_cookie_secure(request),
    )
