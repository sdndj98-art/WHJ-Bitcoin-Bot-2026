"""Optional Telegram report delivery. Configure secrets in GitHub Actions."""
import json
import os
import sys
import urllib.request
from pathlib import Path


def format_message(report):
    bt = report.get("paper_backtest", {})
    return (
        "WHJ Bitcoin Bot report\n"
        f"Market: {report.get('market', 'BTC/USD')}\n"
        f"Price: {report.get('BTC_price', 'N/A')} USD\n"
        f"Signal: {report.get('signal', 'N/A')}\n"
        f"SMA20 / SMA50: {report.get('SMA20', 'N/A')} / {report.get('SMA50', 'N/A')}\n"
        f"Paper equity: {bt.get('final_equity_usd', 'N/A')} USD\n"
        f"Return: {bt.get('return_pct', 'N/A')}%\n"
        f"Closed paper trades: {bt.get('completed_trades', 0)}\n"
        "Analysis only — no real orders."
    )


def send_message(token, chat_id, message):
    if not token or not chat_id:
        raise ValueError("Telegram token and chat ID are required")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    body = json.dumps({"chat_id": chat_id, "text": message}).encode("utf-8")
    request = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        result = json.loads(response.read().decode("utf-8"))
    if not result.get("ok"):
        raise RuntimeError("Telegram API rejected the notification")
    return True


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        print("Telegram is not configured; notification skipped.")
        return
    report = json.loads(Path("report.json").read_text(encoding="utf-8"))
    send_message(token, chat_id, format_message(report))
    print("Telegram notification sent")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Never print raw exception details: request URLs may contain the bot token.
        print("Telegram notification failed (" + type(exc).__name__ + ").", file=sys.stderr)
        raise SystemExit(1)
