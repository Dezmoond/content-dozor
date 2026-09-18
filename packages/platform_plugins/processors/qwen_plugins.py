# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

from platform_core.config import get_settings
from platform_core.context import PipelineContext
from platform_core.llama_gpu_manager import ensure_llama_model
from platform_core.llm_provider import LLMMessage, get_llm_provider, parse_json_response
from platform_core.plugin import Plugin, PluginKind, PluginMeta, register_plugin_class
from platform_plugins.processors.danger_filter import (
    apply_validation_to_extremism,
    filter_dangerous_phrases,
)
from platform_plugins.processors.qwen_chunk_utils import (
    merge_entities_chunk_results,
    merge_extremism_chunk_results,
)

_DIPLOM = Path(__file__).resolve().parents[4]
_LLAMA_TRAIN = _DIPLOM / "llama_classific" / "llama_train"
if str(_LLAMA_TRAIN) not in sys.path:
    sys.path.insert(0, str(_LLAMA_TRAIN))


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


def _gen_params(ctx: PipelineContext, *, default_max_tokens: int = 512) -> Dict[str, Any]:
    """Параметры генерации из настроек пользователя (страница «Модели»)."""
    temp = ctx.config.get("temperature")
    mt = ctx.config.get("max_tokens")
    try:
        temperature = float(temp) if temp is not None else 0.2
    except (TypeError, ValueError):
        temperature = 0.2
    try:
        max_tokens = int(mt) if mt is not None else default_max_tokens
    except (TypeError, ValueError):
        max_tokens = default_max_tokens
    return {"temperature": temperature, "max_tokens": max_tokens}


async def _call_extremism(provider, text: str, model: str, *, temperature: float = 0.2, max_tokens: int = 512) -> dict:
    try:
        from extremism_prompts import SYSTEM, user_text_for_request
    except ImportError:
        SYSTEM = "Ответ только JSON: found_dangerous, dangerous_phrases."
        user_text_for_request = lambda t: f"{t}\n\nОтвет (только JSON):"

    raw = await provider.generate(
        [LLMMessage("system", SYSTEM), LLMMessage("user", user_text_for_request(text))],
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return parse_json_response(raw)


@register_plugin_class
class QwenExtremismPlugin(Plugin):
    meta = PluginMeta(
        id="qwen_extremism",
        name="Qwen Extremism",
        kind=PluginKind.PROCESSOR,
    )

    async def process(self, ctx: PipelineContext, data: Any) -> Any:
        settings = get_settings()
        model = ctx.config.get("extremism_model", settings.ollama_extremism_model)
        gen = _gen_params(ctx, default_max_tokens=512)
        chunks = _iter_chunks(ctx)
        keywords = ("лгбт", "гей", "лесби", "прайд", "meta", "instagram", "facebook")
        full_lower = (ctx.text or "").lower()

        await ensure_llama_model("extremism")
        provider = get_llm_provider("extremism")
        chunk_results: List[Dict[str, Any]] = []
        chunk_timings: List[Dict[str, Any]] = []
        t_phase = time.perf_counter()

        for chunk in chunks:
            text = chunk.get("text") or ""
            triggers = ctx.artifacts.get("entities") or {}
            has_signal = any(triggers.get(k) for k in ("persons", "organizations", "titles", "urls"))
            if not has_signal and not any(k in text.lower() for k in keywords) and not any(k in full_lower for k in keywords):
                continue
            t0 = time.perf_counter()
            parsed = await _call_extremism(
                provider, text, model,
                temperature=gen["temperature"],
                max_tokens=gen["max_tokens"],
            )
            ms = (time.perf_counter() - t0) * 1000
            chunk_results.append({
                "chunk_index": chunk.get("index", 0),
                "chunk_start": chunk.get("start", 0),
                "result": parsed,
            })
            chunk_timings.append({
                "chunk_index": chunk.get("index", 0),
                "duration_ms": round(ms, 1),
            })

        if not chunk_results:
            ctx.artifacts["extremism"] = {"found_dangerous": False, "dangerous_phrases": [], "skipped": True}
        else:
            result = merge_extremism_chunk_results(chunk_results)
            kept, rejected = filter_dangerous_phrases(result.get("dangerous_phrases") or [])
            nested_rej: List[Any] = []
            if kept:
                from platform_plugins.processors.danger_filter import dedupe_nested_dangerous_phrases
                kept, nested_rej = dedupe_nested_dangerous_phrases(kept)
            # Анти-галлюцинация: только фразы, которые есть в документе
            from platform_plugins.processors.text_grounding import ground_phrase_list
            grounded, not_in_text = ground_phrase_list(kept, ctx.text or "", min_len=3)
            kept = grounded
            result["dangerous_phrases"] = kept
            result["found_dangerous"] = bool(kept)
            if rejected:
                result["rejected_dangerous_phrases"] = [
                    {**(p if isinstance(p, dict) else {"text": p}), "reason": "noise_heuristic"}
                    for p in rejected
                ]
            if nested_rej:
                result.setdefault("rejected_dangerous_phrases", []).extend(nested_rej)
            if not_in_text:
                result.setdefault("rejected_dangerous_phrases", []).extend(not_in_text)
            ctx.artifacts["extremism"] = result
            ctx.artifacts.setdefault("audit", []).append(
                {"processor": "qwen_extremism", "model": model, "hash": _audit_hash(json.dumps(result, ensure_ascii=False))}
            )

        phase_ms = (time.perf_counter() - t_phase) * 1000
        ctx.artifacts.setdefault("qwen_chunk_stats", {})["extremism"] = {
            "chunks_processed": len(chunk_results),
            "chunks_total": len(chunks),
            "inference_ms": round(sum(t["duration_ms"] for t in chunk_timings), 1),
            "phase_ms": round(phase_ms, 1),
            "per_chunk": chunk_timings,
        }
        return data


@register_plugin_class
class QwenEntitiesPlugin(Plugin):
    meta = PluginMeta(
        id="qwen_entities",
        name="Qwen Entities",
        kind=PluginKind.PROCESSOR,
    )

    async def process(self, ctx: PipelineContext, data: Any) -> Any:
        settings = get_settings()
        model = ctx.config.get("entities_model", settings.ollama_entities_model)
        gen = _gen_params(ctx, default_max_tokens=768)
        # Промпт как в Modelfile / обучении NEWCLASS3run
        system = (
            "Извлеки сущности из текста и верни JSON с полями: persons, organizations, titles, urls. "
            "Каждое поле — список объектов. Каждый объект содержит: text, start_char, end_char. "
            "start_char и end_char — индексы символов в строке input; end_char эксклюзивный. "
            "Только валидный JSON, без пояснений. Если сущность не найдена — верни пустой список."
        )
        chunks = _iter_chunks(ctx)

        await ensure_llama_model("entities")
        provider = get_llm_provider("entities")
        chunk_results: List[Dict[str, Any]] = []
        chunk_timings: List[Dict[str, Any]] = []
        t_phase = time.perf_counter()

        for chunk in chunks:
            text = chunk.get("text") or ""
            if not text.strip():
                continue
            t0 = time.perf_counter()
            raw = await provider.generate(
                [
                    LLMMessage("system", system),
                    LLMMessage(
                        "user",
                        f"Текст для анализа:\n{text}\n\nОтвет (только JSON, без пояснений):",
                    ),
                ],
                model=model,
                temperature=gen["temperature"],
                max_tokens=gen["max_tokens"],
            )
            ms = (time.perf_counter() - t0) * 1000
            parsed = parse_json_response(raw)
            chunk_results.append({
                "chunk_index": chunk.get("index", 0),
                "chunk_start": chunk.get("start", 0),
                "result": parsed,
            })
            chunk_timings.append({
                "chunk_index": chunk.get("index", 0),
                "duration_ms": round(ms, 1),
            })

        result = merge_entities_chunk_results(chunk_results) if chunk_results else {
            "persons": [], "organizations": [], "titles": [], "urls": [],
        }
        from platform_plugins.processors.text_grounding import ground_entities_typed
        grounded, rej_ents = ground_entities_typed(result, ctx.text or "")
        result = grounded
        if rej_ents:
            ctx.artifacts["rejected_entities"] = rej_ents
        ctx.artifacts["entities"] = result
        ctx.artifacts.setdefault("audit", []).append(
            {"processor": "qwen_entities", "model": model, "hash": _audit_hash(json.dumps(result, ensure_ascii=False))}
        )
        phase_ms = (time.perf_counter() - t_phase) * 1000
        ctx.artifacts.setdefault("qwen_chunk_stats", {})["entities"] = {
            "chunks_processed": len(chunk_results),
            "chunks_total": len(chunks),
            "inference_ms": round(sum(t["duration_ms"] for t in chunk_timings), 1),
            "phase_ms": round(phase_ms, 1),
            "per_chunk": chunk_timings,
        }
        return data


@register_plugin_class
class QwenValidationPlugin(Plugin):
    meta = PluginMeta(
        id="qwen_validation",
        name="Qwen Validation",
        kind=PluginKind.PROCESSOR,
    )

    async def process(self, ctx: PipelineContext, data: Any) -> Any:
        settings = get_settings()
        text = ctx.text
        try:
            from credibility_prompts import SYSTEM, user_text_for_request
            from ollama_credibility_two_step import _apply_validation_flags, compute_erroneous
        except ImportError:
            SYSTEM = "Проверь оскорбления Путина, власти РФ, церкви. JSON only."
            user_text_for_request = lambda t: f"{t}\n\nJSON:"
            _apply_validation_flags = lambda o: o
            compute_erroneous = lambda v, e=None: False

        model = ctx.config.get("validation_model", settings.ollama_validation_model)
        min_conf = int(ctx.config.get("min_danger_confidence", 50))
        gen = _gen_params(ctx, default_max_tokens=1024)
        await ensure_llama_model("validation")
        provider = get_llm_provider("validation")
        t0 = time.perf_counter()
        raw = await provider.generate(
            [LLMMessage("system", SYSTEM), LLMMessage("user", user_text_for_request(text))],
            model=model,
            temperature=gen["temperature"],
            max_tokens=gen["max_tokens"],
        )
        inference_ms = (time.perf_counter() - t0) * 1000
        validation = parse_json_response(raw)
        if "_parse_error" not in validation:
            validation = _apply_validation_flags(validation)
            extremism = ctx.artifacts.get("extremism") or {}
            # Оценка уверенности по каждой опасной фразе
            phrases_for_score = list((extremism.get("dangerous_phrases") or []))
            if phrases_for_score:
                from platform_plugins.processors.danger_filter import (
                    PHRASE_SCORE_SYSTEM,
                    phrase_score_user_prompt,
                )
                t1 = time.perf_counter()
                score_raw = await provider.generate(
                    [
                        LLMMessage("system", PHRASE_SCORE_SYSTEM),
                        LLMMessage("user", phrase_score_user_prompt(text or "", phrases_for_score)),
                    ],
                    model=model,
                    temperature=gen["temperature"],
                    max_tokens=max(gen["max_tokens"], 1024),
                )
                inference_ms += (time.perf_counter() - t1) * 1000
                score_obj = parse_json_response(score_raw)
                scored = score_obj.get("phrases") if isinstance(score_obj, dict) else None
                if isinstance(scored, list):
                    validation["phrase_scores"] = scored

            erroneous = compute_erroneous(validation, extremism)
            cleaned = apply_validation_to_extremism(
                extremism, validation, text or "", min_confidence=min_conf
            )
            if cleaned.get("ошибочное"):
                erroneous = True
            validation["ошибочное"] = erroneous
            validation["min_danger_confidence"] = min_conf
            ctx.artifacts["ошибочное"] = erroneous
            ctx.artifacts["extremism"] = cleaned
            if erroneous:
                validation["cleared_false_positives"] = True
        ctx.artifacts["validation"] = validation
        ctx.artifacts.setdefault("qwen_chunk_stats", {})["validation"] = {
            "chunks_processed": 1,
            "chunks_total": 1,
            "inference_ms": round(inference_ms, 1),
            "phase_ms": round(inference_ms, 1),
        }
        return data
