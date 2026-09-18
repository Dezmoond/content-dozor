# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import List


class Settings:
    database_url: str
    redis_url: str
    llm_backend: str
    ollama_host: str
    ollama_extremism_model: str
    ollama_entities_model: str
    ollama_validation_model: str
    llama_cpp_extremism_url: str
    llama_cpp_entities_url: str
    llama_cpp_validation_url: str
    llama_cpp_gguf_dir: str
    llama_cpp_ctx: int
    llama_cpp_ngl: int
    llama_cpp_gpu_mode: str
    diplom_root: str
    blacklist_dir: str
    upload_dir: str
    storage_dir: str
    chunk_size: int
    chunk_overlap: int
    jwt_secret: str
    jwt_algorithm: str
    jwt_expire_minutes: int
    auth_service_url: str
    cases_service_url: str
    parsers_service_url: str
    llm_service_url: str
    reports_service_url: str
    cors_origins: List[str]
    audit_store_full_text: bool

    def __init__(self) -> None:
        self.database_url = os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///./data/platform.db")
        self.redis_url = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")
        self.llm_backend = os.environ.get("LLM_BACKEND", "llamacpp").lower()
        self.ollama_host = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
        self.ollama_extremism_model = os.environ.get("OLLAMA_EXTREMISM_MODEL", "qwen-actual-run3-extremism")
        self.ollama_entities_model = os.environ.get("OLLAMA_ENTITIES_MODEL", "qwen-newclass3run")
        self.ollama_validation_model = os.environ.get("OLLAMA_VALIDATION_MODEL", "qwen25-7b-instruct")
        self.llama_cpp_extremism_url = os.environ.get("LLAMA_CPP_EXTREMISM_URL", "http://127.0.0.1:8081")
        self.llama_cpp_entities_url = os.environ.get("LLAMA_CPP_ENTITIES_URL", "http://127.0.0.1:8082")
        self.llama_cpp_validation_url = os.environ.get("LLAMA_CPP_VALIDATION_URL", "http://127.0.0.1:8083")
        self.llama_cpp_gguf_dir = os.environ.get("LLAMA_CPP_GGUF_DIR", "F:/DIPLOM_GGUF")
        self.llama_cpp_ctx = int(os.environ.get("LLAMA_CPP_CTX", "8192"))
        self.llama_cpp_ngl = int(os.environ.get("LLAMA_CPP_NGL", "99"))
        self.llama_cpp_gpu_mode = os.environ.get("LLAMA_CPP_GPU_MODE", "single").lower()
        self.diplom_root = os.environ.get("DIPLOM_ROOT", "E:/CURSOR/DIPLOM")
        self.blacklist_dir = os.environ.get("BLACKLIST_DIR", "")
        self.upload_dir = os.environ.get("UPLOAD_DIR", "./data/uploads")
        self.storage_dir = os.environ.get("STORAGE_DIR", "./data")
        self.chunk_size = int(os.environ.get("CHUNK_SIZE", "300"))
        self.chunk_overlap = int(os.environ.get("CHUNK_OVERLAP", "25"))
        self.jwt_secret = os.environ.get("JWT_SECRET", "change-me-in-production")
        self.jwt_algorithm = os.environ.get("JWT_ALGORITHM", "HS256")
        self.jwt_expire_minutes = int(os.environ.get("JWT_EXPIRE_MINUTES", str(60 * 24)))
        # 127.0.0.1 — не localhost: на Windows localhost часто резолвится в ::1, а uvicorn слушает только IPv4
        self.auth_service_url = os.environ.get("AUTH_SERVICE_URL", "http://127.0.0.1:8001")
        self.cases_service_url = os.environ.get("CASES_SERVICE_URL", "http://127.0.0.1:8002")
        self.parsers_service_url = os.environ.get("PARSERS_SERVICE_URL", "http://127.0.0.1:8003")
        self.llm_service_url = os.environ.get("LLM_SERVICE_URL", "http://127.0.0.1:8004")
        self.reports_service_url = os.environ.get("REPORTS_SERVICE_URL", "http://127.0.0.1:8005")
        raw_cors = os.environ.get("CORS_ORIGINS", '["http://127.0.0.1:5173","http://localhost:5173","http://localhost:3000"]')
        try:
            self.cors_origins = json.loads(raw_cors)
        except json.JSONDecodeError:
            self.cors_origins = ["http://127.0.0.1:5173", "http://localhost:5173"]
        self.audit_store_full_text = os.environ.get("AUDIT_STORE_FULL_TEXT", "false").lower() in ("1", "true", "yes")

    def resolved_blacklist_dir(self) -> str:
        """Рантайм-реестры приложения (не эталон dataset/blacklist)."""
        if self.blacklist_dir:
            return self.blacklist_dir
        return os.path.join(self.diplom_root, "analysis_platform", "data", "blacklist")

    def resolved_parser_runs_dir(self) -> str:
        return os.path.join(self.diplom_root, "analysis_platform", "data", "parser_runs")



@lru_cache
def get_settings() -> Settings:
    return Settings()
