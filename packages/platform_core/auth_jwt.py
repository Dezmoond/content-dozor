# -*- coding: utf-8 -*-
"""Общие хелперы JWT для gateway / сервисов."""
from __future__ import annotations

from typing import Any, Dict, Optional

from jose import JWTError, jwt

from platform_core.config import get_settings


def decode_token(token: str) -> Optional[Dict[str, Any]]:
    settings = get_settings()
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None


def user_from_authorization(authorization: Optional[str]) -> Optional[Dict[str, Any]]:
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    payload = decode_token(parts[1].strip())
    if not payload or not payload.get("sub"):
        return None
    return {
        "id": str(payload["sub"]),
        "role": str(payload.get("role") or "analyst"),
        "email": payload.get("email"),
    }
