from __future__ import annotations
from datetime import datetime
from typing import Any, Optional
from sqlmodel import Session, select

from app.db.schema import SettingKV


class ConfigRepo:
    def __init__(self, session: Session):
        self.session = session

    def get(self, key: str) -> Optional[Any]:
        kv = self.session.exec(select(SettingKV).where(SettingKV.key == key)).first()
        if not kv:
            return None
        return kv.value.get("v") if isinstance(kv.value, dict) and "v" in kv.value else kv.value

    def get_all(self) -> dict[str, Any]:
        rows = self.session.exec(select(SettingKV)).all()
        out: dict[str, Any] = {}
        for kv in rows:
            v = kv.value
            out[kv.key] = v.get("v") if isinstance(v, dict) and "v" in v else v
        return out

    def set(self, key: str, value: Any) -> None:
        kv = self.session.exec(select(SettingKV).where(SettingKV.key == key)).first()
        # 统一包一层 {"v": value} 避免 JSON 只接受 dict/list 的限制
        wrapped = {"v": value}
        if kv:
            kv.value = wrapped
            kv.updated_at = datetime.now().isoformat()
        else:
            kv = SettingKV(key=key, value=wrapped)
        self.session.add(kv)
        self.session.commit()

    def set_many(self, items: dict[str, Any]) -> None:
        for k, v in items.items():
            self.set(k, v)

    def delete(self, key: str) -> None:
        kv = self.session.exec(select(SettingKV).where(SettingKV.key == key)).first()
        if kv:
            self.session.delete(kv)
            self.session.commit()
