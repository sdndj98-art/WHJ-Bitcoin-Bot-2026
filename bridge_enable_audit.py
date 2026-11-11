#!/usr/bin/env python3
"""One-time, fail-closed installer for the WHJ read-only audit bridge action."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

HOME = Path.home()
REPO = HOME / "WHJ-Bitcoin-Bot-2026"
BRIDGE = HOME / "whj-assist" / "whj_bridge.py"
ASSIST = HOME / "whj-assist" / "whj_assist.py"
BACKUPS = HOME / "whj-assist" / "backups"
AUDIT = HOME / "whj-assist" / "paper_ledger_audit.py"
AUDIT_URL = (
    "https://raw.githubusercontent.com/sdndj98-art/WHJ-Bitcoin-Bot-2026/"
    "d0253c1cc5c2edb2b06fa1588391ae1a063d29c7/paper_ledger_audit.py"
)

def fail(message):
    raise SystemExit("STOP: " + message)

def atomic_write(path: Path, content: str):
    temp = path.with_suffix(path.suffix + ".whj-tmp")
    temp.write_text(content, encoding="utf-8")
    os.replace(temp, path)

def main():
    if not REPO.is_dir() or not (REPO / ".git").exists():
        fail(f"Repository not found: {REPO}")
    for path in (BRIDGE, ASSIST):
        if not path.is_file() or path.is_symlink():
            fail(f"Expected regular local file not found: {path}")

    bridge_text = BRIDGE.read_text(encoding="utf-8")
    assist_text = ASSIST.read_text(encoding="utf-8")
    allowed_pattern = re.compile(
        r'(?m)^(\s*ALLOWED\s*=\s*)\{\s*"status"\s*,\s*"compile"\s*,\s*"tests"\s*\}\s*$'
    )
    if len(allowed_pattern.findall(bridge_text)) != 1:
        fail("Bridge allowlist did not match the known safe version; no files changed.")
    if len(re.findall(r"(?m)^def main\(\):\s*$", assist_text)) != 1:
        fail("Assistant main() did not match the known version; no files changed.")
    if "_whj_main_before_audit" in assist_text or '"audit"' in bridge_text:
        fail("Audit action appears partially installed already; inspect before retrying.")

    request = urllib.request.Request(AUDIT_URL, headers={"User-Agent": "WHJ-Bridge-Audit-Installer"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            audit_text = response.read().decode("utf-8")
    except Exception as exc:
        fail(f"Could not retrieve the pinned audit utility: {exc}")
    required = ('READ_ONLY_PAPER_LEDGER_AUDIT', 'files_modified', 'live_orders_placed', 'def build_audit')
    if not all(marker in audit_text for marker in required):
        fail("Downloaded audit utility failed content validation.")
    if AUDIT.exists() and AUDIT.read_text(encoding="utf-8") != audit_text:
        fail(f"Refusing to overwrite different existing file: {AUDIT}")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    BACKUPS.mkdir(parents=True, exist_ok=True)
    bridge_backup = BACKUPS / f"whj_bridge.py.{stamp}.bak"
    assist_backup = BACKUPS / f"whj_assist.py.{stamp}.bak"
    shutil.copy2(BRIDGE, bridge_backup)
    shutil.copy2(ASSIST, assist_backup)
    audit_created = not AUDIT.exists()

    try:
        patched_bridge = allowed_pattern.sub(r'\1{"status", "compile", "tests", "audit"}', bridge_text, count=1)
        renamed_assist, count = re.subn(
            r"(?m)^def main\(\):\s*$",
            "def _whj_main_before_audit():",
            assist_text,
            count=1,
        )
        if count != 1:
            fail("Could not safely prepare assistant dispatcher.")
        wrapper = '''
def main():
    if len(sys.argv) == 2 and sys.argv[1] == "audit":
        audit_script = Path.home() / "whj-assist" / "paper_ledger_audit.py"
        if not audit_script.is_file():
            print("AUDIT ERROR: read-only audit utility is missing")
            return 2
        try:
            result = subprocess.run(
                [sys.executable, str(audit_script)],
                cwd=REPO,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=120,
            )
            print(result.stdout, end="" if result.stdout.endswith("\\n") else "\\n")
            return result.returncode
        except subprocess.TimeoutExpired:
            print("AUDIT ERROR: timed out after 120 seconds")
            return 124
    return _whj_main_before_audit()

'''
        marker = '\nif __name__ == "__main__":'
        if renamed_assist.count(marker) != 1:
            fail("Could not locate the assistant entrypoint.")
        patched_assist = renamed_assist.replace(marker, "\n" + wrapper + marker, 1)
        if audit_created:
            atomic_write(AUDIT, audit_text)
        atomic_write(BRIDGE, patched_bridge)
        atomic_write(ASSIST, patched_assist)

        checks = subprocess.run(
            [sys.executable, "-m", "py_compile", str(BRIDGE), str(ASSIST), str(AUDIT)],
            cwd=REPO,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if checks.returncode:
            fail("Python compile check failed: " + checks.stdout)
        smoke = subprocess.run(
            [sys.executable, str(ASSIST), "audit"],
            cwd=REPO,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=120,
        )
        if smoke.returncode:
            fail("Local audit smoke test failed: " + smoke.stdout[-4000:])
        print("WHJ_BRIDGE_AUDIT_INSTALL=OK")
        print(f"Backups: {bridge_backup} | {assist_backup}")
        print("Audit utility installed outside the Git repository.")
        print("Read-only local audit smoke test passed; no ledger files were modified.")
        print(smoke.stdout[-6000:])
    except Exception:
        shutil.copy2(bridge_backup, BRIDGE)
        shutil.copy2(assist_backup, ASSIST)
        if audit_created and AUDIT.exists():
            AUDIT.unlink()
        raise

if __name__ == "__main__":
    main()
