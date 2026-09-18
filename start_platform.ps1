# Запуск платформы analysis_platform (Windows)
#   .\start_platform.ps1
#   .\start_platform.ps1 -StatusOnly
#   .\start_platform.ps1 -Stop
#   .\start_platform.ps1 -SkipFrontend

param(
    [switch]$StatusOnly,
    [switch]$Stop,
    [switch]$SkipFrontend,
    [switch]$SkipLlamaCpp,
    [switch]$SkipOllama,
    [int]$HealthTimeoutSec = 120,
    [string]$PythonExe = ""
)

try {
    if ($env:OS -eq "Windows_NT") { chcp 65001 | Out-Null }
    [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
    $OutputEncoding = [Console]::OutputEncoding
} catch {}

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$DataDir = Join-Path $Root "data"
$PidFile = Join-Path $DataDir "platform_pids.json"
$LogDir = Join-Path $DataDir "logs"

$ServiceNamesRu = @{
    auth    = "авторизация"
    cases   = "кейсы"
    parsers = "парсеры"
    llm     = "LLM"
    reports = "отчёты"
    gateway = "шлюз"
    worker  = "фоновый worker"
    frontend = "интерфейс"
}

function Get-ServiceRuName([string]$Name) {
    if ($ServiceNamesRu.ContainsKey($Name)) { return $ServiceNamesRu[$Name] }
    return $Name
}

function Write-Step([string]$msg) {
    Write-Host "[*] $msg" -ForegroundColor Cyan
}

function Write-Ok([string]$msg) {
    Write-Host "  ОК  $msg" -ForegroundColor Green
}

function Write-Warn([string]$msg) {
    Write-Host "  !!  $msg" -ForegroundColor Yellow
}

function Write-Err([string]$msg) {
    Write-Host "  ОШИБ $msg" -ForegroundColor Red
}

function Resolve-Python {
    if ($PythonExe -and (Test-Path $PythonExe)) { return $PythonExe }
    $candidates = @(
        "C:\Users\xxxde\AppData\Local\Programs\Python\Python310\python.exe",
        "C:\Users\xxxde\AppData\Local\Programs\Python\Python311\python.exe",
        "python",
        "py"
    )
    foreach ($c in $candidates) {
        if ($c -match "\\") {
            if (Test-Path $c) { return $c }
        } else {
            $found = Get-Command $c -ErrorAction SilentlyContinue
            if ($found) { return $found.Source }
        }
    }
    throw "Python не найден. Установите Python 3.10+ и запустите снова."
}

function Test-PortOpen([int]$Port, [int]$Retries = 2) {
    for ($i = 0; $i -le $Retries; $i++) {
        try {
            $t = New-Object Net.Sockets.TcpClient
            $t.Connect("127.0.0.1", $Port)
            $t.Close()
            return $true
        } catch {
            if ($i -lt $Retries) { Start-Sleep -Milliseconds 250 }
        }
    }
    return $false
}

function Invoke-HealthCheck([string]$Url) {
    $py = $script:PyExe
    $out = & $py (Join-Path $Root "scripts\health_check.py") $Url 2>$null
    if ($LASTEXITCODE -ne 0) { return $null }
    try { return $out | ConvertFrom-Json } catch { return $null }
}

function Wait-Health([string]$Name, [string]$Url, [int]$TimeoutSec) {
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        $h = Invoke-HealthCheck $Url
        if ($h -and $h.ok) { return $true }
        Start-Sleep -Milliseconds 800
    }
    return $false
}

function Set-PlatformEnv {
    $DiplomRoot = (Resolve-Path (Join-Path $Root "..")).Path
    $env:PYTHONPATH = "$Root\packages;$Root"
    $env:DATABASE_URL = "sqlite+aiosqlite:///$($DataDir -replace '\\','/')/platform.db"
    $env:DIPLOM_ROOT = $DiplomRoot
    $env:REDIS_URL = "redis://127.0.0.1:6379/0"
    $env:LLM_BACKEND = "llamacpp"
    $env:LLAMA_CPP_EXTREMISM_URL = "http://127.0.0.1:8081"
    $env:LLAMA_CPP_ENTITIES_URL = "http://127.0.0.1:8081"
    $env:LLAMA_CPP_VALIDATION_URL = "http://127.0.0.1:8081"
    $env:LLAMA_CPP_GGUF_DIR = "F:/DIPLOM_GGUF"
    $env:LLAMA_CPP_CTX = "8192"
    $env:LLAMA_CPP_NGL = "99"
    $env:LLAMA_CPP_GPU_MODE = "single"
    $env:OLLAMA_HOST = "http://127.0.0.1:11434"
    $env:UPLOAD_DIR = Join-Path $DataDir "uploads"
    $env:STORAGE_DIR = $DataDir
    # Рантайм-реестры внутри проекта (не dataset/blacklist)
    $env:BLACKLIST_DIR = Join-Path $DataDir "blacklist"
    $env:AUTH_SERVICE_URL = "http://127.0.0.1:8001"
    $env:CASES_SERVICE_URL = "http://127.0.0.1:8002"
    $env:PARSERS_SERVICE_URL = "http://127.0.0.1:8003"
    $env:LLM_SERVICE_URL = "http://127.0.0.1:8004"
    $env:REPORTS_SERVICE_URL = "http://127.0.0.1:8005"
    $env:OLLAMA_EXTREMISM_MODEL = "qwen-actual-run3-extremism"
    $env:OLLAMA_ENTITIES_MODEL = "qwen-newclass3run"
    $env:OLLAMA_VALIDATION_MODEL = "qwen25-7b-instruct"
    $rubert = Join-Path $DiplomRoot "RUBERT\rubert-mini-uncased-15"
    if (Test-Path $rubert) { $env:RUBERT_MODEL_PATH = $rubert }
}

function Ensure-Directories {
    $bl = Join-Path $DataDir "blacklist"
    $runs = Join-Path $DataDir "parser_runs"
    $logs = Join-Path $bl "update_logs"
    New-Item -ItemType Directory -Force -Path $DataDir, $LogDir, (Join-Path $DataDir "uploads"), $bl, $runs, $logs | Out-Null
}

function Ensure-PythonDeps {
    Write-Step "Зависимости Python"
    $req = Join-Path $Root "requirements.txt"
    $marker = Join-Path $DataDir ".requirements_installed"
    if (-not (Test-Path $marker)) {
        & $script:PyExe -m pip install -r $req -q
        if ($LASTEXITCODE -ne 0) {
            Write-Warn "pip install не удался (прокси?). Повторите: pip install -r requirements.txt"
        } else {
            Set-Content -Path $marker -Value (Get-Date -Format o)
            Write-Ok "зависимости установлены"
        }
    } else {
        Write-Ok "зависимости уже установлены"
    }
}

function Ensure-NodeDeps {
    if ($SkipFrontend) {
        Write-Step "Интерфейс (npm)"
        Write-Ok "пропущен (-SkipFrontend)"
        return $false
    }
    Write-Step "Интерфейс (npm)"
    $fe = Join-Path $Root "frontend"
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
        Write-Warn "npm не найден - интерфейс будет пропущен"
        return $false
    }
    if (-not (Test-Path (Join-Path $fe "node_modules"))) {
        Push-Location $fe
        try { npm install --silent 2>$null } finally { Pop-Location }
        Write-Ok "npm install выполнен"
    } else {
        Write-Ok "node_modules уже есть"
    }
    return $true
}

function Ensure-Redis {
    Write-Step "Redis (брокер Celery)"
    if (Test-PortOpen 6379) {
        Write-Ok "Redis на порту 6379"
        return $true
    }
    $docker = Get-Command docker -ErrorAction SilentlyContinue
    if ($docker) {
        $prevEap = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        try {
            $existing = docker ps -a --filter "name=platform-redis" --format "{{.Names}}" 2>&1 | Out-String
            if ($existing.Trim() -eq "platform-redis") {
                docker start platform-redis 2>&1 | Out-Null
            } else {
                docker run -d --name platform-redis -p 6379:6379 redis:7-alpine 2>&1 | Out-Null
            }
            Start-Sleep -Seconds 3
        } catch {
            Write-Warn "Docker Redis: $($_.Exception.Message)"
        } finally {
            $ErrorActionPreference = $prevEap
        }
        if (Test-PortOpen 6379) {
            Write-Ok "Redis запущен через Docker"
            return $true
        }
    }
    Write-Warn "Redis недоступен. Установите Redis/Memurai или выполните: docker run -d -p 6379:6379 redis:7-alpine"
    Write-Warn "Celery worker не запустится без Redis."
    return $false
}

function Ensure-LlamaCpp {
    if ($SkipLlamaCpp -or $SkipOllama) { return }
    Write-Step "llama.cpp (LLM)"
    $gpuMode = $env:LLAMA_CPP_GPU_MODE
    if ($gpuMode -eq "single") {
        # В single GPU сервер поднимает LLM-сервис (переключение GGUF).
        # Проверяем только бинарник через start_llama_cpp.ps1.
        $scriptPath = Join-Path $Root "scripts\start_llama_cpp.ps1"
        if (-not (Test-Path $scriptPath)) {
            Write-Warn "скрипт не найден: $scriptPath"
            return
        }
        $prevEap = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        & $scriptPath -LogDir $LogDir -HealthTimeoutSec 300 -GpuMode single -Ngl ([int]$env:LLAMA_CPP_NGL)
        $exitCode = $LASTEXITCODE
        $ErrorActionPreference = $prevEap
        if ($exitCode -eq 0) {
            Write-Ok "llama.cpp (single GPU) готов к переключению моделей"
        } else {
            Write-Warn "llama.cpp: проверьте CUDA-сборку (см. data/logs)"
        }
        return
    }
    $ports = @(8081, 8082, 8083)
    $allReady = $true
    foreach ($port in $ports) {
        $h = Invoke-HealthCheck "http://127.0.0.1:$port/health"
        if (-not ($h -and $h.ok)) { $allReady = $false; break }
    }
    if ($allReady) {
        Write-Ok "серверы llama.cpp доступны (порты 8081–8083)"
        return
    }
    $scriptPath = Join-Path $Root "scripts\start_llama_cpp.ps1"
    if (-not (Test-Path $scriptPath)) {
        Write-Warn "скрипт не найден: $scriptPath"
        return
    }
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & $scriptPath -LogDir $LogDir -HealthTimeoutSec 300 -GpuMode $env:LLAMA_CPP_GPU_MODE -Ngl ([int]$env:LLAMA_CPP_NGL)
    $exitCode = $LASTEXITCODE
    $ErrorActionPreference = $prevEap
    if ($exitCode -eq 0) {
        Write-Ok "llama.cpp серверы запущены"
    } else {
        Write-Warn "не все серверы llama.cpp готовы (см. $LogDir\llm-*.err.log)"
    }
}

function Start-BackgroundProcess([string]$Name, [string]$Command, [string[]]$ProcArgs, [int]$Port) {
    $label = Get-ServiceRuName $Name
    if (Test-PortOpen $Port) {
        Write-Ok "$label уже на порту $Port"
        return @{ name = $Name; port = $Port; started = $false; pid = $null; ready = $true }
    }
    $logOut = Join-Path $LogDir "$Name.log"
    $logErr = Join-Path $LogDir "$Name.err.log"
    $p = Start-Process -FilePath $Command -ArgumentList $ProcArgs -WorkingDirectory $Root `
        -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput $logOut -RedirectStandardError $logErr
    $ready = Wait-Health $Name "http://127.0.0.1:$Port/health" $HealthTimeoutSec
    if ($ready) {
        Write-Ok "$label запущен (PID $($p.Id), порт $Port)"
    } else {
        Write-Err "$label не готов (см. $logErr)"
    }
    return @{ name = $Name; port = $Port; started = $true; pid = $p.Id; ready = $ready }
}

function Start-CeleryWorker {
    Write-Step "Фоновый worker Celery"
    $existing = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like "*services.worker.app.tasks*" }
    if ($existing) {
        Write-Ok "Celery worker уже запущен"
        return @{ name = "worker"; pid = $existing[0].ProcessId; ready = $true }
    }
    $logOut = Join-Path $LogDir "worker.log"
    $celeryArgs = @(
        "-m", "celery",
        "-A", "services.worker.app.tasks:celery_app",
        "worker", "--loglevel=info", "-P", "solo"
    )
    $p = Start-Process -FilePath $script:PyExe -ArgumentList $celeryArgs -WorkingDirectory $Root `
        -WindowStyle Hidden -PassThru -RedirectStandardOutput $logOut -RedirectStandardError (Join-Path $LogDir "worker.err.log")
    Start-Sleep -Seconds 3
    Write-Ok "Celery worker запущен, PID $($p.Id)"
    return @{ name = "worker"; pid = $p.Id; ready = $true }
}

function Resolve-NpmCmd {
    $npm = Get-Command npm -ErrorAction SilentlyContinue
    if (-not $npm) { return $null }
    $dir = Split-Path $npm.Source -Parent
    $cmd = Join-Path $dir "npm.cmd"
    if (Test-Path $cmd) { return $cmd }
    if ($npm.Source -match '\.cmd$') { return $npm.Source }
    return $null
}

function Start-Frontend {
    if ($SkipFrontend) { return $null }
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { return $null }
    if (Test-PortOpen 5173) {
        Write-Ok "интерфейс уже на порту 5173"
        return @{ name = "frontend"; port = 5173; ready = $true }
    }
    $fe = Join-Path $Root "frontend"
    $logOut = Join-Path $LogDir "frontend.log"
    $logErr = Join-Path $LogDir "frontend.err.log"
    try {
        # npm на Windows - npm.cmd; Start-Process не запускает shim/ps1 напрямую
        $npmCmd = Resolve-NpmCmd
        if ($npmCmd) {
            $p = Start-Process -FilePath $npmCmd `
                -ArgumentList "run", "dev", "--", "--host", "0.0.0.0" `
                -WorkingDirectory $fe -WindowStyle Hidden -PassThru `
                -RedirectStandardOutput $logOut -RedirectStandardError $logErr
        } else {
            $p = Start-Process -FilePath "cmd.exe" `
                -ArgumentList "/c", "npm run dev -- --host 0.0.0.0" `
                -WorkingDirectory $fe -WindowStyle Hidden -PassThru `
                -RedirectStandardOutput $logOut -RedirectStandardError $logErr
        }
        Start-Sleep -Seconds 8
        $ready = Test-PortOpen 5173
        if ($ready) {
            Write-Ok "интерфейс: http://localhost:5173"
        } else {
            Write-Warn "интерфейс запускается (см. $logOut)"
        }
        return @{ name = "frontend"; port = 5173; pid = $p.Id; ready = $ready }
    } catch {
        Write-Warn "не удалось запустить интерфейс: $($_.Exception.Message)"
        Write-Warn "запустите вручную: cd frontend; npm run dev"
        return @{ name = "frontend"; port = 5173; pid = $null; ready = $false }
    }
}

function Get-PlatformStatus {
    $services = @(
        @{ name = "auth";    port = 8001; url = "http://127.0.0.1:8001/health" },
        @{ name = "cases";   port = 8002; url = "http://127.0.0.1:8002/health" },
        @{ name = "parsers"; port = 8003; url = "http://127.0.0.1:8003/health" },
        @{ name = "llm";     port = 8004; url = "http://127.0.0.1:8004/health" },
        @{ name = "reports"; port = 8005; url = "http://127.0.0.1:8005/health" },
        @{ name = "gateway"; port = 8000; url = "http://127.0.0.1:8000/health" }
    )
    $rows = @()
    foreach ($s in $services) {
        $portOpen = Test-PortOpen $s.port
        $h = if ($portOpen) { Invoke-HealthCheck $s.url } else { $null }
        $status = if ($h -and $h.ok) { "ГОТОВ" } elseif ($portOpen) { "ПОРТ" } else { "ВЫКЛ" }
        $rows += [PSCustomObject]@{
            Service = (Get-ServiceRuName $s.name)
            Port    = $s.port
            Status  = $status
        }
    }
    $redis = if (Test-PortOpen 6379) { "ГОТОВ" } else { "ВЫКЛ" }
    $ports = if ($env:LLAMA_CPP_GPU_MODE -eq "multi") { @(8081, 8082, 8083) } else { @(8081) }
    $llamaReady = 0
    foreach ($lp in $ports) {
        $lh = Invoke-HealthCheck "http://127.0.0.1:$lp/health"
        if ($lh -and $lh.ok) { $llamaReady++ }
    }
    $llamacpp = if ($llamaReady -eq $ports.Count) { "ГОТОВ (GPU)" } elseif ($llamaReady -gt 0) { "ЧАСТИЧНО ($llamaReady/$($ports.Count))" } else { "ВЫКЛ" }
    $fe = if (Test-PortOpen 5173) { "ГОТОВ" } else { "ВЫКЛ" }
    $worker = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like "*services.worker.app.tasks*" }
    $workerStatus = if ($worker) { "ГОТОВ" } else { "ВЫКЛ" }
    return @{ services = $rows; redis = $redis; llamacpp = $llamacpp; frontend = $fe; worker = $workerStatus }
}

function Show-StatusTable($status) {
    Write-Host ""
    Write-Host "========== Контент Дозор ==========" -ForegroundColor White
    $status.services | Select-Object `
        @{ Name = "Служба"; Expression = { $_.Service } }, `
        @{ Name = "Порт"; Expression = { $_.Port } }, `
        @{ Name = "Статус"; Expression = { $_.Status } } |
        Format-Table -AutoSize
    Write-Host ("Redis:      " + $status.redis)
    Write-Host ("llama.cpp:  " + $status.llamacpp)
    Write-Host ("Worker:     " + $status.worker)
    Write-Host ("Интерфейс:  " + $status.frontend)
    Write-Host "Шлюз API:   http://localhost:8000/docs" -ForegroundColor Blue
    Write-Host "Веб-UI:     http://localhost:5173" -ForegroundColor Blue
    Write-Host "====================================" -ForegroundColor White
}

function Stop-Platform {
    Write-Step "Остановка процессов платформы"
    if (Test-Path $PidFile) {
        $pids = Get-Content $PidFile | ConvertFrom-Json
        foreach ($item in $pids) {
            if ($item.pid) {
                Stop-Process -Id $item.pid -Force -ErrorAction SilentlyContinue
            }
        }
        Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
    }
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match "services\.(cases|auth|gateway|llm|parsers|reports|worker)" } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Get-CimInstance Win32_Process -Filter "Name='node.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like "*vite*" } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match 'llama-server' -or ($_.CommandLine -and $_.CommandLine -like '*llama-server*') } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Write-Ok "остановлено"
}

# --- main ---
$script:PyExe = Resolve-Python
Set-PlatformEnv
Ensure-Directories

if ($Stop) {
    Stop-Platform
    exit 0
}

if ($StatusOnly) {
    Show-StatusTable (Get-PlatformStatus)
    exit 0
}

Write-Host ""
Write-Host "Контент Дозор - запуск" -ForegroundColor White
Write-Host ""

Ensure-PythonDeps
$hasNode = Ensure-NodeDeps
$redisOk = Ensure-Redis
Ensure-LlamaCpp

Write-Step "Инициализация БД"
$prevEap = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& $script:PyExe (Join-Path $Root "scripts\bootstrap_db.py") 2>&1 | Out-Null
$ErrorActionPreference = $prevEap
if ($LASTEXITCODE -eq 0) { Write-Ok "БД готова" } else { Write-Warn "инициализация БД пропущена или завершилась с ошибкой" }

$uvicornArgs = @("-m", "uvicorn")
$pids = @()

$services = @(
    @{ name = "auth";    module = "services.auth.app.main:app";    port = 8001 },
    @{ name = "cases";   module = "services.cases.app.main:app";   port = 8002 },
    @{ name = "parsers"; module = "services.parsers.app.main:app"; port = 8003 },
    @{ name = "llm";     module = "services.llm.app.main:app";     port = 8004 },
    @{ name = "reports"; module = "services.reports.app.main:app"; port = 8005 },
    @{ name = "gateway"; module = "services.gateway.app.main:app"; port = 8000 }
)

Write-Step "Микросервисы"
foreach ($svc in $services) {
    $procArgs = $uvicornArgs + @($svc.module, "--host", "127.0.0.1", "--port", "$($svc.port)")
    $info = Start-BackgroundProcess $svc.name $script:PyExe $procArgs $svc.port
    $pids += $info
}

$workerInfo = $null
if ($redisOk) {
    $workerInfo = Start-CeleryWorker
    $pids += $workerInfo
} else {
    Write-Warn "Celery worker пропущен (нет Redis)"
}

if ($hasNode -and -not $SkipFrontend) {
    $feInfo = Start-Frontend
    if ($feInfo) { $pids += $feInfo }
}

$pids | ConvertTo-Json | Set-Content -Path $PidFile -Encoding UTF8

$status = Get-PlatformStatus
Show-StatusTable $status

$notReady = @($status.services | Where-Object { $_.Status -ne "ГОТОВ" })
if ($notReady.Count -gt 0) {
    Write-Warn "Не все службы в статусе ГОТОВ. Логи: $LogDir"
    exit 1
}
Write-Host "Платформа готова к работе." -ForegroundColor Green
