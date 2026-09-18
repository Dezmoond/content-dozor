# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx

from platform_core.config import get_settings
from platform_core.llama_gpu_manager import ensure_llama_model


@dataclass
class LLMMessage:
    role: str
    content: str


class LLMProvider(ABC):
    @abstractmethod
    async def generate(
        self,
        messages: List[LLMMessage],
        *,
        model: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 512,
    ) -> str:
        ...

    async def health(self) -> Dict[str, Any]:
        return {"status": "unknown"}


class LlamaCppProvider(LLMProvider):
    """HTTP-клиент llama.cpp server (OpenAI-совместимый /v1/chat/completions)."""

    def __init__(self, base_url: Optional[str] = None, role: str = "extremism") -> None:
        settings = get_settings()
        self.role = role
        self.base_url = (base_url or settings.llama_cpp_extremism_url).rstrip("/")

    async def generate(
        self,
        messages: List[LLMMessage],
        *,
        model: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 512,
    ) -> str:
        settings = get_settings()
        if settings.llm_backend == "llamacpp" and settings.llama_cpp_gpu_mode == "single":
            await ensure_llama_model(self.role)
        payload = {
            "model": model or "default",
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        async with httpx.AsyncClient(timeout=600.0) as client:
            resp = await client.post(f"{self.base_url}/v1/chat/completions", json=payload)
            if resp.status_code >= 400:
                raise RuntimeError(
                    f"llama.cpp server ({self.base_url}): {resp.status_code} {resp.text[:300]}"
                )
            body = resp.json()
        choices = body.get("choices") or []
        if not choices:
            return ""
        msg = choices[0].get("message") or {}
        return msg.get("content") or ""

    async def health(self) -> Dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(f"{self.base_url}/health")
                resp.raise_for_status()
                data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
                return {"status": "ok", "backend": "llamacpp", "url": self.base_url, "health": data}
        except Exception as exc:
            return {"status": "error", "backend": "llamacpp", "url": self.base_url, "error": str(exc)}


class OllamaProvider(LLMProvider):
    def __init__(self, base_url: Optional[str] = None) -> None:
        settings = get_settings()
        self.base_url = (base_url or settings.ollama_host).rstrip("/")

    async def generate(
        self,
        messages: List[LLMMessage],
        *,
        model: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 512,
    ) -> str:
        settings = get_settings()
        model = model or settings.ollama_extremism_model
        payload = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
                "top_p": 0.9,
            },
        }
        async with httpx.AsyncClient(timeout=600.0) as client:
            resp = await client.post(f"{self.base_url}/api/chat", json=payload)
            if resp.status_code == 404:
                raise RuntimeError(
                    f"Модель Ollama '{model}' не найдена. "
                    f"Выполните: ollama list и загрузите модель."
                )
            resp.raise_for_status()
            body = resp.json()
        return (body.get("message") or {}).get("content") or ""

    async def health(self) -> Dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{self.base_url}/api/tags")
                resp.raise_for_status()
                return {"status": "ok", "backend": "ollama", "models": resp.json()}
        except Exception as exc:
            return {"status": "error", "backend": "ollama", "error": str(exc)}


def get_llm_provider(role: str = "extremism") -> LLMProvider:
    """role: extremism | entities | validation"""
    settings = get_settings()
    if settings.llm_backend == "llamacpp":
        if settings.llama_cpp_gpu_mode == "single":
            return LlamaCppProvider(base_url=settings.llama_cpp_extremism_url, role=role)
        urls = {
            "extremism": settings.llama_cpp_extremism_url,
            "entities": settings.llama_cpp_entities_url,
            "validation": settings.llama_cpp_validation_url,
        }
        return LlamaCppProvider(base_url=urls.get(role, settings.llama_cpp_extremism_url), role=role)
    return OllamaProvider()


def extract_first_json(raw: str) -> str:
    s = raw.strip()
    if "```json" in s:
        start = s.find("```json")
        s = s[start + 7 :]
        end = s.find("```")
        if end != -1:
            s = s[:end]
    start = s.find("{")
    if start == -1:
        return raw
    depth = 0
    for i in range(start, len(s)):
        if s[i] == "{":
            depth += 1
        elif s[i] == "}":
            depth -= 1
            if depth == 0:
                return s[start : i + 1]
    return raw


def parse_json_response(raw: str) -> dict:
    try:
        return json.loads(extract_first_json(raw))
    except json.JSONDecodeError:
        return {"_raw": raw, "_parse_error": True}
