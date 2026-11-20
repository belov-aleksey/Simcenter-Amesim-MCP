param([string]$Python)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
Set-Location $PSScriptRoot
function Find-Python {
    $candidates = @()
    if ($Python) { $candidates += $Python }
    foreach ($root in @('HKCU:\Software\Python\PythonCore', 'HKLM:\Software\Python\PythonCore')) {
        if (Test-Path $root) {
            foreach ($key in Get-ChildItem $root) {
                $install = Join-Path $key.PSPath 'InstallPath'
                if (Test-Path $install) {
                    $candidates += Join-Path (Get-Item $install).GetValue('') 'python.exe'
                }
            }
        }
    }
    $candidates += "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe"
    $candidates += "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
    foreach ($candidate in $candidates | Select-Object -Unique) {
        if (Test-Path -LiteralPath $candidate) {
            & $candidate -c "import sys,struct,venv,ensurepip; sys.exit(0 if (3,12)<=sys.version_info[:2]<(3,14) and struct.calcsize('P')==8 else 1)" 2>$null
            if ($LASTEXITCODE -eq 0) { return $candidate }
        }
    }
}
$interpreter = Find-Python
if (-not $interpreter) {
    & winget install --id Python.Python.3.13 --exact --scope user --silent --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) { throw 'Python installation failed' }
    $interpreter = Find-Python
}
if (-not $interpreter) { throw 'Python 3.12/3.13 x64 not found. Use -Python <absolute path>.' }
Write-Host "Using $interpreter"
& $interpreter -m venv .venv
if ($LASTEXITCODE -ne 0) { throw 'venv creation failed' }
$venvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
& $venvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw 'pip upgrade failed' }
& $venvPython -m pip install -e .
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
& $venvPython -m amesim_mcp.doctor
if ($LASTEXITCODE -ne 0) { throw 'Doctor failed. Set AMESIM_HOME and rerun doctor.' }
Write-Host 'Installed. Next: .\configure-codex.ps1'
