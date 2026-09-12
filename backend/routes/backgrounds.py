"""
背景图路由 — 按账号隔离的上传、列表、删除与鉴权访问。

用户上传存放于 backend/backgrounds/<user_id>/；
目录根下的图片视为共享资源（可选用，不可通过接口删除）。
"""
from __future__ import annotations

import logging
import re
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import FileResponse

from auth import current_user
from config import (
    BACKGROUNDS_DIR,
    BACKGROUND_ALLOWED_EXTS,
    BACKGROUND_MAX_SIZE,
)

router = APIRouter(prefix="/api/backgrounds", tags=["backgrounds"])
file_router = APIRouter(tags=["backgrounds"])
logger = logging.getLogger(__name__)

_SAFE_NAME_RE = re.compile(r"^[\w\u4e00-\u9fff .()\[\]-]+$")
_UNSAFE_CHARS_RE = re.compile(r"[^\w\u4e00-\u9fff .()\[\]-]+")

_MEDIA_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _user_dir(user_id: int) -> Path:
    return BACKGROUNDS_DIR / str(int(user_id))


def _invalid_name() -> None:
    raise HTTPException(status_code=400, detail={
        "code": "invalid_name",
        "message": "非法的文件名",
        "detail": "",
    })


def _resolve_in(directory: Path, name: str) -> Path:
    """把文件名解析为 directory 内的直接子文件（防路径穿越）。"""
    if not name or "/" in name or "\\" in name or name in (".", ".."):
        _invalid_name()
    if not _SAFE_NAME_RE.match(name):
        _invalid_name()
    root = directory.resolve()
    path = (root / name).resolve()
    if path.parent != root:
        _invalid_name()
    return path


def _sanitize_stem(stem: str) -> str:
    cleaned = _UNSAFE_CHARS_RE.sub("", (stem or "").strip())
    cleaned = cleaned.replace("..", "").strip(" .")
    return (cleaned or "image")[:60]


def _unique_dest(directory: Path, stem: str, suffix: str) -> tuple[str, Path]:
    ts = int(time.time())
    name = f"{ts}_{stem}{suffix}"
    dest = directory / name
    n = 1
    while dest.exists():
        n += 1
        if n > 1000:
            raise HTTPException(status_code=500, detail={
                "code": "save_failed",
                "message": "无法生成可用的文件名",
                "detail": "",
            })
        name = f"{ts}_{stem}_{n}{suffix}"
        dest = directory / name
    return name, dest


def _iter_images(directory: Path):
    if not directory.is_dir():
        return
    try:
        for f in sorted(directory.iterdir(), key=lambda p: p.name.lower()):
            if f.is_file() and f.suffix.lower() in BACKGROUND_ALLOWED_EXTS:
                yield f
    except OSError as e:
        logger.error(f"扫描背景图目录失败: {e}")
        raise HTTPException(status_code=500, detail={
            "code": "scan_failed",
            "message": "读取背景图目录失败",
            "detail": "",
        })


def _resolve_readable(user_id: int, name: str) -> Path:
    """优先用户目录，其次共享根目录。"""
    user_path = _resolve_in(_user_dir(user_id), name)
    if user_path.is_file():
        return user_path
    shared = _resolve_in(BACKGROUNDS_DIR, name)
    if shared.is_file():
        return shared
    raise HTTPException(status_code=404, detail={
        "code": "not_found",
        "message": "背景图不存在",
        "detail": "",
    })


@router.get("")
def list_backgrounds(user: dict = Depends(current_user)):
    """返回当前用户可见的背景图 [{name, url, shared}]。"""
    _ensure_dir(BACKGROUNDS_DIR)
    items = []
    seen = set()
    user_dir = _user_dir(user["id"])
    for f in _iter_images(user_dir):
        items.append({"name": f.name, "url": f"/backgrounds/{f.name}", "shared": False})
        seen.add(f.name)
    for f in _iter_images(BACKGROUNDS_DIR):
        if f.name in seen:
            continue
        items.append({"name": f.name, "url": f"/backgrounds/{f.name}", "shared": True})
    items.sort(key=lambda it: it["name"].lower())
    return items


@router.post("")
async def upload_background(file: UploadFile = File(...), user: dict = Depends(current_user)):
    """上传一张图片到当前用户的背景目录。"""
    dest_dir = _user_dir(user["id"])
    _ensure_dir(dest_dir)

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in BACKGROUND_ALLOWED_EXTS:
        raise HTTPException(status_code=400, detail={
            "code": "invalid_type",
            "message": f"仅支持图片格式: {', '.join(sorted(BACKGROUND_ALLOWED_EXTS))}",
            "detail": "",
        })

    data = await file.read()
    if len(data) == 0:
        raise HTTPException(status_code=400, detail={
            "code": "empty_file", "message": "文件内容为空", "detail": "",
        })
    if len(data) > BACKGROUND_MAX_SIZE:
        raise HTTPException(status_code=400, detail={
            "code": "too_large",
            "message": f"图片不能超过 {BACKGROUND_MAX_SIZE // (1024 * 1024)}MB",
            "detail": "",
        })

    stem = _sanitize_stem(Path(file.filename or "image").stem)
    name, dest = _unique_dest(dest_dir, stem, suffix)

    try:
        dest.write_bytes(data)
    except OSError as e:
        logger.error(f"保存背景图失败: {e}")
        raise HTTPException(status_code=500, detail={
            "code": "save_failed", "message": "保存图片失败", "detail": "",
        })

    logger.info(f"背景图已上传: user={user['id']} {name} ({len(data)} bytes)")
    return {"name": name, "url": f"/backgrounds/{name}", "shared": False}


@router.delete("/{name:path}")
def delete_background(name: str, user: dict = Depends(current_user)):
    """删除当前用户自己上传的背景图。"""
    path = _resolve_in(_user_dir(user["id"]), name)
    if not path.is_file():
        raise HTTPException(status_code=404, detail={
            "code": "not_found", "message": "背景图不存在或不可删除", "detail": "",
        })
    if path.suffix.lower() not in BACKGROUND_ALLOWED_EXTS:
        raise HTTPException(status_code=400, detail={
            "code": "invalid_type", "message": "仅允许删除图片文件", "detail": "",
        })
    try:
        path.unlink()
    except OSError as e:
        logger.error(f"删除背景图失败: {e}")
        raise HTTPException(status_code=500, detail={
            "code": "delete_failed", "message": "删除图片失败", "detail": "",
        })
    return {"ok": True}


@file_router.get("/backgrounds/{name}")
def serve_background(name: str, user: dict = Depends(current_user)):
    """需登录才能读取背景图文件。"""
    path = _resolve_readable(user["id"], name)
    if path.suffix.lower() not in BACKGROUND_ALLOWED_EXTS:
        raise HTTPException(status_code=400, detail={
            "code": "invalid_type", "message": "不支持的文件类型", "detail": "",
        })
    return FileResponse(
        path,
        media_type=_MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream"),
        headers={"Cache-Control": "private, max-age=3600"},
    )
