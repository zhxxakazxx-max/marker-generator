param([string]$Python = '..\.venv\Scripts\python.exe')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
& $Python -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw 'Tests failed' }
& $Python -m PyInstaller --noconfirm FabricLabelBatchGenerator.spec
if ($LASTEXITCODE -ne 0) { throw 'Build failed' }
