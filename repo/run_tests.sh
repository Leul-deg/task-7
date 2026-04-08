#!/usr/bin/env bash
set -euo pipefail

echo "╔══════════════════════════════════════╗"
echo "║       StudioOps Test Runner          ║"
echo "╚══════════════════════════════════════╝"
echo ""

# Determine which suites to run (default: all)
SUITES="${1:-all}"

case "$SUITES" in
  unit)
    DIRS="unit_tests/"
    ;;
  api)
    DIRS="API_tests/"
    ;;
  integration)
    DIRS="integration_tests/"
    ;;
  all)
    DIRS="unit_tests/ API_tests/ integration_tests/"
    ;;
  *)
    echo "Usage: $0 [unit|api|integration|all]"
    exit 1
    ;;
esac

PYTEST_CMD="python3 -m pytest $DIRS -v --tb=short"
TEST_RUNTIME="${STUDIOOPS_TEST_RUNTIME:-docker}"

have_docker_runtime() {
    command -v docker >/dev/null 2>&1 \
        && docker compose version >/dev/null 2>&1 \
        && docker info >/dev/null 2>&1
}

run_local_tests() {
    # Auto-create and activate venv if not already in one
    if [ -z "${VIRTUAL_ENV:-}" ]; then
        if [ ! -d "venv" ]; then
            echo "→ Creating virtual environment …"
            python3 -m venv venv
        fi
        # shellcheck disable=SC1091
        source venv/bin/activate
        echo "✓ Virtual environment activated"
    fi

    # Auto-install dependencies if pytest is missing
    if ! python3 -m pytest --version &>/dev/null; then
        echo "→ Installing dependencies …"
        pip install -q -r requirements.txt
        echo "✓ Dependencies installed"
    fi

    export FLASK_APP=app
    export FLASK_ENV=testing

    echo "→ Using local Python runtime"
    echo ""
    echo "Running: $PYTEST_CMD"
    echo "──────────────────────────────────────────────────────────────"
    echo ""

    set +e
    eval "$PYTEST_CMD"
    EXIT_CODE=$?
    set -e
}

run_docker_tests() {
    echo "→ Using Docker runtime"
    echo "→ Building test image …"
    docker compose build web

    echo ""
    echo "Running in Docker: $PYTEST_CMD"
    echo "──────────────────────────────────────────────────────────────"
    echo ""

    set +e
    docker compose run --rm \
        --entrypoint /bin/sh \
        -e FLASK_APP=app \
        -e FLASK_ENV=testing \
        -v "$PWD:/app" \
        web \
        -lc "cd /app && $PYTEST_CMD"
    EXIT_CODE=$?
    set -e
}

echo ""
case "$TEST_RUNTIME" in
  docker)
    if have_docker_runtime; then
        run_docker_tests
    else
        echo "→ Docker runtime unavailable, falling back to local Python"
        run_local_tests
    fi
    ;;
  local)
    run_local_tests
    ;;
  *)
    echo "Invalid STUDIOOPS_TEST_RUNTIME: $TEST_RUNTIME"
    echo "Use one of: docker, local"
    exit 1
    ;;
esac

echo ""
echo "══════════════════════════════════════"
if [ $EXIT_CODE -eq 0 ]; then
    echo "  RESULT: ALL TESTS PASSED ✓"
else
    echo "  RESULT: SOME TESTS FAILED ✗  (exit code: $EXIT_CODE)"
fi
echo "══════════════════════════════════════"

exit $EXIT_CODE
