# -*- coding: utf-8 -*-
"""Seed default users (password: 123456)."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "packages"))

import bcrypt
from sqlalchemy import select

from platform_core.db.models import User
from platform_core.db.session import get_session_factory, init_db

DEFAULT_USERS = [
    {"email": "admin@diplom.local", "password": "123456", "role": "admin"},
    {"email": "user@diplom.local", "password": "123456", "role": "analyst"},
]


def hash_password(p: str) -> str:
    return bcrypt.hashpw(p.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


async def seed() -> None:
    await init_db()
    factory = get_session_factory()
    async with factory() as db:
        for item in DEFAULT_USERS:
            exists = await db.execute(select(User).where(User.email == item["email"]))
            if exists.scalar_one_or_none():
                continue
            db.add(
                User(
                    email=item["email"],
                    hashed_password=hash_password(item["password"]),
                    role=item["role"],
                )
            )
        await db.commit()
    print("Пользователи: admin@diplom.local / user@diplom.local (пароль 123456)")


if __name__ == "__main__":
    asyncio.run(seed())
