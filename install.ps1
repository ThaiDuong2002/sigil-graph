$ErrorActionPreference = "Stop"

$Python = if ($env:PYTHON) { $env:PYTHON } else { "python" }

# Verify Python version
$pyMinor = & $Python -c "import sys; print(sys.version_info.minor)"
if ([int]$pyMinor -lt 10) {
    Write-Error "Python 3.10+ required (found $( & $Python --version ))"
    exit 1
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Venv = Join-Path $ScriptDir ".venv"

if (-not (Test-Path $Venv)) {
    Write-Host "Creating virtualenv at $Venv..."
    & $Python -m venv $Venv
}

Write-Host "Installing symbex..."
& "$Venv\Scripts\pip" install -e $ScriptDir --quiet

$SymbexBin = Join-Path $Venv "Scripts\symbex.exe"
Write-Host ""
Write-Host "Installed: $SymbexBin"
Write-Host ""
Write-Host "To use symbex without activating the venv, add to your PATH:"
Write-Host "  `$env:PATH = `"$Venv\Scripts;`$env:PATH`""
Write-Host ""
Write-Host "Or activate the venv first:"
Write-Host "  $Venv\Scripts\Activate.ps1"
