# -*- coding: utf-8 -*-
"""Поверхностный анализ: 4 класса фраз на validation-Qwen, без сущностей/реестров."""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Dict, List

from platform_core.config import get_settings
from platform_core.context import PipelineContext
from platform_core.llama_gpu_manager import ensure_llama_model
from platform_core.llm_provider import LLMMessage, get_llm_provider, parse_json_response
from platform_core.plugin import Plugin, PluginKind, PluginMeta, register_plugin_class
from platform_plugins.processors.shallow_prompts import (
    CLASS_LABELS_RU,
    SYSTEM_PROMPT,
    VALID_CLASSES,
    user_prompt_for_chunk,
)


def _audit_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _iter_chunks(ctx: PipelineContext) -> List[Dict[str, Any]]:
    chunks = ctx.artifacts.get("chunks") or []
    if chunks:
        return chunks
    text = ctx.text or ""
    if not text:
        return []
    return [{"index": 0, "start": 0, "end": len(text), "text": text}]


def _clamp_conf(v: Any) -> int | None:
    try:
        n = int(round(float(v)))
    except (TypeError, ValueError):
        return None
    return max(0, min(100, n))


def _normalize_phrase(raw: Any, *, chunk_index: int, chunk_start: int) -> Dict[str, Any] | None:
    if isinstance(raw, str) and raw.strip():
        return {
            "text": raw.strip(),
            "class": "negative",
            "class_label": CLASS_LABELS_RU["negative"],
            "confidence": None,
            "reason": "",
            "chunk_index": chunk_index,
            "chunk_start": chunk_start,
        }
    if not isinstance(raw, dict):
        return None
    text = str(raw.get("text") or "").strip()
    if not text:
        return None
    cls = str(raw.get("class") or raw.get("category") or "").strip().lower()
    # русские синонимы на всякий случай
    aliases = {
        "экстремистский": "extremist",
        "extremist": "extremist",
        "extremism": "extremist",
        "опасный": "dangerous",
        "dangerous": "dangerous",
        "провокационный": "provocative",
        "provocative": "provocative",
        "негативный": "negative",
        "negative": "negative",
        "негатив": "negative",
    }
    cls = aliases.get(cls, cls)
    if cls not in VALID_CLASSES:
        return None
    conf = _clamp_conf(raw.get("confidence", raw.get("score")))
    reason = str(raw.get("reason") or raw.get("justification") or "").strip()
    item: Dict[str, Any] = {
        "text": text,
        "class": cls,
        "class_label": CLASS_LABELS_RU[cls],
        "confidence": conf,
        "reason": reason,
        "chunk_index": chunk_index,
        "chunk_start": chunk_start,
    }
    for key in ("start_char", "end_char", "start", "end"):
        if isinstance(raw.get(key), int):
            item[key] = int(raw[key]) + chunk_start
    return item


def _norm_key(text: str) -> str:
    return " ".join((text or "").lower().split())


def dedupe_shallow_phrases(phrases: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Убрать дубли и вложенные короткие цитаты того же класса."""
    items = sorted(
        [p for p in phrases if p.get("text")],
        key=lambda p: (-len(str(p.get("text") or "")), -(p.get("confidence") or 0)),
    )
    kept: List[Dict[str, Any]] = []
    for item in items:
        t = _norm_key(str(item.get("text") or ""))
        cls = item.get("class")
        if not t:
            continue
        if any(
            k.get("class") == cls and t == _norm_key(str(k.get("text") or ""))
            for k in kept
        ):
            continue
        if any(
            k.get("class") == cls
            and t in _norm_key(str(k.get("text") or ""))
            and t != _norm_key(str(k.get("text") or ""))
            for k in kept
        ):
            continue
        kept.append(item)
    return kept


@register_plugin_class
class QwenShallowAnalysisPlugin(Plugin):
    meta = PluginMeta(
        id="qwen_shallow",
        name="Qwen Shallow 4-class",
        kind=PluginKind.PROCESSOR,
        enabled=True,
    )

    async def process(self, ctx: PipelineContext, data: Any) -> Any:
        settings = get_settings()
        model = ctx.config.get("validation_model", settings.ollama_validation_model)
        try:
            temperature = float(ctx.config.get("temperature", 0.2))
        except (TypeError, ValueError):
            temperature = 0.2
        try:
            max_tokens = int(ctx.config.get("max_tokens", 1024))
        except (TypeError, ValueError):
            max_tokens = 1024
        max_tokens = max(max_tokens, 1024)
        chunks = _iter_chunks(ctx)

        await ensure_llama_model("validation")
        provider = get_llm_provider("validation")

        all_phrases: List[Dict[str, Any]] = []
        chunk_timings: List[Dict[str, Any]] = []
        chunk_results: List[Dict[str, Any]] = []
        t_phase = time.perf_counter()

        for chunk in chunks:
            text = chunk.get("text") or ""
            if not text.strip():
                continue
            t0 = time.perf_counter()
            raw = await provider.generate(
                [
                    LLMMessage("system", SYSTEM_PROMPT),
                    LLMMessage("user", user_prompt_for_chunk(text)),
                ],
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            ms = (time.perf_counter() - t0) * 1000
            parsed = parse_json_response(raw)
            phrases_raw = []
            if isinstance(parsed, dict) and not parsed.get("_parse_error"):
                phrases_raw = parsed.get("phrases") or []
            if not isinstance(phrases_raw, list):
                phrases_raw = []

            chunk_index = int(chunk.get("index", 0))
            chunk_start = int(chunk.get("start", 0))
            normalized = []
            for ph in phrases_raw:
                item = _normalize_phrase(ph, chunk_index=chunk_index, chunk_start=chunk_start)
                if item:
                    normalized.append(item)
                    all_phrases.append(item)

            chunk_results.append({
                "chunk_index": chunk_index,
                "chunk_start": chunk_start,
                "phrases": normalized,
                "raw_parse_error": bool(isinstance(parsed, dict) and parsed.get("_parse_error")),
            })
            chunk_timings.append({
                "chunk_index": chunk_index,
                "duration_ms": round(ms, 1),
            })

        phrases = dedupe_shallow_phrases(all_phrases)
        from platform_plugins.processors.text_grounding import ground_phrase_list
        phrases, rejected_hallu = ground_phrase_list(phrases, ctx.text or "", min_len=3)
        by_class: Dict[str, List[Dict[str, Any]]] = {k: [] for k in CLASS_LABELS_RU}
        for p in phrases:
            by_class.setdefault(str(p.get("class")), []).append(p)

        result = {
            "phrases": phrases,
            "by_class": by_class,
            "counts": {k: len(v) for k, v in by_class.items()},
            "model": model,
            "analysis_mode": "shallow",
            "rejected_not_in_text": rejected_hallu,
        }
        ctx.artifacts["shallow_analysis"] = result
        ctx.artifacts["analysis_mode"] = "shallow"
        ctx.artifacts.setdefault("audit", []).append({
            "processor": "qwen_shallow",
            "model": model,
            "hash": _audit_hash(json.dumps(result, ensure_ascii=False)),
        })
        phase_ms = (time.perf_counter() - t_phase) * 1000
        ctx.artifacts.setdefault("qwen_chunk_stats", {})["shallow"] = {
            "chunks_processed": len(chunk_results),
            "chunks_total": len(chunks),
            "inference_ms": round(sum(t["duration_ms"] for t in chunk_timings), 1),
            "phase_ms": round(phase_ms, 1),
            "per_chunk": chunk_timings,
            "phrases_found": len(phrases),
        }
        return data
