#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

MODE="${1:-local}"
if [[ $# -gt 0 ]]; then
    shift
fi

show_usage() {
    cat <<'EOF'
Usage: ./scripts/run.sh [local|test|docker|docker-postgres|help] [args...]

Modes:
  local            Run Nextor locally in .venv (default, uses DB_URL or SQLite)
  test             Run pytest, ruff and check_no_emoji.py
  docker           Run via Docker Compose (SQLite default or DB_URL from .env)
  docker-postgres  Run via Docker Compose with the optional PostgreSQL service
  help             Show this message
EOF
}

ensure_venv() {
    local venv_py="${REPO_ROOT}/.venv/bin/python"
    if [[ ! -x "${venv_py}" ]]; then
        python3 -m venv .venv
        "${venv_py}" -m pip install --upgrade pip
        "${venv_py}" -m pip install -r requirements.txt
    fi
    printf '%s\n' "${venv_py}"
}

case "${MODE}" in
    help|-h|--help)
        show_usage
        exit 0
        ;;
    local)
        PY="$(ensure_venv)"
        "${PY}" -m nextor "$@"
        ;;
    test)
        PY="$(ensure_venv)"
        export NEXTOR_VOZ_SAIDA="nenhuma"
        "${PY}" -m pytest "$@"
        "${PY}" -m ruff check scripts/check_no_emoji.py nextor/db.py tests/test_banco_plugavel.py
        "${PY}" scripts/check_no_emoji.py
        ;;
    docker)
        docker compose up --build "$@"
        ;;
    docker-postgres)
        export DB_URL="${DB_URL:-postgresql+psycopg://nextor:changeme@postgres:5432/nextor}"
        docker compose --profile postgres up --build "$@"
        ;;
    *)
        show_usage >&2
        exit 1
        ;;
esac
