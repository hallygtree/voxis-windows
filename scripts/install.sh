#!/usr/bin/env bash
# LARIS installer — standalone transcriber. No panel, no kiris needed.
# Usage: bash scripts/install.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

echo "=== LARIS installer ==="
echo "Repo: $REPO_ROOT"
echo ""

# 1. Python version check
if ! python3.11 --version &>/dev/null; then
  echo "ERROR: Python 3.11 not found. Install it via 'brew install python@3.11' or pyenv." >&2
  exit 1
fi

# 2. Create venv if missing
if [[ ! -d ".venv" ]]; then
  echo "Creating venv..."
  python3.11 -m venv .venv
fi

# 3. Install dependencies + editable package
echo "Installing dependencies (this takes a few minutes for torch/mlx)..."
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -e .

# 4. Verify import
echo ""
echo "Verifying..."
.venv/bin/python -c "import laris; print('LARIS import OK')"
.venv/bin/python -c "from laris.audio_capture import _denoise_chunk; print('DFN3 wrapper OK')"
.venv/bin/python -c "from laris.app_context import format_for_focus; print('app_context OK')"

# 5. Build Laris.app wrapper (TCC mic permission)
echo ""
echo "Building Laris.app wrapper..."
bash scripts/build-app.sh

echo ""
echo "=== LARIS installed successfully ==="
echo ""
echo "To start:"
echo "  open Laris.app                   # GUI launch (triggers mic TCC prompt)"
echo "  # or"
echo "  .venv/bin/python -m laris         # CLI launch (needs Warp for mic)"
echo ""
echo "Hold cmd_r to dictate. Release to paste."
echo "Logs: /tmp/laris.log"
echo ""
echo "To stop: pkill -9 -f 'python -m laris'"
