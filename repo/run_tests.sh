#!/usr/bin/env bash
set -euo pipefail

echo "╔══════════════════════════════════════╗"
echo "║       StudioOps Test Runner          ║"
echo "╚══════════════════════════════════════╝"
echo ""

# Auto-create and activate venv if not already in one
if [ -z "${VIRTUAL_ENV:-}" ]; then
    if [ ! -d "venv" ]; then
        echo "→ Creating virtual environment …"
        python3 -m venv venv
    fi
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

echo ""
echo "Running: python3 -m pytest $DIRS -v --tb=short"
echo "──────────────────────────────────────────────────────────────"
echo ""

set +e
python3 -m pytest $DIRS -v --tb=short
EXIT_CODE=$?
set -e

echo ""
echo "══════════════════════════════════════"
if [ $EXIT_CODE -eq 0 ]; then
    echo "  RESULT: ALL TESTS PASSED ✓"
else
    echo "  RESULT: SOME TESTS FAILED ✗  (exit code: $EXIT_CODE)"
fi
echo "══════════════════════════════════════"

exit $EXIT_CODE
