#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "[smoke] checking local saved session..."
if ! uv run python -m xhs_cli.cli status >/dev/null 2>&1; then
  echo "[smoke] no valid saved session. run 'uv run python -m xhs_cli.cli login' first."
  exit 1
fi

echo "[smoke] validating session usability via whoami..."
if ! uv run python -m xhs_cli.cli whoami >/dev/null 2>&1; then
  echo "[smoke] saved cookies exist but session is expired/invalid."
  echo "[smoke] run 'uv run python -m xhs_cli.cli login' to refresh auth."
  exit 1
fi

echo "[smoke] probing profile endpoint reachability..."
if ! USER_ID="$(uv run python - <<'PY'
import json
import subprocess
import sys

proc = subprocess.run(
    [sys.executable, "-m", "xhs_cli.cli", "whoami", "--json"],
    capture_output=True,
    text=True,
)
if proc.returncode != 0:
    sys.stderr.write(proc.stdout)
    sys.stderr.write(proc.stderr)
    sys.exit(1)

try:
    data = json.loads(proc.stdout)
except json.JSONDecodeError:
    sys.stderr.write(proc.stdout)
    sys.stderr.write(proc.stderr)
    sys.exit(1)
for key in ("userInfo", "basicInfo", "basic_info"):
    sub = data.get(key, {})
    if isinstance(sub, dict):
        uid = sub.get("userId") or sub.get("user_id")
        if uid:
            print(uid)
            sys.exit(0)
uid = data.get("userId") or data.get("user_id") or data.get("id")
if uid:
    print(uid)
    sys.exit(0)
sys.exit(1)
PY
)"; then
  echo "[smoke] failed to resolve user_id from whoami."
  exit 1
fi

if ! uv run python -m xhs_cli.cli user "$USER_ID" --json >/dev/null 2>&1; then
  echo "[smoke] profile endpoint is blocked (likely security verification / risk control)."
  echo "[smoke] refresh login and retry from a normal network."
  exit 1
fi

MARK_EXPR="integration and not live_mutation"
if [[ "${XHS_SMOKE_MUTATION:-0}" == "1" ]]; then
  MARK_EXPR="integration"
fi

echo "[smoke] running integration smoke tests with marker: $MARK_EXPR"
uv run pytest tests/test_integration.py -v --override-ini="addopts=" -m "$MARK_EXPR" "$@"
