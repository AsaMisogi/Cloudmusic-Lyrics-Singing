# 首次安装仅写入项目目录，不修改系统 Python、PATH 或网易云文件。
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$env:UV_CACHE_DIR = Join-Path $projectRoot '.cache\uv'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $projectRoot '.runtime\python'
$uvCommand = Get-Command uv.exe -ErrorAction SilentlyContinue
if ($uvCommand) {
    $uvPath = $uvCommand.Source
} else {
    $uvPath = Join-Path $projectRoot '.runtime\uv\uv.exe'
    if (-not (Test-Path -LiteralPath $uvPath)) {
        Write-Host 'Downloading the project-local uv runtime...'
        $runtimeDir = Join-Path $projectRoot '.runtime\uv'
        New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
        $archivePath = Join-Path $runtimeDir 'uv.zip'
        Invoke-WebRequest -Uri 'https://github.com/astral-sh/uv/releases/download/0.12.3/uv-x86_64-pc-windows-msvc.zip' -OutFile $archivePath
        Expand-Archive -LiteralPath $archivePath -DestinationPath $runtimeDir -Force
    }
}
Write-Host 'Preparing Python 3.12 and locked project dependencies...'
& $uvPath sync --frozen
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Check your network connection and retry.' }
Write-Host 'Setup complete.'
