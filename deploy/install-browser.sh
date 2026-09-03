#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"

if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "Virtual environment not found at ${ROOT_DIR}/.venv" >&2
  exit 1
fi

"${PYTHON_BIN}" -m playwright install chromium

echo "Playwright Chromium installed for Internet Pricing."
