"""认证：JWT 签发/解析 + FastAPI 依赖

设计要点（见 ARCHITECTURE.md 2.2）：
  - JWT 无状态，前端存 localStorage，请求带 Authorization: Bearer <token>
  - 短 TTL（默认 7 天），不设 refresh token（小生意够用）
  - 验证码写死 0000（见 settings.verify_code_override），接真短信时改 _check_code
  - JWT 放 localStorage 是已知债：一旦渲染不受信内容/Markdown 需上 CSP，后续迁 httpOnly cookie

Actor 类型（见 ARCHITECTURE.md 4.1）：
  - user：普通用户，只能操作自己的 group 资源
  - admin：管理员，额外可访问 /config、/prompts、/scheduler、/admin/*
  - system：scheduler/后台任务（不经 HTTP get_current_user，见 scheduler 实现）
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.db.engine import get_session
from app.db.repos import UserRepo
from app.settings import settings


# FastAPI Bearer 认证提取器
_security = HTTPBearer(auto_error=False)


def _jwt_secret() -> str:
    secret = settings.jwt_secret.strip()
    if len(secret) < 32:
        raise RuntimeError("JWT_SECRET 未配置或长度不足 32 字符")
    return secret


def create_token(user_id: int, phone: str, role: str) -> str:
    """签发 JWT。payload 含 user_id、phone、role、过期时间。"""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),        # subject = user_id
        "phone": phone,
        "role": role,
        "iat": now,
        "exp": now + timedelta(hours=settings.jwt_ttl_hours),
    }
    return jwt.encode(payload, _jwt_secret(), algorithm="HS256")


def decode_token(token: str) -> dict:
    """解析 JWT，返回 payload。过期或无效抛 HTTPException 401。"""
    try:
        return jwt.decode(token, _jwt_secret(), algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="token 已过期，请重新登录",
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="token 无效",
        )


def verify_code(phone: str, code: str) -> bool:
    """校验验证码。开发期写死 0000，接真短信后替换此函数。"""
    return bool(phone.strip()) and code == settings.verify_code_override


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_security),
) -> dict:
    """FastAPI 依赖：从请求头提取并验证 JWT，返回用户信息 dict。

    用法：在 router/endpoint 上加 dependencies=[Depends(get_current_user)]
    或在参数中 current_user: dict = Depends(get_current_user)

    返回 dict 而非 DB 对象——避免每次鉴权都查 DB。
    dict 含：user_id, phone, role
    """
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未提供认证信息",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = decode_token(credentials.credentials)
    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="token 无效",
        )

    with get_session() as s:
        user = UserRepo(s).get(user_id)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="用户不存在或已失效",
            )
    return {
        "user_id": user.id,
        "phone": user.phone,
        "role": user.role,
        "plan": user.plan,
        "expires_at": user.expires_at,
    }


def require_admin(current_user: dict = Depends(get_current_user)) -> dict:
    """FastAPI 依赖：要求当前用户是管理员，否则 403。"""
    if current_user["role"] != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要管理员权限",
        )
    return current_user
