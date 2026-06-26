# Install sigil from anywhere — no prior clone needed.
#
# Quick install (run in PowerShell):
#   irm https://raw.githubusercontent.com/ThaiDuong2002/sigil-graph/master/install.ps1 | iex
#
# Custom install location:
#   $env:SIGIL_DIR = "C:\tools\sigil"
#   irm https://raw.githubusercontent.com/ThaiDuong2002/sigil-graph/master/install.ps1 | iex

$ErrorActionPreference = "Stop"

$Python     = if ($env:PYTHON)     { $env:PYTHON }     else { "python" }
$RepoUrl    = "https://github.com/ThaiDuong2002/sigil-graph.git"
$InstallDir = if ($env:SIGIL_DIR) { $env:SIGIL_DIR } else { Join-Path $env:USERPROFILE ".sigil" }
$MinMinor   = 10

# ── Verify Python ──────────────────────────────────────────────────────────
try {
    $pyMinor = & $Python -c "import sys; print(sys.version_info.minor)" 2>$null
} catch {
    Write-Error "'$Python' not found. Install Python 3.$MinMinor+ first."
    exit 1
}
if ([int]$pyMinor -lt $MinMinor) {
    Write-Error "Python 3.$MinMinor+ required (found $(& $Python --version))"
    exit 1
}

# ── Clone or update repo ───────────────────────────────────────────────────
if (Test-Path (Join-Path $InstallDir ".git")) {
    Write-Host "Updating sigil at $InstallDir..."
    git -C $InstallDir pull --quiet
} else {
    Write-Host "Installing sigil to $InstallDir..."
    git clone --quiet $RepoUrl $InstallDir
}

# ── Create venv and install ────────────────────────────────────────────────
$Venv = Join-Path $InstallDir ".venv"
if (-not (Test-Path $Venv)) {
    & $Python -m venv $Venv
}

& "$Venv\Scripts\pip" install --quiet --upgrade pip
& "$Venv\Scripts\pip" install --quiet -e $InstallDir

# ── Done ───────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "Sigil installed at $InstallDir"
Write-Host ""
Write-Host "Add to your PATH (paste into your PowerShell profile):"
Write-Host "  `$env:PATH = `"$Venv\Scripts;`$env:PATH`""
Write-Host ""
Write-Host "Then index any project:"
Write-Host "  cd C:\your-project; sigil init"
