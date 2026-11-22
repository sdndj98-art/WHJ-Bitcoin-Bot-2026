"""Call Gemini as a read-only WHJ development advisor; never execute its suggestions."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash").strip()
REPORT = Path("office/gemini_advisor_report.md")


def main() -> int:
    if not API_KEY:
        print("GEMINI_API_KEY is missing. Add it under repository Actions secrets.")
        return 2

    context = {
        "project": "WHJ trading research terminal",
        "current_mode": "paper trading only",
        "simulated_starting_balance_usd": 100,
        "markets_in_scope": ["crypto", "gold/metals where data is available"],
        "known_constraints": [
            "No live orders or real-money execution",
            "Do not enable or recommend Binance",
            "Do not weaken risk controls to force trades",
            "Do not claim profitability without out-of-sample and forward paper evidence",
            "Only suggest changes that can be validated with tests",
        ],
        "recent_evidence": [
            "Latest multi-asset paper engine workflow completed successfully",
            "Python tests completed successfully",
            "Historical profitability gate has not qualified a strategy yet",
        ],
    }
    prompt = (
        "You are a cautious software QA and quantitative research advisor for WHJ. "
        "Review this limited project status and produce a concise actionable report in Markdown. "
        "Prioritize: (1) likely technical blockers, (2) testable code-quality tasks, "
        "(3) data-quality and realistic fee/slippage checks, (4) paper-forward validation. "
        "Do not invent performance figures, API connectivity, market data, or executed trades. "
        "Do not propose live trading, secrets exposure, risk-limit removal, or guaranteed profit. "
        "Clearly label assumptions and state that the report is advisory only.\n\n"
        "Project context:\n" + json.dumps(context, ensure_ascii=False, indent=2)
    )
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 1600},
    }
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        + MODEL + ":generateContent?key=" + API_KEY
    )
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        # Never print request URL or API key.
        print(f"Gemini API returned HTTP {exc.code}: {body[:1000]}")
        return 1
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"Gemini request failed: {type(exc).__name__}: {exc}")
        return 1

    candidates = data.get("candidates", [])
    parts = candidates[0].get("content", {}).get("parts", []) if candidates else []
    answer = "\n".join(p.get("text", "") for p in parts if p.get("text"))
    if not answer.strip():
        print("Gemini returned no text; check model access and API quota.")
        return 1

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(
        "# WHJ Gemini Development Advisor\n\n"
        f"- Generated (UTC): {datetime.now(timezone.utc).isoformat()}\n"
        f"- Model: {MODEL}\n"
        "- Mode: advisory/read-only; no code was changed and no orders were placed\n\n"
        + answer.strip() + "\n",
        encoding="utf-8",
    )
    print(f"Gemini advisor report created: {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
