# Контент Дозор — оболочка платформы анализа

В этом репозитории — **код оболочки** (сервисы, UI, пайплайн).  
Не входят и не должны попадать в git: датасеты, веса моделей, логи, выгрузки реестров, загруженные документы, примеры прогонов.

Модели GGUF и CSV-реестры подключаются локально (`F:/DIPLOM_GGUF`, `analysis_platform/data/blacklist`).

## Quick start (Windows, local)

```powershell
cd E:\CURSOR\DIPLOM\analysis_platform
.\start_platform.ps1
```

Проверка статуса без запуска:

```powershell
.\start_platform.ps1 -StatusOnly
```

Остановка:

```powershell
.\start_platform.ps1 -Stop
```

Скрипт `start_platform.ps1`:
- проверяет Python, pip, npm, Redis, llama.cpp (3 GGUF-сервера)
- устанавливает зависимости (`requirements.txt`, `npm install`)
- поднимает Redis через Docker (если доступен)
- запускает `llama-server` (CUDA, `-ngl 99`) с моделями из `F:\DIPLOM_GGUF`
- режим `single`: одна модель на GPU, переключение по роли (для 16 GB VRAM)
- стартует все микросервисы (8000–8005), Celery worker, frontend
- ждёт `/health` и выводит таблицу готовности

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
