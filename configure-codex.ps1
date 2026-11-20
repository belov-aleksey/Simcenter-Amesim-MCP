param([string]$AmesimHome, [switch]$EnableUnsafePython, [switch]$Force)
$ErrorActionPreference = 'Stop'
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { throw 'Run install.ps1 first' }
$arguments = @('-m', 'amesim_mcp.configure')
if ($AmesimHome) { $arguments += @('--home', $AmesimHome) }
if ($EnableUnsafePython) { $arguments += '--unsafe-python' }
if ($Force) { $arguments += '--force' }
& $python @arguments
if ($LASTEXITCODE -ne 0) { throw 'Codex configuration failed' }
