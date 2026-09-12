"""
账号路由 — 首次初始化、邀请码注册、登录 / 注销与会话状态。
"""
from __future__ import annotations

import logging
import secrets
import threading
import time

from fastapi import APIRouter, Depends, Request, Response

from auth import SESSION_COOKIE, clear_session_cookie, current_user, set_session_cookie
from config import INVITE_CODE
from helpers import error
from models import LoginRequest, RegisterRequest, SetupRequest
from state import get_auth_mgr

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

_LOGIN_MAX_FAILS = 5
_LOGIN_WINDOW_SEC = 600
_LOGIN_LOCK_SEC = 60
_REGISTER_MAX_FAILS = 8
_REGISTER_WINDOW_SEC = 600
_REGISTER_LOCK_SEC = 60


class _FailTracker:
    """按键记录失败次数，超限后短时锁定。"""

    def __init__(self, max_fails: int, window_sec: float, lock_sec: float):
        self.max_fails = max_fails
        self.window_sec = window_sec
        self.lock_sec = lock_sec
        self._lock = threading.Lock()
        self._fails: dict[str, list[float]] = {}
        self._until: dict[str, float] = {}

    def remaining_lock(self, key: str) -> int:
        now = time.monotonic()
        with self._lock:
            until = self._until.get(key, 0)
            if until > now:
                return int(until - now) + 1
            self._until.pop(key, None)
            return 0

    def hit_fail(self, key: str) -> int:
        now = time.monotonic()
        with self._lock:
            arr = [t for t in self._fails.get(key, []) if now - t < self.window_sec]
            arr.append(now)
            self._fails[key] = arr
            if len(arr) >= self.max_fails:
                self._until[key] = now + self.lock_sec
                self._fails[key] = []
                return int(self.lock_sec)
            return 0

    def hit_ok(self, key: str) -> None:
        with self._lock:
            self._fails.pop(key, None)
            self._until.pop(key, None)


_login_guard = _FailTracker(_LOGIN_MAX_FAILS, _LOGIN_WINDOW_SEC, _LOGIN_LOCK_SEC)
_register_guard = _FailTracker(_REGISTER_MAX_FAILS, _REGISTER_WINDOW_SEC, _REGISTER_LOCK_SEC)


def _is_local_request(request: Request) -> bool:
    """判断是否为本机直连（经隧道/代理的请求会带转发头）。"""
    if request.headers.get("cf-connecting-ip") or request.headers.get("x-forwarded-for"):
        return False
    host = (request.client.host if request.client else "") or ""
    return host in ("127.0.0.1", "::1", "localhost")


def _client_ip(request: Request) -> str:
    cf = (request.headers.get("cf-connecting-ip") or "").strip()
    if cf:
        return cf.split(",")[0].strip()
    xff = (request.headers.get("x-forwarded-for") or "").strip()
    if xff:
        return xff.split(",")[0].strip()
    return (request.client.host if request.client else "") or "unknown"


def _guard_or_error(tracker: _FailTracker, key: str) -> None:
    wait = tracker.remaining_lock(key)
    if wait:
        error("too_many_attempts", f"尝试次数过多，请 {wait} 秒后再试", 429)


def _create_account_or_error(username: str, password: str) -> dict:
    try:
        return get_auth_mgr().create_user(username, password)
    except ValueError as e:
        if str(e) == "duplicate":
            error("duplicate_user", "用户名已存在", 409)
        error("invalid_account", str(e), 400)
    except RuntimeError as e:
        error("create_failed", str(e), 500)


@router.get("/status")
def auth_status():
    """无需登录即可访问：是否已初始化、是否开放注册。"""
    mgr = get_auth_mgr()
    return {
        "initialized": mgr.has_users(),
        "registration_enabled": bool(INVITE_CODE),
    }


@router.get("/me")
def me(user: dict = Depends(current_user)):
    return user


@router.post("/setup")
def setup(request: Request, response: Response, req: SetupRequest):
    """首次初始化：仅允许本机完成，并把旧版全局数据归入该账号。"""
    mgr = get_auth_mgr()
    if mgr.has_users():
        error("already_initialized", "系统已初始化，请直接登录", 409)
    if not _is_local_request(request):
        error("local_only", "首次初始化仅允许在本机浏览器完成", 403)

    user = _create_account_or_error(req.username, req.password)
    try:
        mgr.claim_legacy_data(user["id"])
    except Exception as e:
        logger.warning(f"接管旧版数据失败（不影响新账号使用）: {e}")
    token = mgr.create_session(user["id"])
    set_session_cookie(response, request, token)
    logger.info(f"系统初始化完成，管理员账号: {user['username']}")
    return user


@router.post("/register")
def register(request: Request, response: Response, req: RegisterRequest):
    """邀请码注册（需在 .env 设置 INVITE_CODE）。"""
    mgr = get_auth_mgr()
    if not mgr.has_users():
        error("not_initialized", "系统尚未初始化，请先在本机完成初始化", 409)
    if not INVITE_CODE:
        error("registration_disabled", "未开放注册", 403)

    ip_key = _client_ip(request)
    _guard_or_error(_register_guard, ip_key)
    if not secrets.compare_digest((req.invite_code or "").strip(), INVITE_CODE):
        wait = _register_guard.hit_fail(ip_key)
        if wait:
            error("too_many_attempts", f"尝试次数过多，请 {wait} 秒后再试", 429)
        error("invalid_invite", "邀请码不正确", 403)

    user = _create_account_or_error(req.username, req.password)
    _register_guard.hit_ok(ip_key)
    token = mgr.create_session(user["id"])
    set_session_cookie(response, request, token)
    logger.info(f"新用户注册: {user['username']}")
    return user


@router.post("/login")
def login(request: Request, response: Response, req: LoginRequest):
    key = f"{_client_ip(request)}\n{(req.username or '').strip().lower()}"
    _guard_or_error(_login_guard, key)
    user = get_auth_mgr().authenticate(req.username, req.password)
    if not user:
        wait = _login_guard.hit_fail(key)
        if wait:
            error("too_many_attempts", f"尝试次数过多，请 {wait} 秒后再试", 429)
        error("invalid_credentials", "用户名或密码错误", 401)
    _login_guard.hit_ok(key)
    token = get_auth_mgr().create_session(user["id"])
    set_session_cookie(response, request, token)
    return user


@router.post("/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get(SESSION_COOKIE, "")
    if token:
        get_auth_mgr().delete_session(token)
    clear_session_cookie(response, request)
    return {"ok": True}
