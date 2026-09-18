# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, Optional

import httpx
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from platform_core.auth_jwt import user_from_authorization
from platform_core.config import get_settings
from platform_core.runtime_config import finalize_pipeline_config

app = FastAPI(title="Контент Дозор — Gateway", version="0.1.0")
settings = get_settings()

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def proxy_request(method: str, base: str, path: str, **kwargs) -> httpx.Response:
    url = f"{base.rstrip('/')}{path}"
    async with httpx.AsyncClient(timeout=600.0) as client:
        return await client.request(method, url, **kwargs)


def require_user(authorization: Optional[str] = Header(None)) -> Dict[str, Any]:
    user = user_from_authorization(authorization)
    if not user:
        raise HTTPException(401, "Требуется авторизация")
    return user


def optional_user(authorization: Optional[str] = Header(None)) -> Optional[Dict[str, Any]]:
    return user_from_authorization(authorization)


@app.get("/health")
async def health():
    checks = {}
    for name, url in [
        ("auth", settings.auth_service_url),
        ("cases", settings.cases_service_url),
        ("parsers", settings.parsers_service_url),
        ("llm", settings.llm_service_url),
        ("reports", settings.reports_service_url),
    ]:
        try:
            r = await proxy_request("GET", url, "/health")
            checks[name] = r.json()
        except Exception as exc:
            checks[name] = {"status": "error", "error": str(exc)}
    return {"status": "ok", "service": "gateway", "downstream": checks}


# --- Auth ---
@app.post("/api/v1/auth/token")
async def auth_token(request: Request):
    """Принимает JSON или application/x-www-form-urlencoded."""
    username = ""
    password = ""
    ctype = (request.headers.get("content-type") or "").lower()
    if "application/json" in ctype:
        data = await request.json()
        if not isinstance(data, dict):
            raise HTTPException(422, "Ожидается JSON-объект {username, password}")
        username = str(data.get("username") or data.get("email") or "")
        password = str(data.get("password") or "")
    else:
        form = await request.form()
        username = str(form.get("username") or form.get("email") or "")
        password = str(form.get("password") or "")
    if not username or not password:
        raise HTTPException(422, "Нужны username и password")
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(
            f"{settings.auth_service_url}/token",
            data={"username": username, "password": password},
        )
    if r.status_code >= 400:
        raise HTTPException(r.status_code, r.text)
    return r.json()


@app.post("/api/v1/auth/register")
async def auth_register(body: dict):
    r = await proxy_request("POST", settings.auth_service_url, "/register", json=body)
    if r.status_code >= 400:
        raise HTTPException(r.status_code, r.text)
    return r.json()


@app.get("/api/v1/auth/me")
async def auth_me(authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(401, "Требуется авторизация")
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(
            f"{settings.auth_service_url}/me",
            headers={"Authorization": authorization},
        )
    if r.status_code >= 400:
        raise HTTPException(r.status_code, r.text)
    return r.json()


@app.get("/api/v1/auth/users")
async def auth_users(authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(401, "Требуется авторизация")
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(
            f"{settings.auth_service_url}/users",
            headers={"Authorization": authorization},
        )
    if r.status_code >= 400:
        raise HTTPException(r.status_code, r.text)
    return r.json()


# --- Cases ---
@app.get("/api/v1/cases")
async def list_cases(user: Dict[str, Any] = Depends(require_user)):
    params = {"role": user["role"], "created_by": user["id"]}
    r = await proxy_request("GET", settings.cases_service_url, "/cases", params=params)
    return r.json()


@app.post("/api/v1/cases")
async def create_case(body: dict, user: Dict[str, Any] = Depends(require_user)):
    payload = {**body, "created_by": user["id"]}
    r = await proxy_request("POST", settings.cases_service_url, "/cases", json=payload)
    return r.json()


@app.get("/api/v1/cases/{case_id}")
async def get_case(case_id: str, user: Dict[str, Any] = Depends(require_user)):
    params = {"role": user["role"], "created_by": user["id"]}
    r = await proxy_request("GET", settings.cases_service_url, f"/cases/{case_id}", params=params)
    if r.status_code >= 400:
        raise HTTPException(r.status_code, r.text)
    return r.json()


@app.patch("/api/v1/cases/{case_id}")
async def patch_case(case_id: str, body: dict, user: Dict[str, Any] = Depends(require_user)):
    # проверка доступа через get
    await get_case(case_id, user)
    r = await proxy_request("PATCH", settings.cases_service_url, f"/cases/{case_id}", json=body)
    if r.status_code >= 400:
        raise HTTPException(r.status_code, r.text)
    return r.json()


@app.delete("/api/v1/cases/{case_id}")
async def delete_case(case_id: str, user: Dict[str, Any] = Depends(require_user)):
    await get_case(case_id, user)
    r = await proxy_request("DELETE", settings.cases_service_url, f"/cases/{case_id}")
    if r.status_code >= 400:
        raise HTTPException(r.status_code, r.text)
    try:
        return r.json()
    except Exception:
        return {"ok": True, "id": case_id}


@app.get("/api/v1/cases/{case_id}/stats")
async def get_case_stats(case_id: str, user: Dict[str, Any] = Depends(require_user)):
    await get_case(case_id, user)
    r = await proxy_request("GET", settings.cases_service_url, f"/cases/{case_id}/stats")
    if r.status_code >= 400:
        raise HTTPException(r.status_code, r.text)
    return r.json()


async def _enqueue_analyze(doc: dict, case_id: str, analysis_mode: str) -> dict:
    try:
        from celery import Celery
        celery = Celery(broker=settings.redis_url, backend=settings.redis_url)
        cfg_r = await proxy_request("GET", settings.cases_service_url, "/settings")
        platform_settings = cfg_r.json() if cfg_r.status_code == 200 else {}
        pipeline_config = finalize_pipeline_config(
            {
                "analysis_mode": analysis_mode,
                "source_type": doc.get("source_type") or "docx",
            },
            platform_settings,
        )
        job_r = await proxy_request("POST", settings.cases_service_url, "/jobs", json={
            "case_id": case_id,
            "document_id": doc["document_id"],
            "job_type": "analyze",
        })
        job_body = job_r.json() if job_r.status_code == 200 else {}
        job_id = job_body.get("id")
        task = celery.send_task(
            "analyze_document",
            kwargs={
                "case_id": case_id,
                "document_id": doc["document_id"],
                "doc_path": doc["path"],
                "pipeline_config": pipeline_config,
                "job_id": job_id,
                "source_type": doc.get("source_type") or "docx",
                "source_url": doc.get("source_url"),
                "include_comments": doc.get("include_comments", True),
            },
        )
        if job_id:
            mode_label = "поверхностный" if pipeline_config.get("analysis_mode") == "shallow" else "глубокий"
            await proxy_request("PATCH", settings.cases_service_url, f"/jobs/{job_id}", json={
                "celery_task_id": task.id,
                "status": "pending",
                "progress": 1,
                "detail": f"В очереди · {mode_label}",
            })
        doc["job"] = {**job_body, "celery_task_id": task.id, "analysis_mode": pipeline_config.get("analysis_mode")}
        doc["task_id"] = task.id
        doc["analysis_mode"] = pipeline_config.get("analysis_mode")
    except Exception as exc:
        doc["queue_error"] = str(exc)
    return doc


@app.get("/api/v1/ingest/sources")
async def ingest_sources(user: Dict[str, Any] = Depends(require_user)):
    r = await proxy_request("GET", settings.cases_service_url, "/ingest/sources")
    if r.status_code >= 400:
        from platform_core.ingest_sources import list_source_types, probe_internet
        return {"items": list_source_types(), "online": probe_internet()}
    return r.json()


@app.get("/api/v1/ingest/connectivity")
async def ingest_connectivity(user: Dict[str, Any] = Depends(require_user)):
    r = await proxy_request("GET", settings.cases_service_url, "/ingest/connectivity")
    if r.status_code >= 400:
        from platform_core.ingest_sources import probe_internet
        return {"online": probe_internet()}
    return r.json()


@app.post("/api/v1/cases/{case_id}/ingest")
async def ingest_source(
    case_id: str,
    source_type: str = Form(...),
    analysis_mode: str = Form("deep"),
    url: Optional[str] = Form(None),
    text: Optional[str] = Form(None),
    include_comments: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    user: Dict[str, Any] = Depends(require_user),
):
    await get_case(case_id, user)
    data = {
        "source_type": source_type,
        "url": url or "",
        "text": text or "",
        "include_comments": include_comments if include_comments is not None else "true",
    }
    files = None
    if file is not None and (file.filename or "").strip():
        content = await file.read()
        files = {"file": (file.filename, content, file.content_type or "application/octet-stream")}
    kwargs: Dict[str, Any] = {"data": data}
    if files:
        kwargs["files"] = files
    r = await proxy_request(
        "POST",
        settings.cases_service_url,
        f"/cases/{case_id}/ingest",
        **kwargs,
    )
    if r.status_code >= 400:
        raise HTTPException(r.status_code, r.text)
    doc = r.json()
    return await _enqueue_analyze(doc, case_id, analysis_mode)


@app.post("/api/v1/cases/{case_id}/documents")
async def upload_document(
    case_id: str,
    file: UploadFile = File(...),
    analysis_mode: str = Form("deep"),
    user: Dict[str, Any] = Depends(require_user),
):
    await get_case(case_id, user)
    content = await file.read()
    files = {"file": (file.filename, content, file.content_type or "application/octet-stream")}
    r = await proxy_request(
        "POST",
        settings.cases_service_url,
        f"/cases/{case_id}/documents",
        files=files,
    )
    if r.status_code >= 400:
        raise HTTPException(r.status_code, r.text)
    doc = r.json()
    doc.setdefault("source_type", "docx")
    return await _enqueue_analyze(doc, case_id, analysis_mode)


# --- Analyze ---
@app.post("/api/v1/analyze/text")
async def analyze_text(body: dict, user: Dict[str, Any] = Depends(require_user)):
    r = await proxy_request("POST", settings.llm_service_url, "/analyze/text", json=body)
    return r.json()


@app.post("/api/v1/pipeline/two-level")
async def two_level(body: dict, user: Dict[str, Any] = Depends(require_user)):
    r = await proxy_request("POST", settings.llm_service_url, "/pipeline/two-level", json=body)
    return r.json()


# --- Parsers ---
@app.get("/api/v1/parsers")
async def parsers_list(user: Dict[str, Any] = Depends(require_user)):
    r = await proxy_request("GET", settings.parsers_service_url, "/parsers")
    return r.json()


@app.post("/api/v1/parsers/run")
async def parsers_run(body: dict, user: Dict[str, Any] = Depends(require_user)):
    try:
        from celery import Celery
        celery = Celery(broker=settings.redis_url, backend=settings.redis_url)
        task = celery.send_task("run_parser", kwargs=body)
        return {"task_id": task.id, "status": "queued"}
    except Exception:
        r = await proxy_request("POST", settings.parsers_service_url, "/parsers/run", json=body)
        return r.json()


# --- Settings ---
@app.get("/api/v1/settings")
async def get_settings_api(user: Dict[str, Any] = Depends(require_user)):
    r = await proxy_request("GET", settings.cases_service_url, "/settings")
    return r.json()


@app.put("/api/v1/settings/{key}")
async def put_settings(key: str, body: dict, user: Dict[str, Any] = Depends(require_user)):
    # Подключение к БД могут сохранять все; остальные ключи — только админ
    if key != "database" and user.get("role") != "admin":
        raise HTTPException(403, "Настройки доступны только администратору")
    if key == "ui" and user.get("role") != "admin":
        raise HTTPException(403, "Настройки интерфейса доступны только администратору")
    r = await proxy_request("PUT", settings.cases_service_url, f"/settings/{key}", json=body)
    return r.json()


@app.post("/api/v1/database/test")
async def database_test(body: dict, user: Dict[str, Any] = Depends(require_user)):
    r = await proxy_request("POST", settings.cases_service_url, "/database/test", json=body)
    if r.status_code >= 400:
        raise HTTPException(r.status_code, r.text)
    return r.json()


@app.post("/api/v1/database/create")
async def database_create(body: dict, user: Dict[str, Any] = Depends(require_user)):
    if user.get("role") != "admin":
        raise HTTPException(403, "Создавать базу данных может только администратор")
    r = await proxy_request("POST", settings.cases_service_url, "/database/create", json=body)
    if r.status_code >= 400:
        raise HTTPException(r.status_code, r.text)
    return r.json()


@app.get("/api/v1/audit")
async def audit(limit: int = 100, user: Dict[str, Any] = Depends(require_user)):
    if user.get("role") != "admin":
        raise HTTPException(403, "Аудит доступен только администратору")
    r = await proxy_request("GET", settings.cases_service_url, f"/audit?limit={limit}")
    return r.json()


@app.get("/api/v1/plugins")
async def plugins(user: Dict[str, Any] = Depends(require_user)):
    r = await proxy_request("GET", settings.llm_service_url, "/plugins")
    return r.json()


@app.get("/api/v1/reports/{case_id}/html")
async def report_html(case_id: str, user: Dict[str, Any] = Depends(require_user)):
    from fastapi.responses import HTMLResponse
    await get_case(case_id, user)
    r = await proxy_request("GET", settings.reports_service_url, f"/reports/{case_id}/html")
    if r.status_code >= 400:
        raise HTTPException(r.status_code, r.text or "Ошибка сервиса отчётов")
    return HTMLResponse(content=r.text, status_code=200, media_type="text/html; charset=utf-8")


@app.get("/api/v1/jobs/{job_id}")
async def get_job(job_id: str, user: Dict[str, Any] = Depends(require_user)):
    r = await proxy_request("GET", settings.cases_service_url, f"/jobs/{job_id}")
    return r.json()


@app.websocket("/ws/jobs/{task_id}")
async def ws_job(websocket: WebSocket, task_id: str):
    await websocket.accept()
    try:
        from celery.result import AsyncResult
        from services.worker.app.tasks import celery_app
        result = AsyncResult(task_id, app=celery_app)
        while True:
            state = result.state
            meta = result.info if isinstance(result.info, dict) else {"detail": str(result.info)}
            progress = int(meta.get("progress", 0)) if isinstance(meta, dict) else 0
            step = meta.get("step", "") if isinstance(meta, dict) else ""
            await websocket.send_json({
                "state": state,
                "progress": progress,
                "step": step,
                "meta": meta,
            })
            if state in ("SUCCESS", "FAILURE"):
                break
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        return
    except Exception as exc:
        await websocket.send_json({"state": "ERROR", "error": str(exc)})
    await websocket.close()
