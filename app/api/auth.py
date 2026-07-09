"""认证 API：手机号 + 验证码注册/登录

设计（见 ARCHITECTURE.md 2.1）：
  - 前端：注册/登录 UI 一次建成最终形态。
  - 后端：验证码校验函数现在恒校验 0000（settings.verify_code_override）。
  - 以后接真短信：只改 app.auth.verify_code + 加发码逻辑，前端不动。

接口：
  POST /api/auth/code     发验证码（桩，恒成功）
  POST /api/auth/register 手机号+验证码注册（首次登录自动注册）
  POST /api/auth/login    手机号+验证码登录
  GET  /api/me            当前用户信息（需登录）
"""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth import create_token, verify_code, get_current_user
from app.db.engine import get_session
from app.db.repos import UserRepo
from app.db.schema import User
from app.settings import settings


router = APIRouter(prefix="/api/auth", tags=["auth"])
me_router = APIRouter(prefix="/api", tags=["auth"])


# ---------- 请求模型 ----------

class CodeReq(BaseModel):
    phone: str


class AuthReq(BaseModel):
    phone: str
    code: str
    invite_code: str | None = None


class MeResp(BaseModel):
    id: int
    phone: str
    nickname: str
    role: str
    plan: str
    expires_at: str | None = None


# ---------- 接口 ----------

@router.post("/code")
def send_code(req: CodeReq):
    """发送验证码。开发期不真的发，恒返回成功，用户填 0000 即可。"""
    phone = req.phone.strip()
    if not phone:
        raise HTTPException(400, "手机号不能为空")
    # 接真短信后：这里调短信服务发码，验证码存 DB/Redis 带 TTL。
    return {"ok": True, "message": "验证码已发送"}


@router.post("/register")
def register(req: AuthReq):
    """手机号 + 验证码注册。手机号已存在则报错（用 /login 登录）。"""
    phone = req.phone.strip()
    if not phone:
        raise HTTPException(400, "手机号不能为空")
    if not verify_code(phone, req.code):
        raise HTTPException(400, "验证码错误")
    if not _registration_allowed(req.invite_code):
        raise HTTPException(403, "注册暂未开放")

    with get_session() as s:
        repo = UserRepo(s)
        existing = repo.get_by_phone(phone)
        if existing:
            raise HTTPException(409, "该手机号已注册，请直接登录")
        user = repo.create(User(
            phone=phone,
            nickname=f"用户{phone[-4:]}",
            role="user",
            plan="none",
        ))
        token = create_token(user.id, user.phone, user.role)

    return {
        "token": token,
        "user": _me(user),
    }


@router.post("/login")
def login(req: AuthReq):
    """手机号 + 验证码登录。"""
    phone = req.phone.strip()
    if not phone:
        raise HTTPException(400, "手机号不能为空")
    if not verify_code(phone, req.code):
        raise HTTPException(400, "验证码错误")

    with get_session() as s:
        repo = UserRepo(s)
        user = repo.get_by_phone(phone)
        if not user:
            raise HTTPException(404, "该手机号未注册")
        token = create_token(user.id, user.phone, user.role)

    return {
        "token": token,
        "user": _me(user),
    }


@router.get("/me", response_model=MeResp)
@me_router.get("/me", response_model=MeResp)
def get_me(current_user: dict = Depends(get_current_user)):
    """当前用户信息（需登录）。"""
    with get_session() as s:
        user = UserRepo(s).get(current_user["user_id"])
        if not user:
            raise HTTPException(404, "用户不存在")
        return _me(user)


def _me(user: User) -> MeResp:
    return MeResp(
        id=user.id,
        phone=user.phone,
        nickname=user.nickname,
        role=user.role,
        plan=user.plan,
        expires_at=user.expires_at,
    )


def _registration_allowed(invite_code: str | None) -> bool:
    if settings.auth_dev_mode or settings.allow_public_register:
        return True
    configured_code = settings.register_invite_code.strip()
    return bool(configured_code and invite_code and invite_code == configured_code)
