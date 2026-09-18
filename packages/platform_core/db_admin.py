# -*- coding: utf-8 -*-
"""Подключение и создание PostgreSQL из настроек UI."""
from __future__ import annotations

import re
from typing import Any, Dict, Optional, Tuple
from urllib.parse import quote_plus

_DBNAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")


def sanitize_dbname(name: str) -> str:
    n = (name or "").strip()
    if not _DBNAME_RE.match(n):
        raise ValueError(
            "Имя базы: только латиница, цифры и _; не начинать с цифры (до 63 символов)"
        )
    return n


def normalize_db_config(raw: Optional[dict]) -> Dict[str, Any]:
    cfg = dict(raw or {})
    engine = str(cfg.get("engine") or "sqlite").lower()
    if engine not in ("sqlite", "postgresql"):
        engine = "sqlite"
    return {
        "engine": engine,
        "host": str(cfg.get("host") or "127.0.0.1").strip() or "127.0.0.1",
        "port": int(cfg.get("port") or 5432),
        "user": str(cfg.get("user") or "postgres").strip() or "postgres",
        "password": str(cfg.get("password") or ""),
        "dbname": str(cfg.get("dbname") or "content_dozor").strip() or "content_dozor",
        "sslmode": str(cfg.get("sslmode") or "prefer").strip() or "prefer",
    }


def public_db_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Конфиг для ответа API без пароля в открытом виде."""
    out = normalize_db_config(cfg)
    has_pw = bool(out.get("password"))
    out["password"] = ""
    out["password_set"] = has_pw
    return out


def merge_password(new_cfg: dict, old_cfg: Optional[dict]) -> Dict[str, Any]:
    """Если пароль в форме пустой — сохранить прежний."""
    merged = normalize_db_config({**(old_cfg or {}), **(new_cfg or {})})
    new_pw = (new_cfg or {}).get("password")
    if new_pw is None or str(new_pw) == "":
        merged["password"] = str((old_cfg or {}).get("password") or "")
    else:
        merged["password"] = str(new_pw)
    return merged


def build_async_url(cfg: Dict[str, Any], *, database: Optional[str] = None) -> str:
    c = normalize_db_config(cfg)
    if c["engine"] == "sqlite":
        return "sqlite+aiosqlite:///./data/platform.db"
    db = database if database is not None else c["dbname"]
    user = quote_plus(c["user"])
    password = quote_plus(c["password"])
    host = c["host"]
    port = c["port"]
    return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{db}"


def build_asyncpg_kwargs(cfg: Dict[str, Any], *, database: Optional[str] = None) -> dict:
    c = normalize_db_config(cfg)
    return {
        "host": c["host"],
        "port": int(c["port"]),
        "user": c["user"],
        "password": c["password"],
        "database": database if database is not None else c["dbname"],
    }


async def test_postgres(cfg: Dict[str, Any]) -> Tuple[bool, str]:
    try:
        import asyncpg
    except ImportError:
        return False, "Пакет asyncpg не установлен (pip install asyncpg)"
    c = normalize_db_config(cfg)
    if c["engine"] != "postgresql":
        return True, "Выбран SQLite — проверка PostgreSQL не требуется"
    try:
        sanitize_dbname(c["dbname"])
    except ValueError as exc:
        return False, str(exc)
    try:
        conn = await asyncpg.connect(**build_asyncpg_kwargs(c), timeout=10)
        try:
            val = await conn.fetchval("SELECT 1")
            version = await conn.fetchval("SHOW server_version")
        finally:
            await conn.close()
        if val != 1:
            return False, "Неожиданный ответ сервера"
        return True, f"Подключение OK (PostgreSQL {version})"
    except Exception as exc:
        return False, f"Ошибка подключения: {exc}"


async def create_postgres_database(cfg: Dict[str, Any]) -> Tuple[bool, str]:
    try:
        import asyncpg
    except ImportError:
        return False, "Пакет asyncpg не установлен (pip install asyncpg)"
    c = normalize_db_config(cfg)
    if c["engine"] != "postgresql":
        return False, "Создание базы доступно только для PostgreSQL"
    try:
        dbname = sanitize_dbname(c["dbname"])
    except ValueError as exc:
        return False, str(exc)

    # Подключаемся к служебной БД postgres
    try:
        conn = await asyncpg.connect(**build_asyncpg_kwargs(c, database="postgres"), timeout=15)
    except Exception as exc:
        return False, f"Не удалось подключиться к серверу (БД postgres): {exc}"

    try:
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", dbname
        )
        if exists:
            return True, f"База «{dbname}» уже существует"
        # CREATE DATABASE нельзя в транзакции
        await conn.execute(f'CREATE DATABASE "{dbname}" ENCODING \'UTF8\'')
        return True, f"База «{dbname}» создана"
    except Exception as exc:
        return False, f"Не удалось создать базу: {exc}"
    finally:
        await conn.close()


async def ensure_schema_on_url(async_url: str) -> Tuple[bool, str]:
    """Создать таблицы платформы на указанном URL."""
    try:
        from sqlalchemy.ext.asyncio import create_async_engine
        from platform_core.db.models import Base
    except Exception as exc:
        return False, str(exc)
    engine = create_async_engine(async_url, echo=False)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        return True, "Схема таблиц создана/обновлена"
    except Exception as exc:
        return False, f"Ошибка создания схемы: {exc}"
    finally:
        await engine.dispose()
