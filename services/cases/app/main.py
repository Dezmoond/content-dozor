# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiofiles
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.config import get_settings
from platform_core.db.models import AuditLog, Case, Document, Finding, Job, PipelineRun, PromptVersion, Setting, User
from platform_core.db.session import get_db, init_db

app = FastAPI(title="Cases Service", version="0.1.0")


class CaseCreate(BaseModel):
    title: str
    created_by: Optional[str] = None


class CaseOut(BaseModel):
    id: str
    title: str
    status: str
    created_by: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class CaseUpdate(BaseModel):
    title: Optional[str] = None
    status: Optional[str] = None


class SettingUpdate(BaseModel):
    value: dict


class AuditCreate(BaseModel):
    user_id: Optional[str] = None
    case_id: Optional[str] = None
    document_id: Optional[str] = None
    action: str
    processor_id: Optional[str] = None
    model_name: Optional[str] = None
    prompt_version_id: Optional[str] = None
    request_hash: Optional[str] = None
    response_hash: Optional[str] = None
    request_text: Optional[str] = None
    response_text: Optional[str] = None
    meta: Optional[dict] = None


@app.on_event("startup")
async def startup():
    settings = get_settings()
    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.storage_dir).mkdir(parents=True, exist_ok=True)
    await init_db()


@app.get("/health")
async def health():
    return {"status": "ok", "service": "cases"}


@app.get("/cases", response_model=List[CaseOut])
async def list_cases(
    created_by: Optional[str] = None,
    role: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    q = select(Case).order_by(Case.created_at.desc()).limit(200)
    if role != "admin" and created_by:
        q = q.where(Case.created_by == created_by)
    result = await db.execute(q)
    return result.scalars().all()


@app.post("/cases", response_model=CaseOut)
async def create_case(body: CaseCreate, db: AsyncSession = Depends(get_db)):
    case = Case(title=body.title, created_by=body.created_by)
    db.add(case)
    await db.commit()
    await db.refresh(case)
    return case


@app.patch("/cases/{case_id}")
async def patch_case(case_id: str, body: dict, db: AsyncSession = Depends(get_db)):
    case = await db.get(Case, case_id)
    if not case:
        raise HTTPException(404, "Case not found")
    for k in ("title", "status"):
        if k in body and body[k] is not None:
            setattr(case, k, body[k])
    await db.commit()
    await db.refresh(case)
    return CaseOut.model_validate(case)


@app.get("/cases/{case_id}")
async def get_case(
    case_id: str,
    created_by: Optional[str] = None,
    role: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    case = await db.get(Case, case_id)
    if not case:
        raise HTTPException(404, "Case not found")
    if role != "admin" and created_by and case.created_by and case.created_by != created_by:
        raise HTTPException(403, "Нет доступа к этому кейсу")
    docs_rows = list((await db.execute(select(Document).where(Document.case_id == case_id))).scalars())
    findings_rows = list((await db.execute(select(Finding).where(Finding.case_id == case_id))).scalars())
    runs_rows = list((
        await db.execute(
            select(PipelineRun).where(PipelineRun.case_id == case_id).order_by(PipelineRun.created_at.desc())
        )
    ).scalars())
    # авто-исправление статуса после успешного анализа
    if case.status == "processing" and any(r.status == "success" for r in runs_rows):
        case.status = "review"
        await db.commit()
    elif case.status == "processing" and any(r.status == "failed" for r in runs_rows) and not any(r.status == "success" for r in runs_rows):
        case.status = "failed"
        await db.commit()
    owner_email = None
    if case.created_by:
        owner = await db.get(User, case.created_by)
        owner_email = owner.email if owner else None
    return {
        "case": {**CaseOut.model_validate(case).model_dump(mode="json"), "owner_email": owner_email},
        "documents": [
            {
                "id": d.id,
                "filename": d.filename,
                "source_type": d.source_type,
                "meta": d.meta,
                "created_at": d.created_at.isoformat() if d.created_at else None,
            }
            for d in docs_rows
        ],
        "findings": [
            {
                "id": f.id,
                "kind": f.kind,
                "payload": f.payload,
                "confidence": f.confidence,
                "document_id": f.document_id,
                "tool": (f.payload or {}).get("tool") if isinstance(f.payload, dict) else None,
                "processor": (f.payload or {}).get("processor") if isinstance(f.payload, dict) else None,
            }
            for f in findings_rows
        ],
        "pipeline_runs": [
            {
                "id": r.id,
                "status": r.status,
                "pipeline_config": r.pipeline_config,
                "steps_log": r.steps_log,
                "timing": (r.result or {}).get("timing") if isinstance(r.result, dict) else None,
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "result": r.result,
            }
            for r in runs_rows
        ],
    }


@app.post("/cases/{case_id}/documents")
async def upload_document(
    case_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    case = await db.get(Case, case_id)
    if not case:
        raise HTTPException(404, "Case not found")
    existing = await db.execute(select(Document).where(Document.case_id == case_id).limit(1))
    if existing.scalars().first():
        raise HTTPException(
            409,
            "В кейс уже загружен документ. Создайте новый кейс для другого файла.",
        )
    settings = get_settings()
    content = await file.read()
    doc_id = str(uuid.uuid4())
    ext = Path(file.filename or "doc").suffix or ".bin"
    dest = Path(settings.upload_dir) / case_id / f"{doc_id}{ext}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    async with aiofiles.open(dest, "wb") as f:
        await f.write(content)
    doc = Document(
        id=doc_id,
        case_id=case_id,
        source_type=ext.lstrip(".") or "bin",
        filename=file.filename or "upload",
        storage_path=str(dest),
        content_hash=hashlib.sha256(content).hexdigest(),
    )
    db.add(doc)
    case.status = "processing"
    await db.commit()
    return {"document_id": doc_id, "path": str(dest), "filename": file.filename}


def _as_bool(value: Any, default: bool = True) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


@app.get("/ingest/sources")
async def list_ingest_sources():
    from platform_core.ingest_sources import list_source_types, probe_internet

    return {"items": list_source_types(), "online": probe_internet()}


@app.get("/ingest/connectivity")
async def ingest_connectivity():
    from platform_core.ingest_sources import probe_internet

    return {"online": probe_internet()}


@app.post("/cases/{case_id}/ingest")
async def ingest_source(
    case_id: str,
    source_type: str = Form(...),
    url: Optional[str] = Form(None),
    text: Optional[str] = Form(None),
    include_comments: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    db: AsyncSession = Depends(get_db),
):
    import json as json_lib

    from platform_core.ingest_sources import probe_internet, source_label, validate_ingest

    case = await db.get(Case, case_id)
    if not case:
        raise HTTPException(404, "Case not found")
    existing = await db.execute(select(Document).where(Document.case_id == case_id).limit(1))
    if existing.scalars().first():
        raise HTTPException(
            409,
            "В кейс уже загружен источник. Создайте новый кейс для другого материала.",
        )

    filename = (file.filename or "").strip() if file is not None else ""
    has_file = bool(file is not None and filename)
    comments = _as_bool(include_comments, True)
    url_s = (url or "").strip()
    text_s = (text or "").strip()
    online = probe_internet()
    try:
        spec = validate_ingest(
            source_type,
            has_file=has_file,
            filename=filename or None,
            text=text_s or None,
            url=url_s or None,
            online=online,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    settings = get_settings()
    doc_id = str(uuid.uuid4())
    dest_dir = Path(settings.upload_dir) / case_id
    dest_dir.mkdir(parents=True, exist_ok=True)

    meta: Dict[str, Any] = {
        "source_type": spec["id"],
        "include_comments": comments,
        "url": url_s or None,
        "online_at_upload": online,
    }

    if has_file and file is not None:
        content = await file.read()
        ext = Path(filename).suffix or ".bin"
        dest = dest_dir / f"{doc_id}{ext}"
        display_name = filename
    elif spec["id"] == "paste":
        content = text_s.encode("utf-8")
        dest = dest_dir / f"{doc_id}.txt"
        display_name = "Вставленный текст"
        meta["chars"] = len(text_s)
    else:
        payload = {
            "source_type": spec["id"],
            "url": url_s,
            "include_comments": comments,
        }
        content = json_lib.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        dest = dest_dir / f"{doc_id}.source.json"
        display_name = url_s or source_label(spec["id"])

    async with aiofiles.open(dest, "wb") as out:
        await out.write(content)

    doc = Document(
        id=doc_id,
        case_id=case_id,
        source_type=spec["id"],
        filename=display_name[:512],
        storage_path=str(dest),
        content_hash=hashlib.sha256(content).hexdigest(),
        meta=meta,
    )
    db.add(doc)
    case.status = "processing"
    await db.commit()
    return {
        "document_id": doc_id,
        "path": str(dest),
        "filename": display_name,
        "source_type": spec["id"],
        "source_url": url_s or None,
        "include_comments": comments,
        "meta": meta,
    }


@app.delete("/cases/{case_id}")
async def delete_case(case_id: str, db: AsyncSession = Depends(get_db)):
    from sqlalchemy import delete as sa_delete

    case = await db.get(Case, case_id)
    if not case:
        raise HTTPException(404, "Case not found")

    docs = list((await db.execute(select(Document).where(Document.case_id == case_id))).scalars())
    settings = get_settings()
    for d in docs:
        try:
            p = Path(d.storage_path)
            if p.is_file():
                p.unlink()
        except OSError:
            pass
    case_dir = Path(settings.upload_dir) / case_id
    if case_dir.is_dir():
        try:
            for child in case_dir.iterdir():
                try:
                    child.unlink()
                except OSError:
                    pass
            case_dir.rmdir()
        except OSError:
            pass

    await db.execute(sa_delete(Finding).where(Finding.case_id == case_id))
    await db.execute(sa_delete(PipelineRun).where(PipelineRun.case_id == case_id))
    await db.execute(sa_delete(Job).where(Job.case_id == case_id))
    await db.execute(sa_delete(AuditLog).where(AuditLog.case_id == case_id))
    await db.execute(sa_delete(Document).where(Document.case_id == case_id))
    await db.delete(case)
    await db.commit()
    return {"ok": True, "id": case_id}


@app.post("/jobs")
async def create_job(body: dict, db: AsyncSession = Depends(get_db)):
    job = Job(
        case_id=body.get("case_id"),
        document_id=body.get("document_id"),
        job_type=body.get("job_type", "analyze"),
        status="pending",
        celery_task_id=body.get("celery_task_id"),
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return {"id": job.id, "status": job.status}


@app.patch("/jobs/{job_id}")
async def update_job(job_id: str, body: dict, db: AsyncSession = Depends(get_db)):
    job = await db.get(Job, job_id)
    if not job:
        raise HTTPException(404)
    for k in ("status", "progress", "detail", "result", "celery_task_id"):
        if k in body:
            setattr(job, k, body[k])
    await db.commit()
    return {"id": job.id, "status": job.status, "progress": job.progress}


@app.get("/jobs/{job_id}")
async def get_job(job_id: str, db: AsyncSession = Depends(get_db)):
    job = await db.get(Job, job_id)
    if not job:
        raise HTTPException(404)
    return {
        "id": job.id,
        "case_id": job.case_id,
        "document_id": job.document_id,
        "job_type": job.job_type,
        "status": job.status,
        "progress": job.progress,
        "detail": job.detail,
        "result": job.result,
        "celery_task_id": job.celery_task_id,
    }


@app.post("/pipeline-runs")
async def create_pipeline_run(body: dict, db: AsyncSession = Depends(get_db)):
    run = PipelineRun(
        case_id=body["case_id"],
        document_id=body.get("document_id"),
        pipeline_config=body.get("pipeline_config", {}),
        status=body.get("status", "running"),
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    return {"id": run.id}


@app.patch("/pipeline-runs/{run_id}")
async def update_pipeline_run(run_id: str, body: dict, db: AsyncSession = Depends(get_db)):
    run = await db.get(PipelineRun, run_id)
    if not run:
        raise HTTPException(404)
    for k in ("status", "steps_log", "result", "finished_at", "pipeline_config"):
        if k in body:
            val = body[k]
            if k == "finished_at" and isinstance(val, str):
                val = datetime.fromisoformat(val.replace("Z", "+00:00"))
            setattr(run, k, val)
    await db.commit()
    return {"id": run.id, "status": run.status}


@app.get("/cases/{case_id}/stats")
async def get_case_stats(case_id: str, db: AsyncSession = Depends(get_db)):
    """Сводка времени обработки по всем pipeline runs кейса."""
    case = await db.get(Case, case_id)
    if not case:
        raise HTTPException(404, "Case not found")
    runs = await db.execute(
        select(PipelineRun).where(PipelineRun.case_id == case_id).order_by(PipelineRun.created_at.desc())
    )
    items = []
    for run in runs.scalars():
        timing = None
        if isinstance(run.result, dict):
            timing = run.result.get("timing")
        items.append({
            "run_id": run.id,
            "document_id": run.document_id,
            "status": run.status,
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            "timing": timing,
            "steps_log": run.steps_log,
        })
    return {"case_id": case_id, "runs": items}


@app.get("/settings")
async def get_settings_all(db: AsyncSession = Depends(get_db)):
    from platform_core.db_admin import public_db_config

    result = await db.execute(select(Setting))
    out = {s.key: s.value for s in result.scalars()}
    if "database" in out and isinstance(out["database"], dict):
        out["database"] = public_db_config(out["database"])
    return out


@app.get("/settings/{key}")
async def get_setting(key: str, db: AsyncSession = Depends(get_db)):
    from platform_core.db_admin import public_db_config

    s = await db.get(Setting, key)
    if not s:
        return {}
    if key == "database" and isinstance(s.value, dict):
        return public_db_config(s.value)
    return s.value


@app.put("/settings/{key}")
async def put_setting(key: str, body: SettingUpdate, db: AsyncSession = Depends(get_db)):
    from platform_core.db_admin import merge_password, public_db_config

    value = body.value
    if key == "database" and isinstance(value, dict):
        old = await db.get(Setting, key)
        old_val = old.value if old and isinstance(old.value, dict) else {}
        value = merge_password(value, old_val)

    s = await db.get(Setting, key)
    if not s:
        s = Setting(key=key, value=value)
        db.add(s)
    else:
        s.value = value
    await db.commit()
    if key == "database" and isinstance(value, dict):
        return {"key": key, "value": public_db_config(value)}
    return {"key": key, "value": value}


class DatabaseActionBody(BaseModel):
    engine: str = "postgresql"
    host: str = "127.0.0.1"
    port: int = 5432
    user: str = "postgres"
    password: Optional[str] = None
    dbname: str = "content_dozor"
    sslmode: str = "prefer"
    init_schema: bool = False


async def _resolve_db_cfg(body: DatabaseActionBody, db: AsyncSession) -> dict:
    from platform_core.db_admin import merge_password

    incoming = body.model_dump()
    old = await db.get(Setting, "database")
    old_val = old.value if old and isinstance(old.value, dict) else {}
    return merge_password(incoming, old_val)


@app.post("/database/test")
async def database_test(body: DatabaseActionBody, db: AsyncSession = Depends(get_db)):
    from platform_core.db_admin import normalize_db_config, test_postgres

    cfg = await _resolve_db_cfg(body, db)
    cfg = normalize_db_config(cfg)
    if cfg["engine"] == "sqlite":
        return {"ok": True, "message": "Выбран SQLite (локальный файл data/platform.db)"}
    ok, message = await test_postgres(cfg)
    return {"ok": ok, "message": message}


@app.post("/database/create")
async def database_create(body: DatabaseActionBody, db: AsyncSession = Depends(get_db)):
    """Создать БД на сервере PostgreSQL и опционально схему таблиц."""
    from platform_core.db_admin import (
        build_async_url,
        create_postgres_database,
        ensure_schema_on_url,
        merge_password,
        normalize_db_config,
        public_db_config,
    )

    cfg = await _resolve_db_cfg(body, db)
    cfg = normalize_db_config(cfg)
    if cfg["engine"] != "postgresql":
        raise HTTPException(400, "Создание базы доступно только для PostgreSQL")

    ok, message = await create_postgres_database(cfg)
    if not ok:
        raise HTTPException(400, message)

    schema_msg = None
    if body.init_schema:
        ok_s, schema_msg = await ensure_schema_on_url(build_async_url(cfg))
        if not ok_s:
            raise HTTPException(400, f"{message}. Схема: {schema_msg}")

    # сохранить параметры (пароль) в settings
    s = await db.get(Setting, "database")
    if not s:
        s = Setting(key="database", value=cfg)
        db.add(s)
    else:
        s.value = merge_password(cfg, s.value if isinstance(s.value, dict) else {})
    await db.commit()

    return {
        "ok": True,
        "message": message,
        "schema": schema_msg,
        "database": public_db_config(cfg),
        "async_url_hint": build_async_url({**cfg, "password": "***"}),
    }


@app.post("/audit")
async def create_audit(body: AuditCreate, db: AsyncSession = Depends(get_db)):
    settings = get_settings()
    entry = AuditLog(
        user_id=body.user_id,
        case_id=body.case_id,
        document_id=body.document_id,
        action=body.action,
        processor_id=body.processor_id,
        model_name=body.model_name,
        prompt_version_id=body.prompt_version_id,
        request_hash=body.request_hash,
        response_hash=body.response_hash,
        request_text=body.request_text if settings.audit_store_full_text else None,
        response_text=body.response_text if settings.audit_store_full_text else None,
        meta=body.meta,
    )
    db.add(entry)
    await db.commit()
    return {"id": entry.id}


@app.get("/audit")
async def list_audit(limit: int = 100, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit))
    rows = result.scalars().all()
    return [
        {
            "id": r.id,
            "action": r.action,
            "case_id": r.case_id,
            "processor_id": r.processor_id,
            "model_name": r.model_name,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


@app.get("/prompts")
async def list_prompts(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(PromptVersion).order_by(PromptVersion.created_at.desc()))
    return [
        {
            "id": p.id,
            "processor_id": p.processor_id,
            "version": p.version,
            "is_active": p.is_active,
        }
        for p in result.scalars()
    ]


@app.post("/prompts")
async def create_prompt(body: dict, db: AsyncSession = Depends(get_db)):
    p = PromptVersion(
        processor_id=body["processor_id"],
        version=body.get("version", "v1"),
        text=body["text"],
        is_active=body.get("is_active", False),
    )
    if p.is_active:
        active = await db.execute(
            select(PromptVersion).where(PromptVersion.processor_id == p.processor_id, PromptVersion.is_active == True)
        )
        for old in active.scalars():
            old.is_active = False
    db.add(p)
    await db.commit()
    return {"id": p.id}


@app.post("/findings/bulk")
async def bulk_findings(body: dict, db: AsyncSession = Depends(get_db)):
    items = body.get("findings", [])
    for item in items:
        f = Finding(
            case_id=item["case_id"],
            document_id=item.get("document_id"),
            kind=item["kind"],
            span_start=item.get("span_start"),
            span_end=item.get("span_end"),
            payload=item.get("payload", {}),
            confidence=item.get("confidence"),
        )
        db.add(f)
    await db.commit()
    return {"count": len(items)}
