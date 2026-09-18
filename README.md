# Оболочка платформы

Модели GGUF и CSV-реестры подключаются локально (`/GUF`, `analysis_platform/data/blacklist`).

## Quick start (Windows, local)

```
.\start_platform.ps1
```

Логи: `analysis_platform/data/logs/`
## Quick start (Docker)

```powershell
cd analysis_platform
copy .env.example .env
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

Frontend: http://localhost:5173  
API Gateway: http://localhost:8000/docs

## Services

| Service | Port |
|---------|------|
| gateway | 8000 |
| auth | 8001 |
| cases | 8002 |
| parsers | 8003 |
| llm | 8004 |
| reports | 8005 |

## Local without Docker

```powershell
pip install -r requirements.txt
$env:PYTHONPATH="packages;services/cases/app;services/auth/app"
python -m uvicorn services.gateway.app.main:app --reload --port 8000
```

LLM (llama.cpp): GGUF в `F:\DIPLOM_GGUF` (основное хранилище). Копия extremism: `llama_classific/llama_train/output_qwen25_ACTUAL_v2_instr/run3/gguf/`. Скрипт `scripts/start_llama_cpp.ps1`.
Для 24+ GB VRAM: `LLAMA_CPP_GPU_MODE=multi` и порты 8081–8083.
Для Ollama (опционально): `LLM_BACKEND=ollama` и `llama_classific/llama_train/run_ollama_*.ps1`.
