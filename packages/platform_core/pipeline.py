# -*- coding: utf-8 -*-
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from platform_core.context import PipelineContext
from platform_core.plugin import PluginRegistry, get_registry


@dataclass
class PipelineStep:
    id: str
    plugin_id: str
    enabled: bool = True
    condition: Optional[Callable[[PipelineContext], bool]] = None


DEFAULT_PIPELINE_STEPS: List[PipelineStep] = [
    PipelineStep("ingest_docx", "ingest_source"),
    PipelineStep("chunk_text", "chunker"),
    PipelineStep("qwen_entities", "qwen_entities"),
    PipelineStep("qwen_extremism", "qwen_extremism"),
    PipelineStep("qwen_validation", "qwen_validation"),
    PipelineStep("qwen_shallow", "qwen_shallow", enabled=False),
    PipelineStep("rubert_entities", "rubert_entities"),
    PipelineStep("rubert_danger", "rubert_danger", enabled=False),
    PipelineStep("rubert_fio", "rubert_fio"),
    PipelineStep("natasha_entities", "natasha_entities"),
    PipelineStep("registry_enrich", "registry_enrich"),
    PipelineStep("blocklist_lexicon", "blocklist_lexicon"),
    PipelineStep("report_json", "exporter_json"),
]


class Pipeline:
    def __init__(
        self,
        steps: Optional[List[PipelineStep]] = None,
        registry: Optional[PluginRegistry] = None,
    ) -> None:
        self.steps = steps or list(DEFAULT_PIPELINE_STEPS)
        self.registry = registry or get_registry()

    def with_enabled(self, enabled_map: Dict[str, bool]) -> Pipeline:
        for step in self.steps:
            if step.id in enabled_map:
                step.enabled = enabled_map[step.id]
        return self

    async def run(self, ctx: PipelineContext, data: Any = None) -> Any:
        from platform_core.job_progress import report_job_progress
        from platform_core.llama_gpu_manager import get_model_load_log, reset_model_load_log
        from platform_core.timing import build_timing_summary

        reset_model_load_log()
        pipeline_t0 = time.perf_counter()

        enabled_steps = [
            s for s in self.steps
            if s.enabled and (not s.condition or s.condition(ctx))
        ]
        total = len(enabled_steps) or 1
        current = data if data is not None else ctx.text
        done = 0
        job_id = ctx.config.get("job_id")

        for step in self.steps:
            if not step.enabled:
                ctx.log_step(step.id, "skipped")
                continue
            if step.condition and not step.condition(ctx):
                ctx.log_step(step.id, "skipped_condition")
                continue
            plugin = self.registry.get(step.plugin_id)
            if not plugin or not plugin.meta.enabled:
                ctx.log_step(step.id, "plugin_missing", step.plugin_id)
                continue

            if job_id:
                pct = 5 + int((done / total) * 85)
                report_job_progress(job_id, pct, step.id, status="running")

            t0 = time.perf_counter()
            try:
                current = await plugin.process(ctx, current)
                ms = (time.perf_counter() - t0) * 1000
                ctx.log_step(step.id, "ok", duration_ms=ms)
            except Exception as exc:
                ms = (time.perf_counter() - t0) * 1000
                ctx.log_step(step.id, "error", str(exc), duration_ms=ms)
                if job_id:
                    report_job_progress(job_id, 0, step.id, status="failed")
                raise

            done += 1
            if job_id:
                pct = 5 + int((done / total) * 85)
                report_job_progress(job_id, pct, step.id, status="running")

        if job_id:
            report_job_progress(job_id, 95, "finalize", status="running")

        total_ms = (time.perf_counter() - pipeline_t0) * 1000
        timing = build_timing_summary(
            ctx.steps_log,
            total_ms=total_ms,
            model_loads=get_model_load_log(),
            chunk_stats=ctx.artifacts.get("qwen_chunk_stats"),
        )
        ctx.artifacts["timing"] = timing
        ctx.artifacts["result"] = current
        return current
