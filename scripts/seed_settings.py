# -*- coding: utf-8 -*-
"""Seed default settings and prompt versions."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "packages"))
sys.path.insert(0, str(_ROOT.parent / "llama_classific" / "llama_train"))

from sqlalchemy import select

from platform_core.db.models import PromptVersion, Setting
from platform_core.db.session import get_session_factory, init_db

DEFAULT_FORBIDDEN_LEXICON = {
    "phrases": ["facebook", "meta", "1488"],
    "max_wer": 0.25,
}

DEFAULT_PIPELINE = {
    "enabled_steps": {
        "ingest_docx": True,
        "chunk_text": True,
        "qwen_entities": True,
        "qwen_extremism": True,
        "qwen_validation": True,
        "qwen_shallow": False,
        "rubert_entities": True,
        "rubert_danger": False,
        "rubert_fio": True,
        "natasha_entities": True,
        "registry_enrich": True,
        "blocklist_lexicon": True,
        "report_json": True,
    }
}

DEFAULT_MODELS = {
    "extremism_model": "qwen-actual-run3-extremism",
    "entities_model": "qwen-newclass3run",
    "validation_model": "qwen25-7b-instruct",
    "temperature": 0.2,
    "max_tokens": 512,
    "num_ctx": 8192,
    "chunk_size": 300,
    "chunk_overlap": 25,
}


async def seed():
    await init_db()
    factory = get_session_factory()
    async with factory() as db:
        for key, value in [
            ("pipeline", DEFAULT_PIPELINE),
            ("models", DEFAULT_MODELS),
            ("forbidden_lexicon", DEFAULT_FORBIDDEN_LEXICON),
            ("database", {
                "engine": "sqlite",
                "host": "127.0.0.1",
                "port": 5432,
                "user": "postgres",
                "password": "",
                "dbname": "content_dozor",
            }),
            ("ui", {"theme": "dark", "analysis_panel_width": 720}),
        ]:
            existing = await db.get(Setting, key)
            if not existing:
                db.add(Setting(key=key, value=value))

        prompts = []
        try:
            from extremism_prompts import SYSTEM as ext_sys
            from credibility_prompts import SYSTEM as val_sys
            prompts = [
                ("qwen_extremism", "v1", ext_sys),
                ("qwen_validation", "v1", val_sys),
            ]
        except ImportError:
            pass
        for proc_id, ver, text in prompts:
            exists = await db.execute(
                select(PromptVersion).where(
                    PromptVersion.processor_id == proc_id,
                    PromptVersion.version == ver,
                )
            )
            if not exists.scalar_one_or_none():
                db.add(PromptVersion(processor_id=proc_id, version=ver, text=text, is_active=True))
        await db.commit()

        # Добавить новые ключи настроек в уже существующую БД
        for key, value in [
            ("forbidden_lexicon", DEFAULT_FORBIDDEN_LEXICON),
        ]:
            if not await db.get(Setting, key):
                db.add(Setting(key=key, value=value))

        # Дописать qwen_shallow в уже сохранённый pipeline.enabled_steps
        pipe = await db.get(Setting, "pipeline")
        if pipe and isinstance(pipe.value, dict):
            steps = dict((pipe.value or {}).get("enabled_steps") or {})
            if "qwen_shallow" not in steps:
                steps["qwen_shallow"] = False
                pipe.value = {**(pipe.value or {}), "enabled_steps": steps}

        # Расширить database-настройки полями PostgreSQL
        db_set = await db.get(Setting, "database")
        if db_set and isinstance(db_set.value, dict):
            cur = dict(db_set.value)
            defaults = {
                "engine": "sqlite",
                "host": "127.0.0.1",
                "port": 5432,
                "user": "postgres",
                "password": "",
                "dbname": "content_dozor",
            }
            changed = False
            for k, v in defaults.items():
                if k not in cur:
                    cur[k] = v
                    changed = True
            if changed:
                db_set.value = cur
        await db.commit()
    print("Начальные настройки загружены.")


if __name__ == "__main__":
    asyncio.run(seed())
