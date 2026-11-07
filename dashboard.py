"""Build a self-contained HTML dashboard from report.json."""
import html
import json
from pathlib import Path

SOURCE = Path("report.json")
OUTPUT = Path("dashboard.html")


def build_dashboard(report):
    bt = report.get("paper_backtest", {})
    trades = bt.get("trade_log", [])
    rows = "".join(
        "<tr><td>{}</td><td>{}</td></tr>".format(
            html.escape(str(t.get("result", ""))),
            html.escape(str(t.get("pnl", "")))
        )
        for t in trades[-30:]
    ) or '<tr><td colspan="2">No completed trades yet</td></tr>'

    account = report.get("persistent_paper_account", {})
    fields = [
        ("Persistent paper equity (USD)", account.get("equity_after_estimated_exit_costs_usd", "—")),
        ("Persistent paper return (%)", account.get("return_pct", "—")),
        ("Persistent paper cash (USD)", account.get("cash_usd", "—")),
        ("Persistent paper BTC", account.get("btc_units", "—")),
        ("Persistent paper trades", account.get("completed_trades", "—")),
        ("Persistent paper win rate (%)", account.get("win_rate_pct", "—")),
        ("Persistent paper profit factor", account.get("profit_factor", "—")),
        ("Persistent paper max drawdown (%)", account.get("max_drawdown_pct", "—")),
        ("Persistent paper loss streak", account.get("max_consecutive_losses", "—")),
        ("Persistent paper open position", account.get("open_position", "—")),
        ("Paper account paused", account.get("paused_for_drawdown", "—")),
        ("Daily loss pause", account.get("daily_loss_paused", "—")),
        ("BTC/USD", report.get("BTC_price", "—")),
        ("Signal", report.get("signal", "—")),
        ("SMA 20", report.get("SMA20", "—")),
        ("SMA 50", report.get("SMA50", "—")),
        ("Paper equity (USD)", bt.get("final_equity_usd", "—")),
        ("Return (%)", bt.get("return_pct", "—")),
        ("Max drawdown (%)", bt.get("max_drawdown_pct", "—")),
        ("Completed trades", bt.get("completed_trades", 0)),
        ("Win rate (%)", bt.get("win_rate_pct", 0)),
        ("Average trade P&L (USD)", bt.get("average_trade_pnl_usd", "—")),
        ("Profit factor", bt.get("profit_factor", "—")),
        ("Max consecutive losses", bt.get("max_consecutive_losses", "—")),
        ("Fees paid (USD)", bt.get("fees_paid_usd", "—")),
    ]
    cards = "".join(
        '<article class="metric"><span>{}</span><strong>{}</strong></article>'.format(
            html.escape(str(label)), html.escape(str(value))
        )
        for label, value in fields
    )
    lab = report.get("strategy_lab", {}).get("strategies", {})
    strategy_rows = "".join(
        "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
            html.escape(name),
            html.escape(str(metrics.get("return_pct", "—"))),
            html.escape(str(metrics.get("max_drawdown_pct", "—"))),
            html.escape(str(metrics.get("closed_trades", "—"))),
            html.escape(str(item.get("worst_window_return_pct", "—")))
        )
        for name, item in lab.items()
        for metrics in [item.get("out_of_sample", {})]
    ) or '<tr><td colspan="5">Strategy comparison not available</td></tr>'
    timestamp = html.escape(str(report.get("time", "Unknown")))
    signal = html.escape(str(report.get("signal", "HOLD")))
    return """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>WHJ Bitcoin Bot Dashboard</title>
<style>
:root{color-scheme:dark;font-family:system-ui,sans-serif;background:#101827;color:#eef3fa}
body{margin:0;padding:24px;max-width:1100px;margin:auto}header{margin-bottom:24px}
h1{margin-bottom:4px}.muted{color:#a9b8ca}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}
.metric{background:#1b293b;border:1px solid #30435c;border-radius:12px;padding:18px}
.metric span{display:block;color:#a9b8ca;font-size:13px}.metric strong{display:block;font-size:25px;margin-top:8px;overflow-wrap:anywhere}
section{margin-top:26px;background:#1b293b;border:1px solid #30435c;border-radius:12px;padding:18px}
table{width:100%;border-collapse:collapse}td,th{text-align:left;padding:10px;border-bottom:1px solid #30435c}
.notice{color:#ffd58a}.signal{font-weight:700}.foot{margin-top:24px;color:#a9b8ca;font-size:13px}
</style></head><body>
<header><h1>WHJ Bitcoin Bot</h1><div class="muted">BTC/USD hourly analysis · Updated: """ + timestamp + """</div>
<p class="signal">Current indicator: """ + signal + """</p></header>
<div class="grid">""" + cards + """</div>
<section><h2>Recent simulated trades</h2><table><thead><tr><th>Result</th><th>P&amp;L (USD)</th></tr></thead><tbody>""" + rows + """</tbody></table></section>
<section><h2>Strategy comparison · Out-of-sample</h2><p class="muted">Chronological holdout results; fixed rules, not a guarantee or a strategy recommendation.</p><table><thead><tr><th>Strategy</th><th>Return (%)</th><th>Max drawdown (%)</th><th>Closed trades</th><th>Worst walk-forward window (%)</th></tr></thead><tbody>""" + strategy_rows + """</tbody></table></section>
<p class="foot notice">Simulation only. No real orders are placed. Historical results do not predict future performance and are not financial advice.</p>
</body></html>"""


def main():
    report = json.loads(SOURCE.read_text(encoding="utf-8"))
    OUTPUT.write_text(build_dashboard(report), encoding="utf-8")
    print("Dashboard written to dashboard.html")


if __name__ == "__main__":
    main()
