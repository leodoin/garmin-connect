#!/usr/bin/env bash
set -euo pipefail
if ! command -v uv >/dev/null 2>&1; then
  python3 -m pip install --user 'uv==0.9.5'
  export PATH="$HOME/.local/bin:$PATH"
fi
uv sync --frozen --extra dev
uv run --frozen --extra dev pytest -q
