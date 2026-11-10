#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

cd "$(dirname "$0")/.." || exit 1
CONFIG="$HOME/.config/whj-bridge"
TOKEN_FILE="$CONFIG/github_token"
mkdir -p "$CONFIG"
chmod 700 "$CONFIG"
umask 077

echo "Create a fine-grained GitHub token for ONLY sdndj98-art/WHJ-Bitcoin-Bot-2026."
echo "Required permissions: Contents (Read and write), Issues (Read and write)."
echo "Metadata remains read-only. Do not paste the token into ChatGPT."
read -r -s -p "Paste token here (input hidden): " TOKEN
echo
case "$TOKEN" in
  github_pat_*|ghp_*) ;;
  *) echo "Unexpected token format; expected a fine-grained or classic GitHub token."; unset TOKEN; exit 1 ;;
esac
printf '%s' "$TOKEN" > "$TOKEN_FILE"
chmod 600 "$TOKEN_FILE"
unset TOKEN

echo "===== VALIDATING TOKEN ====="
python - <<'PY'
import json
import os
import urllib.request
from pathlib import Path

p = Path.home() / ".config" / "whj-bridge" / "github_token"
token = p.read_text().strip()
req = urllib.request.Request(
    "https://api.github.com/repos/sdndj98-art/WHJ-Bitcoin-Bot-2026",
    headers={
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json",
        "User-Agent": "WHJ-Termux-Bridge/1.0",
        "X-GitHub-Api-Version": "2022-11-28",
    },
)
try:
    with urllib.request.urlopen(req, timeout=20) as response:
        data = json.loads(response.read().decode())
    print("Token accepted by GitHub.")
    print("Repository:", data.get("full_name"))
    print("Default branch:", data.get("default_branch"))
    print("Push permission:", (data.get("permissions") or {}).get("push", "not reported"))
except Exception as exc:
    print("Token validation failed:", type(exc).__name__)
    raise SystemExit(1)
PY

echo "===== ONE-SHOT BRIDGE CHECK ====="
python whj_bridge_agent.py --once

echo "===== STARTING BRIDGE ====="
if pgrep -f '[w]hj_bridge_agent.py' >/dev/null; then
  echo "Bridge agent is already running."
else
  if command -v termux-wake-lock >/dev/null 2>&1; then
    termux-wake-lock || true
  fi
  nohup python -u whj_bridge_agent.py \
    > "$CONFIG/agent.log" 2>&1 </dev/null &
  echo "Bridge PID: $!"
fi
sleep 2
tail -20 "$CONFIG/agent.log" 2>/dev/null || true
echo "Setup complete. Keep the token private."
