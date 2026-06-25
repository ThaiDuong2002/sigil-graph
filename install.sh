#!/usr/bin/env bash
set -euo pipefail

PYTHON=${PYTHON:-python3}
MIN_MINOR=10

# Verify Python version
PY_MINOR=$("$PYTHON" -c "import sys; print(sys.version_info.minor)")
if [ "$PY_MINOR" -lt "$MIN_MINOR" ]; then
  echo "Error: Python 3.${MIN_MINOR}+ required (found $("$PYTHON" --version))" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$SCRIPT_DIR/.venv"

if [ ! -d "$VENV" ]; then
  echo "Creating virtualenv at $VENV..."
  "$PYTHON" -m venv "$VENV"
fi

echo "Installing symbex..."
"$VENV/bin/pip" install -e "$SCRIPT_DIR" --quiet

SYMBEX_BIN="$VENV/bin/symbex"
echo ""
echo "Installed: $SYMBEX_BIN"
echo ""
echo "To use symbex without activating the venv, add to your shell profile:"
echo "  export PATH=\"$VENV/bin:\$PATH\""
echo ""
echo "Or activate the venv first:"
echo "  source $VENV/bin/activate"
