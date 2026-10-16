param([string]$Python = '..\.venv\Scripts\python.exe')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
& $Python -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw 'Tests failed' }
& $Python -m PyInstaller --noconfirm FabricLabelStudio.spec
if ($LASTEXITCODE -ne 0) { throw 'Build failed' }
& $Python scripts/package_release.py
if ($LASTEXITCODE -ne 0) { throw 'Packaging failed' }
