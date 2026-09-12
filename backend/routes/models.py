"""
模型路由 — 提供模型列表、环境状态与默认生成参数（按登录用户隔离）。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from auth import current_user
from config import DEFAULT_PARAMS
from helpers import public_provider
from state import get_slot_mgr

router = APIRouter(tags=["models"])


@router.get("/api/models")
def list_models(user: dict = Depends(current_user)):
    """返回当前用户目录中的全部模型（含提供商信息）。"""
    return get_slot_mgr().list_catalog_models(user["id"])


@router.get("/api/env-check")
def env_check(user: dict = Depends(current_user)):
    """各供应商运行时密钥是否可解析（env 已设置，或使用存库/空密钥）。"""
    result = {}
    for row in get_slot_mgr().list_providers(user["id"]):
        pub = public_provider(row)
        result[pub["slug"]] = pub["key_ready"]
    return result


@router.get("/api/default-params")
def default_params(user: dict = Depends(current_user)):
    """返回默认生成参数，供前端创建存档时使用。"""
    return DEFAULT_PARAMS
