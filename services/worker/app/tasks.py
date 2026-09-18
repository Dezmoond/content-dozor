# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from celery import Celery

_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_ROOT / "packages"))
sys.path.insert(0, str(_ROOT.parent / "llama_classific" / "llama_train"))

from platform_core.config import get_settings
from platform_core.job_progress import report_job_progress
from platform_core.runtime_config import finalize_pipeline_config

settings = get_settings()
celery_app = Celery("worker", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.task_track_started = True
celery_app.conf.task_serializer = "json"
celery_app.conf.result_serializer = "json"
celery_app.conf.result_extended = True
celery_app.conf.task_store_errors_even_if_ignored = True


def _fmt_ms(ms: float) -> str:
    if ms < 1000:
        return f"{ms:.0f} мс"
    sec = ms / 1000.0
    if sec < 60:
        return f"{sec:.1f} с"
    return f"{int(sec // 60)} мин {sec % 60:.0f} с"


def _patch_job(job_id: str, **fields) -> None:
    if not job_id:
        return
    try:
        with httpx.Client(base_url=settings.cases_service_url, timeout=30.0) as c:
            c.patch(f"/jobs/{job_id}", json=fields)
    except Exception:
        pass


def _patch_case(case_id: str, **fields) -> None:
    if not case_id:
        return
    try:
        with httpx.Client(base_url=settings.cases_service_url, timeout=30.0) as c:
            c.patch(f"/cases/{case_id}", json=fields)
    except Exception:
        pass


@celery_app.task(bind=True, name="analyze_document")
def analyze_document_task(
    self,
    case_id: str,
    document_id: str,
    doc_path: str,
    pipeline_config: dict | None = None,
    job_id: str | None = None,
    source_type: str = "docx",
    source_url: str | None = None,
    include_comments: bool = True,
):
    run_id = None
    job_db_id = job_id
    started_at = time.perf_counter()

    try:
        with httpx.Client(base_url=settings.cases_service_url, timeout=120.0) as c:
            if not job_db_id:
                job = c.post("/jobs", json={
                    "case_id": case_id,
                    "document_id": document_id,
                    "job_type": "analyze",
                    "celery_task_id": self.request.id,
                }).json()
                job_db_id = job["id"]
            else:
                c.patch(f"/jobs/{job_db_id}", json={
                    "status": "running",
                    "progress": 2,
                    "detail": "Постановка в очередь",
                    "celery_task_id": self.request.id,
                })

        runtime_config = dict(pipeline_config or {})
        runtime_config["job_id"] = job_db_id
        with httpx.Client(base_url=settings.cases_service_url, timeout=30.0) as cfg_client:
            try:
                platform_settings = cfg_client.get("/settings").json()
                # Актуальные Methods/Модели на момент запуска (не снимок при загрузке)
                runtime_config = finalize_pipeline_config(runtime_config, platform_settings)
                runtime_config["job_id"] = job_db_id
            except Exception:
                pass

        with httpx.Client(base_url=settings.cases_service_url, timeout=120.0) as c:
            run = c.post("/pipeline-runs", json={
                "case_id": case_id,
                "document_id": document_id,
                "status": "running",
                "pipeline_config": {
                    "analysis_mode": runtime_config.get("analysis_mode", "deep"),
                    "source_type": source_type or "docx",
                    "enabled_steps": runtime_config.get("enabled_steps"),
                    "chunk_size": runtime_config.get("chunk_size"),
                    "extremism_model": runtime_config.get("extremism_model"),
                    "entities_model": runtime_config.get("entities_model"),
                    "validation_model": runtime_config.get("validation_model"),
                    "temperature": runtime_config.get("temperature"),
                    "max_tokens": runtime_config.get("max_tokens"),
                },
            }).json()
            run_id = run["id"]

        report_job_progress(job_db_id, 5, "queue", status="running")
        self.update_state(state="PROGRESS", meta={"progress": 5, "step": "queue"})

        self.update_state(state="PROGRESS", meta={"progress": 10, "step": "llm"})
        with httpx.Client(base_url=settings.llm_service_url, timeout=600.0) as llm:
            resp = llm.post("/analyze/source", json={
                "source_type": source_type or "docx",
                "source_path": doc_path,
                "source_url": source_url,
                "include_comments": include_comments,
                "case_id": case_id,
                "document_id": document_id,
                "job_id": job_db_id,
                "pipeline_config": runtime_config,
            })
            if resp.status_code >= 400:
                err_text = resp.text[:500]
                raise RuntimeError(f"LLM-сервис: {err_text}")
            data = resp.json()

        artifacts = data.get("artifacts") or {}
        result = data.get("result") or {}
        steps_log = data.get("steps_log") or []
        timing = artifacts.get("timing") or {}
        wall_ms = (time.perf_counter() - started_at) * 1000
        if timing:
            timing = {**timing, "worker_total_ms": round(wall_ms, 1), "worker_total_human": _fmt_ms(wall_ms)}
            artifacts["timing"] = timing

        findings = []
        # Поверхностный 4-классовый анализ
        shallow = artifacts.get("shallow_analysis") or {}
        shallow_model = shallow.get("model")
        for ph in shallow.get("phrases") or []:
            payload = dict(ph) if isinstance(ph, dict) else {"text": ph}
            payload["processor"] = "qwen_shallow"
            payload["tool"] = "Qwen Shallow (4 класса)"
            if shallow_model:
                payload["model"] = shallow_model
            conf = payload.get("confidence")
            try:
                conf_f = float(conf) if conf is not None else None
            except (TypeError, ValueError):
                conf_f = None
            if conf_f is not None:
                payload["confidence"] = int(round(conf_f))
            findings.append({
                "case_id": case_id,
                "document_id": document_id,
                "kind": "shallow",
                "payload": payload,
                "confidence": (conf_f / 100.0) if conf_f is not None else None,
            })

        ext = artifacts.get("extremism") or {}
        ext_model = None
        for a in artifacts.get("audit") or []:
            if a.get("processor") == "qwen_extremism":
                ext_model = a.get("model")
                break
        for ph in ext.get("dangerous_phrases") or []:
            payload = dict(ph) if isinstance(ph, dict) else {"text": ph}
            payload["processor"] = "qwen_extremism"
            payload["tool"] = "Qwen Extremism (LLM)"
            if ext_model:
                payload["model"] = ext_model
            conf = payload.get("validation_confidence", payload.get("confidence"))
            try:
                conf_f = float(conf) if conf is not None else None
            except (TypeError, ValueError):
                conf_f = None
            if conf_f is not None:
                payload["confidence"] = int(round(conf_f))
            findings.append({
                "case_id": case_id,
                "document_id": document_id,
                "kind": "danger",
                "payload": payload,
                "confidence": (conf_f / 100.0) if conf_f is not None else None,
            })
        for h in artifacts.get("registry_hits") or []:
            payload = dict(h) if isinstance(h, dict) else {"match": h}
            payload["processor"] = "registry_enrich"
            title = payload.get("source_title") or payload.get("source") or ""
            row = payload.get("row")
            tool = title or "Реестр (CSV)"
            if row is not None:
                tool = f"{tool}, строка {row}"
            payload["tool"] = tool
            findings.append({
                "case_id": case_id,
                "document_id": document_id,
                "kind": "registry",
                "payload": payload,
                "confidence": payload.get("score") if isinstance(payload.get("score"), (int, float)) else None,
            })
        for hit in artifacts.get("blocklist_phrases") or []:
            payload = dict(hit) if isinstance(hit, dict) else {"text": hit}
            payload["processor"] = "blocklist_lexicon"
            payload["tool"] = "Запретный лексикон (WER)"
            findings.append({
                "case_id": case_id,
                "document_id": document_id,
                "kind": "blocklist",
                "payload": payload,
                "confidence": payload.get("score") if isinstance(payload.get("score"), (int, float)) else None,
            })
        # сущности (для наглядности — кто извлёк)
        ents = artifacts.get("entities") or {}
        if isinstance(ents, dict):
            ent_model = None
            for a in artifacts.get("audit") or []:
                if a.get("processor") == "qwen_entities":
                    ent_model = a.get("model")
                    break
            for key, label in (
                ("persons", "person"),
                ("organizations", "organization"),
                ("titles", "title"),
                ("urls", "url"),
            ):
                for item in ents.get(key) or []:
                    payload = dict(item) if isinstance(item, dict) else {"text": item}
                    payload["processor"] = "qwen_entities"
                    payload["tool"] = "Qwen Entities (LLM)"
                    payload["entity_kind"] = label
                    if ent_model:
                        payload["model"] = ent_model
                    findings.append({
                        "case_id": case_id,
                        "document_id": document_id,
                        "kind": "entity",
                        "payload": payload,
                    })
        for item in artifacts.get("rubert_entities") or []:
            if not isinstance(item, dict):
                continue
            payload = dict(item)
            payload["processor"] = "rubert_entities"
            payload["tool"] = "RuBERT Entities"
            label = str(payload.get("label") or "")
            if label in ("fio", "person"):
                payload["entity_kind"] = "person"
            elif label == "organization":
                payload["entity_kind"] = "organization"
            elif label == "title":
                payload["entity_kind"] = "title"
            elif label == "url":
                payload["entity_kind"] = "url"
            conf = payload.get("score")
            findings.append({
                "case_id": case_id,
                "document_id": document_id,
                "kind": "entity",
                "payload": payload,
                "confidence": conf if isinstance(conf, (int, float)) else None,
            })

        with httpx.Client(base_url=settings.cases_service_url, timeout=120.0) as c:
            if run_id:
                c.patch(f"/pipeline-runs/{run_id}", json={
                    "status": "success",
                    "steps_log": steps_log,
                    "result": {"artifacts": artifacts, "result": result, "timing": timing},
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                })
            _patch_job(job_db_id, status="success", progress=100, detail="Готово", result={
                "artifacts": artifacts,
                "timing": timing,
                "steps_log": steps_log,
            })
            _patch_case(case_id, status="review")
            if findings:
                c.post("/findings/bulk", json={"findings": findings})
            for audit in artifacts.get("audit") or []:
                c.post("/audit", json={
                    "case_id": case_id,
                    "document_id": document_id,
                    "action": "llm_inference",
                    "processor_id": audit.get("processor"),
                    "model_name": audit.get("model"),
                    "request_hash": audit.get("hash"),
                    "response_hash": audit.get("hash"),
                })

        self.update_state(state="SUCCESS", meta={"progress": 100, "step": "done"})
        return {"case_id": case_id, "document_id": document_id, "artifacts": artifacts, "job_id": job_db_id}

    except Exception as exc:
        err = str(exc)[:500]
        if job_db_id:
            _patch_job(job_db_id, status="failed", progress=0, detail=err)
        _patch_case(case_id, status="failed")
        if run_id:
            try:
                with httpx.Client(base_url=settings.cases_service_url, timeout=30.0) as c:
                    c.patch(f"/pipeline-runs/{run_id}", json={"status": "failed", "result": {"error": err}})
            except Exception:
                pass
        # Не пробрасываем исключение — иначе Celery worker на Windows падает
        self.update_state(state="FAILURE", meta={"progress": 0, "error": err, "exc_type": type(exc).__name__})
        return {"status": "failed", "error": err, "job_id": job_db_id}


@celery_app.task(name="run_parser")
def run_parser_task(parser_id: str, output_dir: str = ""):
    """Пустой output_dir → parsers service пишет в analysis_platform/data/parser_runs и применяет к blacklist."""
    payload = {"parser_id": parser_id}
    if output_dir:
        payload["output_dir"] = output_dir
    with httpx.Client(base_url=settings.parsers_service_url, timeout=3700.0) as p:
        resp = p.post("/parsers/run", json=payload)
        return resp.json()
