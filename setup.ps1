$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "Setting up AIwithSaeed Downloader..." -ForegroundColor Cyan

$venvPath = Join-Path $PSScriptRoot ".venv"
$venvPython = Join-Path $venvPath "Scripts\python.exe"
$invalidVenv = $null

if (Test-Path -LiteralPath $venvPython) {
    & $venvPython -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" 2>$null
    if ($LASTEXITCODE -ne 0) {
        $invalidVenv = Join-Path $PSScriptRoot (
            ".venv.invalid-" + (Get-Date -Format "yyyyMMdd-HHmmss")
        )
        Write-Host "The existing Python environment is not usable. Rebuilding it safely..." -ForegroundColor Yellow
        Move-Item -LiteralPath $venvPath -Destination $invalidVenv
    }
} elseif (Test-Path -LiteralPath $venvPath) {
    $invalidVenv = Join-Path $PSScriptRoot (
        ".venv.invalid-" + (Get-Date -Format "yyyyMMdd-HHmmss")
    )
    Move-Item -LiteralPath $venvPath -Destination $invalidVenv
}

$py = Get-Command py -ErrorAction SilentlyContinue
if (-not $py) {
    $python = Get-Command python -ErrorAction SilentlyContinue
    if (-not $python) {
        if ($invalidVenv -and (Test-Path -LiteralPath $invalidVenv)) {
            Move-Item -LiteralPath $invalidVenv -Destination $venvPath
        }
        Write-Host "Python 3.10 or newer is required." -ForegroundColor Yellow
        Write-Host "Install it from https://www.python.org/downloads/windows/ and enable 'Add Python to PATH'."
        Read-Host "Press Enter to close"
        exit 1
    }
}

try {
    if (-not (Test-Path -LiteralPath $venvPython)) {
        if ($py) {
            & py -3 -m venv .venv
        } else {
            & python -m venv .venv
        }
        if ($LASTEXITCODE -ne 0) { throw "Could not create the Python environment." }
    }
    & .\.venv\Scripts\python.exe -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw "Could not upgrade pip." }
    & .\.venv\Scripts\python.exe -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw "Could not install the app dependencies." }
    & .\.venv\Scripts\python.exe -c "import customtkinter, PIL, telegram, tkinterdnd2, yt_dlp"
    if ($LASTEXITCODE -ne 0) { throw "The installed Python environment did not pass validation." }
} catch {
    if ($invalidVenv -and (Test-Path -LiteralPath $invalidVenv)) {
        if (Test-Path -LiteralPath $venvPath) {
            Remove-Item -LiteralPath $venvPath -Recurse -Force
        }
        Move-Item -LiteralPath $invalidVenv -Destination $venvPath
        Write-Host "Setup failed; the previous environment was restored." -ForegroundColor Yellow
    }
    throw
}

if ($invalidVenv -and (Test-Path -LiteralPath $invalidVenv)) {
    Remove-Item -LiteralPath $invalidVenv -Recurse -Force
}

$winget = Get-Command winget -ErrorAction SilentlyContinue
if (-not (Get-Command deno -ErrorAction SilentlyContinue) -and -not (Get-Command node -ErrorAction SilentlyContinue)) {
    if ($winget) {
        $answer = Read-Host "Deno is needed for current YouTube downloads. Install it with winget now? [Y/n]"
        if ($answer -notmatch '^[Nn]') {
            & winget install --id DenoLand.Deno --exact --accept-source-agreements --accept-package-agreements
        }
    } else {
        Write-Host "Deno or Node.js 22+ is required for current YouTube downloads." -ForegroundColor Yellow
    }
}

if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    if ($winget) {
        $answer = Read-Host "FFmpeg is needed for merging video/audio and MP3 conversion. Install it with winget now? [Y/n]"
        if ($answer -notmatch '^[Nn]') {
            & winget install --id Gyan.FFmpeg --exact --accept-source-agreements --accept-package-agreements
        }
    } else {
        Write-Host "FFmpeg was not found. Install it later to merge high-quality video/audio." -ForegroundColor Yellow
    }
}

Set-Content -LiteralPath .setup-v8 -Value "AIwithSaeed Downloader setup version 8"

Write-Host ""
Write-Host "Setup complete. Double-click run.bat to start AIwithSaeed Downloader." -ForegroundColor Green
Read-Host "Press Enter to close"
