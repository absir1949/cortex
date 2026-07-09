"""User 仓储——用户 CRUD + 按手机号查找"""
from __future__ import annotations
from typing import Optional
from sqlmodel import Session, select

from app.db.schema import User


class UserRepo:
    def __init__(self, session: Session):
        self.session = session

    def get(self, user_id: int) -> Optional[User]:
        return self.session.get(User, user_id)

    def get_by_phone(self, phone: str) -> Optional[User]:
        return self.session.exec(select(User).where(User.phone == phone)).first()

    def create(self, user: User) -> User:
        self.session.add(user)
        self.session.commit()
        self.session.refresh(user)
        return user

    def update(self, user: User) -> User:
        self.session.add(user)
        self.session.commit()
        self.session.refresh(user)
        return user

    def list_all(self) -> list[User]:
        return list(self.session.exec(select(User).order_by(User.id)).all())
