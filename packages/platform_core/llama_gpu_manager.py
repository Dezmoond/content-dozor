# -*- coding: utf-8 -*-
"""Один llama-server на GPU: переключение GGUF по роли (для 16 GB VRAM)."""
from __future__ import annotations

import asyncio
import os
import subprocess
import time
from pathlib import Path
from typing import Optional

import httpx

from platform_core.config import get_settings

_lock = asyncio.Lock()
_current_gguf: Optional[str] = None
_server_proc: Optional[subprocess.Popen] = None
_model_load_log: list[dict] = []


def reset_model_load_log() -> None:
    global _model_load_log
    _model_load_log = []


def get_model_load_log() -> list[dict]:
    return list(_model_load_log)


ROLE_GGUF_FILES = {
    "extremism": "qwen-actual-run3-extremism-q5_k_m.gguf",
    "entities": "qwen-newclass3run-q5_k_m.gguf",
    "validation": "qwen25-7b-instruct-q5_k_m.gguf",
}


def _find_llama_server() -> Path:
    settings = get_settings()
    root = Path(settings.diplom_root)
    base = root / "llama_classific" / "llama_train" / "vendor" / "llama.cpp" / "bin"
    for sub in ("cuda", ""):
        candidate = base / sub / "llama-server.exe" if sub else base / "llama-server.exe"
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        "llama-server.exe не найден. Запустите start_platform.ps1 для загрузки CUDA-сборки."
    )


def _creation_flags() -> int:
    if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
        return subprocess.CREATE_NO_WINDOW
    return 0


def _kill_port(port: int) -> None:
    """Освободить порт: убить любой процесс, слушающий port."""
    if os.name == "nt":
        try:
            out = subprocess.check_output(
                ["netstat", "-ano"],
                text=True,
                errors="ignore",
                creationflags=_creation_flags(),
            )
        except Exception:
            return
        pids: set[int] = set()
        needle = f":{port}"
        for line in out.splitlines():
            if needle not in line or "LISTENING" not in line.upper():
                continue
            parts = line.split()
            if not parts:
                continue
            try:
                pids.add(int(parts[-1]))
            except ValueError:
                continue
        for pid in pids:
            if pid <= 0:
                continue
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/F", "/T"],
                    capture_output=True,
                    creationflags=_creation_flags(),
                )
            except Exception:
                pass
    else:
        try:
            subprocess.run(["fuser", "-k", f"{port}/tcp"], capture_output=True)
        except Exception:
            pass


def _stop_server() -> None:
    global _server_proc, _current_gguf
    if _server_proc is not None and _server_proc.poll() is None:
        try:
            _server_proc.terminate()
            _server_proc.wait(timeout=15)
        except Exception:
            try:
                _server_proc.kill()
                _server_proc.wait(timeout=5)
            except Exception:
                pass
    _server_proc = None
    _current_gguf = None


def _port_free(port: int) -> bool:
    if os.name == "nt":
        try:
            out = subprocess.check_output(
                ["netstat", "-ano"],
                text=True,
                errors="ignore",
                creationflags=_creation_flags(),
            )
        except Exception:
            return True
        needle = f":{port}"
        for line in out.splitlines():
            if needle in line and "LISTENING" in line.upper():
                return False
        return True
    return True


async def _wait_port_free(port: int, timeout_sec: float = 30.0) -> None:
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        if _port_free(port):
            return
        _kill_port(port)
        await asyncio.sleep(0.5)
    raise RuntimeError(f"Порт {port} занят, не удалось освободить")


async def _wait_health(port: int, timeout_sec: float = 300.0) -> None:
    deadline = time.monotonic() + timeout_sec
    url = f"http://127.0.0.1:{port}/health"
    while time.monotonic() < deadline:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    return
        except Exception:
            pass
        await asyncio.sleep(1.5)
    raise RuntimeError(f"llama-server на порту {port} не ответил за {timeout_sec:.0f} с")


async def _loaded_model_name(port: int) -> str:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"http://127.0.0.1:{port}/v1/models")
            if resp.status_code == 200:
                data = resp.json()
                models = data.get("data") or []
                if models:
                    return str(models[0].get("id") or "")
    except Exception:
        pass
    return ""


def _model_matches(loaded: str, gguf_name: str) -> bool:
    if not loaded or not gguf_name:
        return False
    loaded_l = loaded.replace("\\", "/").lower()
    name_l = gguf_name.lower()
    return name_l in loaded_l or loaded_l.endswith(name_l)


async def _wait_model_match(port: int, gguf_name: str, timeout_sec: float = 120.0) -> str:
    deadline = time.monotonic() + timeout_sec
    last = ""
    while time.monotonic() < deadline:
        last = await _loaded_model_name(port)
        if _model_matches(last, gguf_name):
            return last
        await asyncio.sleep(1.0)
    raise RuntimeError(
        f"Ожидалась модель {gguf_name}, на порту {port} загружено: {last or '(пусто)'}"
    )


async def ensure_llama_model(role: str) -> None:
    """Загрузить нужный GGUF на единственный GPU-сервер (порт 8081)."""
    settings = get_settings()
    if settings.llama_cpp_gpu_mode != "single":
        return

    gguf_name = ROLE_GGUF_FILES.get(role)
    if not gguf_name:
        return

    gguf_path = Path(settings.llama_cpp_gguf_dir) / gguf_name
    if not gguf_path.is_file():
        raise FileNotFoundError(f"GGUF не найден: {gguf_path}")

    global _current_gguf, _server_proc, _model_load_log
    port = 8081
    async with _lock:
        # Уже наш процесс с нужной моделью — проверить по /v1/models
        if (
            _current_gguf == gguf_name
            and _server_proc is not None
            and _server_proc.poll() is None
        ):
            loaded = await _loaded_model_name(port)
            if _model_matches(loaded, gguf_name):
                _model_load_log.append({
                    "role": role,
                    "gguf": gguf_name,
                    "duration_ms": 0,
                    "reused": True,
                    "verified": loaded,
                })
                return

        t0 = time.perf_counter()
        _stop_server()
        _kill_port(port)
        await _wait_port_free(port, timeout_sec=45.0)
        await asyncio.sleep(0.5)

        exe = _find_llama_server()
        ngl = settings.llama_cpp_ngl
        args = [
            str(exe),
            "-m",
            str(gguf_path),
            "--port",
            str(port),
            "--host",
            "127.0.0.1",
            "-c",
            str(settings.llama_cpp_ctx),
        ]
        if ngl != 0:
            args.extend(["-ngl", str(ngl)])

        _server_proc = subprocess.Popen(
            args,
            cwd=str(exe.parent),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=_creation_flags(),
        )
        # Дать процессу шанс упасть, если порт всё ещё занят
        await asyncio.sleep(1.0)
        early_code = _server_proc.poll()
        if early_code is not None:
            _server_proc = None
            _current_gguf = None
            raise RuntimeError(
                f"llama-server сразу завершился при загрузке {gguf_name} "
                f"(код {early_code}). Проверьте, что порт {port} свободен."
            )

        await _wait_health(port)
        loaded = await _wait_model_match(port, gguf_name, timeout_sec=180.0)
        if _server_proc.poll() is not None:
            raise RuntimeError(f"llama-server упал после загрузки {gguf_name}")

        _current_gguf = gguf_name
        load_ms = (time.perf_counter() - t0) * 1000
        _model_load_log.append({
            "role": role,
            "gguf": gguf_name,
            "duration_ms": round(load_ms, 1),
            "reused": False,
            "verified": loaded or gguf_name,
        })
