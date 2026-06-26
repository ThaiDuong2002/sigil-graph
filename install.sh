#!/usr/bin/env bash
# Install symbex from anywhere — no prior clone needed.
#
# Quick install:
#   curl -sSL https://raw.githubusercontent.com/ThaiDuong2002/symbex-graph/master/install.sh | bash
#
# Custom install location:
#   SYMBEX_DIR=~/tools/symbex curl -sSL ... | bash

set -euo pipefail

PYTHON=${PYTHON:-python3}
REPO_URL="https://github.com/ThaiDuong2002/symbex-graph.git"
INSTALL_DIR="${SYMBEX_DIR:-$HOME/.symbex}"
MIN_MINOR=10

# ── Verify Python ──────────────────────────────────────────────────────────
PY_MINOR=$("$PYTHON" -c "import sys; print(sys.version_info.minor)" 2>/dev/null) || {
  echo "Error: '$PYTHON' not found. Install Python 3.${MIN_MINOR}+ first." >&2
  exit 1
}
if [ "$PY_MINOR" -lt "$MIN_MINOR" ]; then
  echo "Error: Python 3.${MIN_MINOR}+ required (found $("$PYTHON" --version))" >&2
  exit 1
fi

# ── Clone or update repo ───────────────────────────────────────────────────
if [ -d "$INSTALL_DIR/.git" ]; then
  echo "Updating symbex at $INSTALL_DIR..."
  git -C "$INSTALL_DIR" pull --quiet
else
  echo "Installing symbex to $INSTALL_DIR..."
  git clone --quiet "$REPO_URL" "$INSTALL_DIR"
fi

# ── Create venv and install ────────────────────────────────────────────────
VENV="$INSTALL_DIR/.venv"
if [ ! -d "$VENV" ]; then
  "$PYTHON" -m venv "$VENV"
fi

"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet -e "$INSTALL_DIR"

# ── Done ───────────────────────────────────────────────────────────────────
echo ""
echo "Symbex installed at $INSTALL_DIR"
echo ""
echo "Add to your shell profile (~/.bashrc or ~/.zshrc):"
echo "  export PATH=\"$VENV/bin:\$PATH\""
echo ""
echo "Then index any project:"
echo "  cd ~/your-project && symbex init"
