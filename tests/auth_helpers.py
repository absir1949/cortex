from __future__ import annotations

from sqlmodel import Session, select

from app.auth import create_token
from app.db.engine import get_engine
from app.db.schema import User


def auth_headers(*, role: str = "admin", phone: str | None = None) -> dict[str, str]:
    phone = phone or ("13000000000" if role == "admin" else "13100000000")
    with Session(get_engine()) as s:
        user = s.exec(select(User).where(User.phone == phone)).first()
        if not user:
            user = User(
                phone=phone,
                nickname=role,
                role=role,
                plan="pro" if role == "admin" else "none",
            )
            s.add(user)
            s.commit()
            s.refresh(user)
        token = create_token(user.id, user.phone, user.role)
    return {"Authorization": f"Bearer {token}"}
