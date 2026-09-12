"""
账号路由 — 首次初始化、邀请码注册、登录 / 注销与会话状态。
"""
from __future__ import annotations

import logging
import secrets

from fastapi import APIRouter, Depends, Request, Response

from auth import SESSION_COOKIE, clear_session_cookie, current_user, set_session_cookie
from config import INVITE_CODE
from helpers import error
from models import LoginRequest, RegisterRequest, SetupRequest
from state import get_auth_mgr

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _is_local_request(request: Request) -> bool:
    """判断是否为本机直连（经隧道/代理的请求会带转发头）。"""
    if request.headers.get("cf-connecting-ip") or request.headers.get("x-forwarded-for"):
        return False
    host = (request.client.host if request.client else "") or ""
    return host in ("127.0.0.1", "::1", "localhost")


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
    if not secrets.compare_digest((req.invite_code or "").strip(), INVITE_CODE):
        error("invalid_invite", "邀请码不正确", 403)

    user = _create_account_or_error(req.username, req.password)
    token = mgr.create_session(user["id"])
    set_session_cookie(response, request, token)
    logger.info(f"新用户注册: {user['username']}")
    return user


@router.post("/login")
def login(request: Request, response: Response, req: LoginRequest):
    user = get_auth_mgr().authenticate(req.username, req.password)
    if not user:
        error("invalid_credentials", "用户名或密码错误", 401)
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
