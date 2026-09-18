# Запуск llama.cpp server (GPU) для analysis_platform
# single — одна модель на GPU, переключение по роли (16 GB VRAM)
# multi  — три сервера на портах 8081–8083 (нужно >= 24 GB VRAM)

param(
    [string]$GgufDir = "F:\DIPLOM_GGUF",
    [ValidateSet("single", "multi")]
    [string]$GpuMode = "single",
    [int]$Ctx = 8192,
    [int]$Ngl = 99,
    [int]$HealthTimeoutSec = 300,
    [string]$LogDir = ""
)

$ErrorActionPreference = "Stop"

function Write-Ok([string]$msg) {
    Write-Host "  ОК  $msg" -ForegroundColor Green
}

function Write-Warn([string]$msg) {
    Write-Host "  !!  $msg" -ForegroundColor Yellow
}

$DiplomRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$LlamaVendor = Join-Path $DiplomRoot "llama_classific\llama_train\vendor\llama.cpp"
$BinDir = Join-Path $LlamaVendor "bin"
$CudaDir = Join-Path $BinDir "cuda"

function Find-LlamaServerExe {
    foreach ($dir in @($CudaDir, $BinDir)) {
        $exe = Join-Path $dir "llama-server.exe"
        if (Test-Path $exe) { return $exe }
    }
    return $null
}

function Test-CudaBinary([string]$Dir) {
    return (Test-Path (Join-Path $Dir "ggml-cuda.dll")) -or (Test-Path (Join-Path $Dir "ggml-cuda*.dll"))
}

function Ensure-LlamaCudaBinary {
    New-Item -ItemType Directory -Force -Path $CudaDir | Out-Null
    if ((Find-LlamaServerExe) -and (Test-CudaBinary $CudaDir)) {
        return (Find-LlamaServerExe)
    }
    $baseUrl = "https://github.com/ggml-org/llama.cpp/releases/download/b9780"
    $binZip = Join-Path $CudaDir "llama-b9780-bin-win-cuda-12.4-x64.zip"
    $rtZip = Join-Path $CudaDir "cudart-llama-bin-win-cuda-12.4-x64.zip"
    Write-Host "  .. скачивание llama-server CUDA 12.4..." -ForegroundColor Cyan
    $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
    if ($curl) {
        curl.exe -L --ssl-no-revoke --retry 3 -o $binZip "$baseUrl/llama-b9780-bin-win-cuda-12.4-x64.zip"
        curl.exe -L --ssl-no-revoke --retry 3 -o $rtZip "$baseUrl/cudart-llama-bin-win-cuda-12.4-x64.zip"
    } else {
        Invoke-WebRequest -Uri "$baseUrl/llama-b9780-bin-win-cuda-12.4-x64.zip" -OutFile $binZip -UseBasicParsing
        Invoke-WebRequest -Uri "$baseUrl/cudart-llama-bin-win-cuda-12.4-x64.zip" -OutFile $rtZip -UseBasicParsing
    }
    Expand-Archive -Path $binZip -DestinationPath $CudaDir -Force
    Expand-Archive -Path $rtZip -DestinationPath $CudaDir -Force
    Remove-Item $binZip, $rtZip -Force -ErrorAction SilentlyContinue
    $exe = Find-LlamaServerExe
    if (-not $exe) { throw "llama-server.exe (CUDA) не найден после распаковки" }
    Write-Ok "CUDA-сборка llama.cpp готова: $exe"
    return $exe
}

function Test-PortOpen([int]$Port) {
    try {
        $t = New-Object Net.Sockets.TcpClient
        $t.Connect("127.0.0.1", $Port)
        $t.Close()
        return $true
    } catch { return $false }
}

function Wait-LlamaHealth([int]$Port, [int]$TimeoutSec) {
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if (Test-PortOpen $Port) {
            try {
                $r = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/health" -UseBasicParsing -TimeoutSec 5
                if ($r.StatusCode -eq 200) { return $true }
            } catch {}
        }
        Start-Sleep -Seconds 2
    }
    return $false
}

function Start-LlamaServer([string]$Name, [int]$Port, [string]$Gguf, [string]$ServerExe) {
    if (-not (Test-Path $Gguf)) {
        Write-Warn "GGUF не найден: $Gguf"
        return $false
    }
    if (Test-PortOpen $Port) {
        Write-Ok "$Name уже на порту $Port"
        return $true
    }
    if (-not $LogDir) { $LogDir = Join-Path (Split-Path $PSScriptRoot -Parent) "data\logs" }
    New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
    $logOut = Join-Path $LogDir "$Name.log"
    $logErr = Join-Path $LogDir "$Name.err.log"
    $procArgs = @(
        "-m", $Gguf,
        "--port", "$Port",
        "--host", "127.0.0.1",
        "-c", "$Ctx"
    )
    if ($Ngl -ne 0) { $procArgs += @("-ngl", "$Ngl") }
    $workDir = Split-Path $ServerExe -Parent
    $p = Start-Process -FilePath $ServerExe -ArgumentList $procArgs -WorkingDirectory $workDir `
        -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput $logOut -RedirectStandardError $logErr
    Write-Host "  .. $Name загружает модель на GPU (PID $($p.Id), -ngl $Ngl)..." -ForegroundColor Cyan
    if (Wait-LlamaHealth $Port $HealthTimeoutSec) {
        Write-Ok "$Name готов на порту $Port"
        return $true
    }
    Write-Warn "$Name не ответил (см. $logErr)"
    return $false
}

$models = @{
    extremism  = Join-Path $GgufDir "qwen-actual-run3-extremism-q5_k_m.gguf"
    entities   = Join-Path $GgufDir "qwen-newclass3run-q5_k_m.gguf"
    validation = Join-Path $GgufDir "qwen25-7b-instruct-q5_k_m.gguf"
}

$serverExe = Ensure-LlamaCudaBinary
$allOk = $true

if ($GpuMode -eq "single") {
    Write-Host '  GPU mode: single (one model on RTX, switch at runtime)' -ForegroundColor Cyan
    # Do not pre-start server: LLM service switches GGUF via llama_gpu_manager.py
    Write-Ok 'binary ready; LLM service starts llama-server on first request'
    if (Test-PortOpen 8081) {
        Write-Warn 'port 8081 already in use - LLM service will try to take it over'
    }
} else {
    Write-Host '  GPU mode: multi (3 servers, needs lots of VRAM)' -ForegroundColor Cyan
    $servers = @(
        @{ name = "llm-extremism";  port = 8081; gguf = $models.extremism }
        @{ name = "llm-entities";   port = 8082; gguf = $models.entities }
        @{ name = "llm-validation"; port = 8083; gguf = $models.validation }
    )
    foreach ($svc in $servers) {
        if (-not (Start-LlamaServer $svc.name $svc.port $svc.gguf $serverExe)) {
            $allOk = $false
        }
    }
}

if (-not $allOk) { exit 1 }
