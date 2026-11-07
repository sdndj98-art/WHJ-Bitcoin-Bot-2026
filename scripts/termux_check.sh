#!/data/data/com.termux/files/usr/bin/bash
# Read-only Termux diagnostics for WHJ-Bitcoin-Bot-2026.
# Does not install packages, modify paper ledgers, or submit exchange orders.

set -u

ROOT="${HOME}/WHJ-Bitcoin-Bot-2026"
cd "$ROOT" 2>/dev/null || {
  echo "ERROR: project directory not found: $ROOT"
  echo "Clone the repository first, then run this script from the project."
  exit 1
}

echo "========== WHJ TERMUX DIAGNOSTICS =========="
echo "Project: $PWD"
echo

FAILURES=0

if ! command -v python >/dev/null 2>&1; then
  echo "FAIL: Python is not installed."
  echo "Fix: pkg install python"
  exit 1
fi

PY_VERSION="$(python -c 'import sys; print(".".join(map(str, sys.version_info[:3])))' 2>/dev/null)" || {
  echo "FAIL: Python could not start."
  exit 1
}
echo "Python: $PY_VERSION"
python -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'
if [ "$?" -ne 0 ]; then
  echo "FAIL: Python 3.10 or newer is required."
  echo "Fix: pkg upgrade python"
  FAILURES=$((FAILURES + 1))
else
  echo "PASS: Python version requirement"
fi

for file in main.py paper_trading.py paper_account.py strategy_lab.py risk_analysis.py market_scanner.py forward_paper_monitor.py historical_research.py dashboard.py; do
  if [ ! -f "$file" ]; then
    echo "FAIL: missing project file: $file"
    FAILURES=$((FAILURES + 1))
  fi
done

if [ "$FAILURES" -eq 0 ]; then
  echo "PASS: required project files found"
fi

echo
echo "========== PYTHON SYNTAX CHECK =========="
if python -m py_compile ./*.py; then
  echo "PASS: top-level Python files compile"
else
  echo "FAIL: Python syntax/compilation check"
  FAILURES=$((FAILURES + 1))
fi

echo
echo "========== UNIT TESTS =========="
if [ -d tests ]; then
  if python -m unittest discover -s tests -v; then
    echo "PASS: unit tests"
  else
    echo "FAIL: unit tests"
    FAILURES=$((FAILURES + 1))
  fi
else
  echo "FAIL: tests directory is missing"
  FAILURES=$((FAILURES + 1))
fi

echo
echo "========== GIT =========="
if command -v git >/dev/null 2>&1; then
  git --version
  git status --short --branch
  if git remote get-url origin >/dev/null 2>&1; then
    echo "PASS: origin remote is configured"
  else
    echo "WARN: origin remote is not configured"
  fi
else
  echo "WARN: Git is not installed. Fix: pkg install git"
fi

echo
echo "========== GITHUB CLI =========="
if command -v gh >/dev/null 2>&1; then
  gh --version | head -n 1
  if gh auth status >/dev/null 2>&1; then
    echo "PASS: GitHub CLI is authenticated (credentials hidden)"
  else
    echo "WARN: GitHub CLI is not authenticated. Run: gh auth login"
  fi
else
  echo "WARN: GitHub CLI is not installed. Fix: pkg install gh"
fi

echo
echo "========== RESULT =========="
if [ "$FAILURES" -eq 0 ]; then
  echo "PASS: Termux diagnostics completed without test or syntax failures."
  exit 0
fi

echo "FAIL: $FAILURES check(s) need attention. Review the messages above."
exit 1
