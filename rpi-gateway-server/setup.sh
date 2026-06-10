#!/usr/bin/env bash
# setup.sh — venv 생성 및 의존성 설치
#
# 사용법:
#   chmod +x setup.sh && ./setup.sh
#
# 동작:
#   1. python3 버전 확인 (3.11 이상 요구)
#   2. .venv 가 없으면 생성, 있으면 재사용
#   3. pip upgrade 후 requirements.txt 설치

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"
REQUIREMENTS="$SCRIPT_DIR/requirements.txt"

GREEN="\033[0;32m"; YELLOW="\033[1;33m"; RED="\033[0;31m"; RESET="\033[0m"
log()  { echo -e "${GREEN}[setup]${RESET} $*"; }
warn() { echo -e "${YELLOW}[setup]${RESET} $*"; }
err()  { echo -e "${RED}[setup]${RESET} $*" >&2; exit 1; }

# ── 1. Python 버전 확인 ───────────────────────────────────────────
PYTHON=$(command -v python3 || true)
[[ -z "$PYTHON" ]] && err "python3 not found"

PY_VERSION=$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$(echo "$PY_VERSION" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VERSION" | cut -d. -f2)

log "found python3 $PY_VERSION"

if [[ "$PY_MAJOR" -lt 3 || ("$PY_MAJOR" -eq 3 && "$PY_MINOR" -lt 11) ]]; then
    err "python 3.11+ required (found $PY_VERSION)"
fi

# ── 2. venv 생성 또는 재사용 ──────────────────────────────────────
if [[ -d "$VENV_DIR" ]]; then
    warn ".venv already exists — reusing"
else
    log "creating .venv …"
    "$PYTHON" -m venv "$VENV_DIR"
    log ".venv created at $VENV_DIR"
fi

PIP="$VENV_DIR/bin/pip"

# ── 3. pip 업그레이드 및 의존성 설치 ─────────────────────────────
log "upgrading pip …"
"$PIP" install --quiet --upgrade pip

log "installing requirements.txt …"
"$PIP" install --quiet -r "$REQUIREMENTS"

log "done — activate with:  source .venv/bin/activate"
