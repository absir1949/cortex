from __future__ import annotations
from fastapi import APIRouter

from app.platforms import list_platforms_metadata


router = APIRouter(prefix="/api/platforms", tags=["platforms"])


@router.get("")
def list_platforms():
    """所有支持的平台元数据（给前端添加作者表单用）"""
    return list_platforms_metadata()
