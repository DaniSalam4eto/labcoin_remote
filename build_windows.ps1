# Build dist\LabcoinRemote\LabcoinRemote.exe (onedir). Run from repo root.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
python -m pip install -r requirements.txt -r requirements-build.txt
python -m PyInstaller --noconfirm LabcoinRemote.spec
Write-Host "Output: $(Join-Path $PSScriptRoot 'dist\LabcoinRemote\LabcoinRemote.exe')"
