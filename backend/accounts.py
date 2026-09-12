"""
账号与会话管理 — 多用户隔离的鉴权基础。

密码使用标准库 scrypt 加盐哈希存储；会话为数据库中的随机令牌，
由 HttpOnly Cookie 承载，支持注销与过期。
"""
from __future__ import annotations

import datetime
import hashlib
import logging
import re
import secrets
from typing import Optional

import pymysql

from config import SESSION_TTL_DAYS

logger = logging.getLogger(__name__)

USERNAME_RE = re.compile(r"^[A-Za-z0-9_\-\u4e00-\u9fff]{2,32}$")
PASSWORD_MIN_LEN = 6
PASSWORD_MAX_LEN = 128

_SCRYPT_N = 16384
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 32


def hash_password(password: str) -> str:
    """生成 `scrypt$N$r$p$salt$hash` 格式的密码哈希。"""
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(
        password.encode("utf-8"), salt=salt,
        n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=_SCRYPT_DKLEN,
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """校验密码是否与哈希匹配（恒定时间比较）。"""
    try:
        scheme, n, r, p, salt_hex, hash_hex = (stored or "").split("$")
        if scheme != "scrypt":
            return False
        expected = bytes.fromhex(hash_hex)
        dk = hashlib.scrypt(
            password.encode("utf-8"), salt=bytes.fromhex(salt_hex),
            n=int(n), r=int(r), p=int(p), dklen=len(expected),
        )
        return secrets.compare_digest(dk, expected)
    except (ValueError, TypeError):
        return False


# 用户不存在时仍走一次相同耗时的哈希，避免按响应时间枚举用户名
_DUMMY_PASSWORD_HASH = hash_password("__nehchat_dummy__")


def validate_username(username: str) -> str:
    u = (username or "").strip()
    if not USERNAME_RE.match(u):
        raise ValueError("用户名需为 2-32 位字母、数字、下划线、连字符或中文")
    return u


def validate_password(password: str) -> str:
    if not password or len(password) < PASSWORD_MIN_LEN:
        raise ValueError(f"密码至少需要 {PASSWORD_MIN_LEN} 位")
    if len(password) > PASSWORD_MAX_LEN:
        raise ValueError(f"密码不能超过 {PASSWORD_MAX_LEN} 位")
    return password


class AccountManager:
    """用户与会话的数据库访问；复用 SlotManager 的连接池。"""

    def __init__(self, pool):
        self.pool = pool
        self._init_tables()

    def _init_tables(self):
        conn = self.pool.connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        username VARCHAR(32) NOT NULL UNIQUE,
                        password_hash VARCHAR(256) NOT NULL,
                        created_at VARCHAR(32) DEFAULT ''
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS sessions (
                        token CHAR(64) PRIMARY KEY,
                        user_id INT NOT NULL,
                        created_at VARCHAR(32) DEFAULT '',
                        expires_at VARCHAR(32) DEFAULT '',
                        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                        INDEX idx_sessions_user (user_id)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """)
            conn.commit()
            logger.info("用户与会话表初始化完成")
        except pymysql.Error as e:
            conn.rollback()
            logger.error(f"用户与会话表初始化失败: {e}")
            raise
        finally:
            conn.close()

    @staticmethod
    def _now() -> datetime.datetime:
        return datetime.datetime.now()

    def has_users(self) -> bool:
        conn = self.pool.connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) AS c FROM users")
                return (cursor.fetchone() or {}).get("c", 0) > 0
        finally:
            conn.close()

    def create_user(self, username: str, password: str) -> dict:
        """创建账号；用户名重复时抛出 ValueError("duplicate")。"""
        u = validate_username(username)
        p = validate_password(password)
        conn = self.pool.connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO users (username, password_hash, created_at) VALUES (%s, %s, %s)",
                    (u, hash_password(p), self._now().isoformat()),
                )
                user_id = cursor.lastrowid
            conn.commit()
            return {"id": user_id, "username": u}
        except pymysql.IntegrityError:
            conn.rollback()
            raise ValueError("duplicate")
        except pymysql.Error as e:
            conn.rollback()
            logger.error(f"创建用户失败: {e}")
            raise RuntimeError(f"创建账号失败: {e}")
        finally:
            conn.close()

    def _get_user(self, where: str, value) -> Optional[dict]:
        conn = self.pool.connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"SELECT id, username, password_hash FROM users WHERE {where} = %s",
                    (value,),
                )
                return cursor.fetchone()
        finally:
            conn.close()

    def get_user_by_username(self, username: str) -> Optional[dict]:
        return self._get_user("username", (username or "").strip())

    def get_user_by_id(self, user_id: int) -> Optional[dict]:
        return self._get_user("id", user_id)

    def authenticate(self, username: str, password: str) -> Optional[dict]:
        """校验用户名密码，成功返回 {id, username}，失败返回 None。"""
        row = self.get_user_by_username(username)
        stored = (row.get("password_hash") if row else "") or _DUMMY_PASSWORD_HASH
        ok = verify_password(password, stored)
        if not row or not ok:
            return None
        return {"id": row["id"], "username": row["username"]}

    def create_session(self, user_id: int) -> str:
        token = secrets.token_urlsafe(32)
        now = self._now()
        expires = now + datetime.timedelta(days=SESSION_TTL_DAYS)
        conn = self.pool.connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (%s, %s, %s, %s)",
                    (token, user_id, now.isoformat(), expires.isoformat()),
                )
            conn.commit()
            return token
        except pymysql.Error as e:
            conn.rollback()
            logger.error(f"创建会话失败: {e}")
            raise RuntimeError(f"创建会话失败: {e}")
        finally:
            conn.close()

    def resolve_session(self, token: str) -> Optional[dict]:
        """根据令牌返回当前用户；过期会话会被清理。"""
        if not token:
            return None
        conn = self.pool.connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT s.user_id, s.expires_at, u.username "
                    "FROM sessions s JOIN users u ON u.id = s.user_id "
                    "WHERE s.token = %s",
                    (token,),
                )
                row = cursor.fetchone()
                if not row:
                    return None
                try:
                    expires = datetime.datetime.fromisoformat(row.get("expires_at") or "")
                except ValueError:
                    expires = self._now()
                if expires <= self._now():
                    cursor.execute("DELETE FROM sessions WHERE token = %s", (token,))
                    conn.commit()
                    return None
                return {"id": row["user_id"], "username": row["username"]}
        finally:
            conn.close()

    def delete_session(self, token: str) -> None:
        if not token:
            return
        conn = self.pool.connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM sessions WHERE token = %s", (token,))
            conn.commit()
        except pymysql.Error as e:
            conn.rollback()
            logger.warning(f"删除会话失败: {e}")
        finally:
            conn.close()

    def claim_legacy_data(self, user_id: int) -> None:
        """把旧版全局数据（user_id = 0）归入指定账号。"""
        conn = self.pool.connection()
        try:
            with conn.cursor() as cursor:
                for table in ("slots", "messages", "providers"):
                    cursor.execute(
                        f"UPDATE `{table}` SET user_id = %s WHERE user_id = 0",
                        (user_id,),
                    )
            conn.commit()
            logger.info(f"已将旧版全局数据归入账号 #{user_id}")
        except pymysql.Error as e:
            conn.rollback()
            logger.error(f"迁移旧数据失败: {e}")
            raise
        finally:
            conn.close()
