#!/usr/bin/env bash
# run.sh — server + gateway 동시 기동 및 일괄 종료
#
# 사용법:
#   ./run.sh [--log-level LEVEL]
#   ./run.sh -l debug
#
# 옵션:
#   -l, --log-level   로그 레벨: DEBUG | INFO | WARNING | ERROR  (기본: INFO)
#   -h, --help        도움말 출력
#
# 환경 변수 (옵션보다 낮은 우선순위):
#   SERIAL_PORT   (기본: /dev/ttyACM0)
#   BAUD_RATE     (기본: 115200)
#   SERVER_HOST   (기본: 0.0.0.0)
#   SERVER_PORT   (기본: 8000)
#   LOG_LEVEL     (기본: INFO)
#   MOCK_DATA     (기본: 0, 1/true/yes/on이면 활성화)
#
# 종료 동작:
#   - Ctrl+C(SIGINT) 또는 SIGTERM → 두 프로세스 모두 정상 종료
#   - 어느 한쪽이 예기치 않게 종료되면 나머지도 중단

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── 인자 파싱 ─────────────────────────────────────────────────────
_ARG_LOG_LEVEL=""

usage() {
    echo "usage: ./run.sh [-l|--log-level DEBUG|INFO|WARNING|ERROR] [-h|--help]"
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -l|--log-level)
            _ARG_LOG_LEVEL="${2^^}"   # 대문자 정규화
            shift 2 ;;
        -h|--help) usage ;;
        *) echo "[run.sh] unknown option: $1" >&2; usage ;;
    esac
done

# ── venv 확인 ─────────────────────────────────────────────────────
VENV_DIR="$SCRIPT_DIR/.venv"
if [[ ! -d "$VENV_DIR" ]]; then
    echo "[run.sh] .venv not found — run ./setup.sh first" >&2
    exit 1
fi
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

: "${SERIAL_PORT:=/dev/ttyACM0}"
: "${BAUD_RATE:=115200}"
: "${SERVER_HOST:=0.0.0.0}"
: "${SERVER_PORT:=8000}"
: "${LOG_LEVEL:=INFO}"
: "${MOCK_DATA:=0}"

# 커맨드라인 옵션이 환경 변수보다 우선
[[ -n "$_ARG_LOG_LEVEL" ]] && LOG_LEVEL="$_ARG_LOG_LEVEL"

export SERIAL_PORT BAUD_RATE LOG_LEVEL MOCK_DATA
export SERVER_URL="http://localhost:${SERVER_PORT}"

# ── 색상 출력 ─────────────────────────────────────────────────────
GREEN="\033[0;32m"; YELLOW="\033[1;33m"; RED="\033[0;31m"; RESET="\033[0m"
log()  { echo -e "${GREEN}[run.sh]${RESET} $*"; }
warn() { echo -e "${YELLOW}[run.sh]${RESET} $*"; }
err()  { echo -e "${RED}[run.sh]${RESET} $*" >&2; }

# ── 정리 함수 (중복 실행 방지) ────────────────────────────────────
SERVER_PID=""
GATEWAY_PID=""
_STOPPED=0

cleanup() {
    [[ $_STOPPED -eq 1 ]] && return
    _STOPPED=1
    echo ""
    warn "stopping all processes…"
    [[ -n "$SERVER_PID"  ]] && kill "$SERVER_PID"  2>/dev/null || true
    [[ -n "$GATEWAY_PID" ]] && kill "$GATEWAY_PID" 2>/dev/null || true
    [[ -n "$SERVER_PID"  ]] && wait "$SERVER_PID"  2>/dev/null || true
    [[ -n "$GATEWAY_PID" ]] && wait "$GATEWAY_PID" 2>/dev/null || true
    log "all stopped"
}

trap cleanup SIGINT SIGTERM

# ── 서버 기동 ─────────────────────────────────────────────────────
log "starting server  (host=${SERVER_HOST} port=${SERVER_PORT})"
(
  cd "$SCRIPT_DIR/server"
  exec uvicorn main:app \
    --host "$SERVER_HOST" \
    --port "$SERVER_PORT" \
    --log-level "$(echo "$LOG_LEVEL" | tr '[:upper:]' '[:lower:]')"
) &
SERVER_PID=$!
log "server  PID=$SERVER_PID"

# 서버가 listen 상태가 될 때까지 대기 (최대 10초)
log "waiting for server to be ready…"
for i in $(seq 1 10); do
    if curl -sf "http://localhost:${SERVER_PORT}/api/buoys" > /dev/null 2>&1; then
        log "server ready (${i}s)"
        break
    fi
    if ! kill -0 "$SERVER_PID" 2>/dev/null; then
        err "server failed to start"
        exit 1
    fi
    sleep 1
done

# ── 게이트웨이 기동 ───────────────────────────────────────────────
log "starting gateway (serial=${SERIAL_PORT})"
(
  cd "$SCRIPT_DIR/gateway"
  exec python main.py
) &
GATEWAY_PID=$!
log "gateway PID=$GATEWAY_PID"

log "all services running — press Ctrl+C to stop"

# ── 감시 루프: 한쪽이 죽으면 나머지도 종료 ───────────────────────
while true; do
    if ! kill -0 "$SERVER_PID" 2>/dev/null; then
        err "server (PID=$SERVER_PID) exited unexpectedly"
        break
    fi
    if ! kill -0 "$GATEWAY_PID" 2>/dev/null; then
        err "gateway (PID=$GATEWAY_PID) exited unexpectedly"
        break
    fi
    sleep 2
done

cleanup
