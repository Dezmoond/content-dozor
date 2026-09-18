# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

import bcrypt
from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.config import get_settings
from platform_core.db.models import User
from platform_core.db.session import get_db, init_db

app = FastAPI(title="Auth Service", version="0.1.0")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/token")


class UserCreate(BaseModel):
    email: str
    password: str
    role: str = "analyst"


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


def hash_password(p: str) -> str:
    return bcrypt.hashpw(p.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("ascii"))
    except Exception:
        return False


def create_token(sub: str, role: str, email: str = "") -> str:
    settings = get_settings()
    expire = datetime.utcnow() + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {"sub": sub, "role": role, "exp": expire}
    if email:
        payload["email"] = email
    return jwt.encode(
        payload,
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


@app.on_event("startup")
async def startup():
    await init_db()


@app.get("/health")
async def health():
    return {"status": "ok", "service": "auth"}


@app.post("/register")
async def register(body: UserCreate, db: AsyncSession = Depends(get_db)):
    exists = await db.execute(select(User).where(User.email == body.email))
    if exists.scalar_one_or_none():
        raise HTTPException(400, "Email already registered")
    role = body.role if body.role in ("analyst", "user") else "analyst"
    if role == "user":
        role = "analyst"
    user = User(email=body.email, hashed_password=hash_password(body.password), role=role)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return {"id": user.id, "email": user.email, "role": user.role}


@app.post("/token", response_model=Token)
async def login(form: OAuth2PasswordRequestForm = Depends(), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == form.username))
    user = result.scalar_one_or_none()
    if not user or not verify_password(form.password, user.hashed_password):
        raise HTTPException(401, "Invalid credentials")
    return Token(access_token=create_token(user.id, user.role, user.email))


@app.get("/me")
async def me(token: str = Depends(oauth2_scheme), db: AsyncSession = Depends(get_db)):
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        user_id = payload.get("sub")
    except JWTError:
        raise HTTPException(401, "Invalid token")
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(401)
    return {"id": user.id, "email": user.email, "role": user.role}


@app.get("/users")
async def list_users(token: str = Depends(oauth2_scheme), db: AsyncSession = Depends(get_db)):
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        if payload.get("role") != "admin":
            raise HTTPException(403, "Только администратор")
    except JWTError:
        raise HTTPException(401, "Invalid token")
    result = await db.execute(select(User).order_by(User.created_at.desc()).limit(200))
    return [{"id": u.id, "email": u.email, "role": u.role} for u in result.scalars()]
