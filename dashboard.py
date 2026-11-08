"""Build a self-contained HTML dashboard from report.json."""
import html
import json
import math
import time
from pathlib import Path

SOURCE = Path("report.json")
OUTPUT = Path("dashboard.html")

CVD_STATE_SOURCE = Path("state/kraken_cvd_btc_usd.json")


def summarize_cvd_state(state, now_ns=None, stale_after_seconds=180):
    """Validate a persisted CVD state and derive dashboard-only freshness metrics."""
    if not isinstance(state, dict):
        return {"status": "INVALID_STATE", "message": "CVD state must be a JSON object"}
    try:
        count = state.get("processed_trade_count")
        last_id = state.get("last_trade_id", 0)
        if isinstance(state.get("cumulative_buy_volume", 0.0), bool) or isinstance(state.get("cumulative_sell_volume", 0.0), bool):
            raise ValueError("invalid cumulative volume")
        buy = float(state.get("cumulative_buy_volume", 0.0))
        sell = float(state.get("cumulative_sell_volume", 0.0))
        timestamp_ns = state.get("last_trade_timestamp_ns")
        if timestamp_ns is None and state.get("last_trade_timestamp") is not None:
            legacy_timestamp = float(state["last_trade_timestamp"])
            if not math.isfinite(legacy_timestamp) or legacy_timestamp < 0:
                raise ValueError("invalid legacy trade timestamp")
            timestamp_ns = int(legacy_timestamp * 1_000_000_000)
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError("invalid processed trade count")
        if isinstance(last_id, bool) or not isinstance(last_id, int) or last_id < 0:
            raise ValueError("invalid last trade ID")
        if not math.isfinite(buy) or not math.isfinite(sell) or buy < 0 or sell < 0:
            raise ValueError("invalid cumulative volume")
        if timestamp_ns is not None and (
            isinstance(timestamp_ns, bool) or not isinstance(timestamp_ns, int) or timestamp_ns < 0
        ):
            raise ValueError("invalid nanosecond timestamp")
    except (TypeError, ValueError, OverflowError) as exc:
        return {"status": "INVALID_STATE", "message": str(exc)}

    if count == 0 or timestamp_ns is None:
        return {
            "status": "NO_TRADES",
            "pair": state.get("symbol", "—"),
            "processed_trade_count": count,
            "last_trade_id": last_id,
        }

    if isinstance(stale_after_seconds, bool) or not isinstance(stale_after_seconds, (int, float)) or not math.isfinite(stale_after_seconds) or stale_after_seconds <= 0:
        raise ValueError("stale_after_seconds must be positive")
    now_ns = time.time_ns() if now_ns is None else now_ns
    if isinstance(now_ns, bool) or not isinstance(now_ns, int) or now_ns < 0:
        raise ValueError("now_ns must be a non-negative integer")
    age = (now_ns - timestamp_ns) / 1_000_000_000.0
    total = buy + sell
    delta = buy - sell
    delta_pct = delta / total if total else 0.0
    bias = (
        "BUY_PRESSURE" if delta_pct >= 0.10 else
        "SELL_PRESSURE" if delta_pct <= -0.10 else
        "BALANCED"
    )
    if age < -30:
        freshness = "CLOCK_SKEW"
    elif age > stale_after_seconds:
        freshness = "STALE"
    else:
        freshness = "FRESH"
    return {
        "status": freshness,
        "pair": state.get("symbol", "—"),
        "last_trade_id": last_id,
        "processed_trade_count": count,
        "cumulative_buy_volume": round(buy, 12),
        "cumulative_sell_volume": round(sell, 12),
        "cumulative_delta": round(delta, 12),
        "cumulative_delta_pct": round(delta_pct * 100.0, 4),
        "cumulative_bias": bias,
        "last_trade_age_seconds": round(max(age, 0.0), 3),
        "stale_after_seconds": stale_after_seconds,
    }


def load_dashboard_cvd_state(path=CVD_STATE_SOURCE):
    """Read the optional BTC/USD collector state without resetting corrupt files."""
    try:
        state = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"status": "NOT_RUNNING", "message": "No saved CVD state"}
    except (OSError, json.JSONDecodeError) as exc:
        return {"status": "INVALID_STATE", "message": str(exc)}
    return summarize_cvd_state(state)



def build_dashboard(report):
    cvd = report.get("kraken_cvd", {"status": "NOT_RUNNING", "message": "No saved CVD state"})
    cvd_fields = [
        ("Status / freshness", cvd.get("status", "UNKNOWN")),
        ("Trading pair", cvd.get("pair", "—")),
        ("Cumulative buy volume", cvd.get("cumulative_buy_volume", "—")),
        ("Cumulative sell volume", cvd.get("cumulative_sell_volume", "—")),
        ("Cumulative delta", cvd.get("cumulative_delta", "—")),
        ("Cumulative delta (%)", cvd.get("cumulative_delta_pct", "—")),
        ("CVD pressure", cvd.get("cumulative_bias", "—")),
        ("Last trade ID", cvd.get("last_trade_id", "—")),
        ("Processed trades", cvd.get("processed_trade_count", "—")),
        ("Last trade age (seconds)", cvd.get("last_trade_age_seconds", "—")),
        ("Collector note", cvd.get("message", "Read-only public market data")),
    ]
    cvd_rows = "".join(
        "<tr><th>{}</th><td>{}</td></tr>".format(
            html.escape(str(label)), html.escape(str(value))
        )
        for label, value in cvd_fields
    )

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
    quality = report.get("market_data_quality", {})
    fields = [
        ("Market data status", quality.get("quality_status", "UNKNOWN")),
        ("Market data fresh", quality.get("latest_candle_fresh", "—")),
        ("Latest candle age (minutes)", quality.get("latest_closed_candle_age_minutes", "—")),
        ("Recent missing hourly gaps", quality.get("recent_missing_hour_gaps", "—")),
        ("Data quality block reasons", ", ".join(quality.get("quality_block_reasons", [])) or "None"),
        ("Persistent paper equity (USD)", account.get("equity_after_estimated_exit_costs_usd", "—")),
        ("Persistent paper return (%)", account.get("return_pct", "—")),
        ("Persistent paper cash (USD)", account.get("cash_usd", "—")),
        ("Persistent paper BTC", account.get("btc_units", "—")),
        ("Persistent paper trades", account.get("completed_trades", "—")),
        ("Persistent paper win rate (%)", account.get("win_rate_pct", "—")),
        ("Persistent paper profit factor", account.get("profit_factor", "—")),
        ("Persistent paper max drawdown (%)", account.get("max_drawdown_pct", "—")),
        ("Monte Carlo risk status", report.get("monte_carlo_risk", {}).get("status", "—")),
        ("Monte Carlo 5th percentile equity (USD)", report.get("monte_carlo_risk", {}).get("p05_final_equity_usd", "—")),
        ("Monte Carlo median equity (USD)", report.get("monte_carlo_risk", {}).get("median_final_equity_usd", "—")),
        ("Monte Carlo 95th percentile drawdown (%)", report.get("monte_carlo_risk", {}).get("p95_max_drawdown_pct", "—")),
        ("Monte Carlo probability of loss (%)", report.get("monte_carlo_risk", {}).get("probability_of_loss_pct", "—")),
        ("Monte Carlo probability of 50% capital loss (%)", report.get("monte_carlo_risk", {}).get("probability_of_50pct_capital_loss_pct", "—")),
        ("Block bootstrap risk status", report.get("block_bootstrap_risk", {}).get("status", "—")),
        ("Block bootstrap size (trades)", report.get("block_bootstrap_risk", {}).get("block_size", "—")),
        ("Block bootstrap P05 equity (USD)", report.get("block_bootstrap_risk", {}).get("p05_final_equity_usd", "—")),
        ("Block bootstrap P95 drawdown (%)", report.get("block_bootstrap_risk", {}).get("p95_max_drawdown_pct", "—")),
        ("Block bootstrap probability of loss (%)", report.get("block_bootstrap_risk", {}).get("probability_of_loss_pct", "—")),
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
    portfolio = report.get("persistent_paper_portfolio", {}).get("accounts", {})
    paper_strategy_rows = "".join(
        "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
            html.escape(name),
            html.escape(str(item.get("equity_after_estimated_exit_costs_usd", "—"))),
            html.escape(str(item.get("return_pct", "—"))),
            html.escape(str(item.get("max_drawdown_pct", "—"))),
            html.escape(str(item.get("completed_trades", "—"))),
            html.escape(str(item.get("fees_paid_usd", "—"))),
            html.escape(str(item.get("open_position", "—"))),
            html.escape(str(item.get("paused_for_drawdown", "—"))),
            html.escape(str(item.get("daily_loss_paused", "—"))),
            html.escape(str(item.get("paused_for_loss_streak", "—"))),
            html.escape(str(item.get("paused_for_strategy_health", "—")))
        )
        for name, item in portfolio.items()
    ) or '<tr><td colspan="11">Persistent paper portfolio not available</td></tr>'
    lab = report.get("strategy_lab", {}).get("strategies", {})
    strategy_rows = "".join(
        "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
            html.escape(name),
            html.escape(str(metrics.get("return_pct", "—"))),
            html.escape(str(metrics.get("max_drawdown_pct", "—"))),
            html.escape(str(metrics.get("closed_trades", "—"))),
            html.escape(str(item.get("worst_window_return_pct") if item.get("worst_window_return_pct") is not None else "—"))
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
<section><h2>Kraken CVD · Public market feed</h2><p class="muted">Read-only cumulative aggressor buy/sell volume. Freshness is based on the saved trade timestamp; stale or missing data is not a trading signal.</p><table><tbody>""" + cvd_rows + """</tbody></table></section>
<section><h2>Recent simulated trades</h2><table><thead><tr><th>Result</th><th>P&amp;L (USD)</th></tr></thead><tbody>""" + rows + """</tbody></table></section>
<section><h2>Strategy comparison · Out-of-sample</h2><p class="muted">Chronological holdout results; fixed rules, not a guarantee or a strategy recommendation.</p><table><thead><tr><th>Strategy</th><th>Return (%)</th><th>Max drawdown (%)</th><th>Closed trades</th><th>Worst walk-forward window (%)</th></tr></thead><tbody>""" + strategy_rows + """</tbody></table></section>
<section><h2>Persistent paper strategy race</h2><p class="muted">Independent simulated accounts with identical initial capital, fees, slippage, sizing and risk limits. Equity includes estimated liquidation costs.</p><table><thead><tr><th>Strategy</th><th>Equity (USD)</th><th>Return (%)</th><th>Max drawdown (%)</th><th>Closed trades</th><th>Fees (USD)</th><th>Open position</th><th>Drawdown paused</th><th>Daily loss paused</th><th>Loss streak paused</th><th>Strategy health paused</th></tr></thead><tbody>""" + paper_strategy_rows + """</tbody></table></section>
<section><h2>Monte Carlo trade-risk diagnostic</h2><p class="muted">IID and circular moving-block bootstrap resampling of completed backtest trades. The block method retains short local sequences but cannot reliably estimate dependence from a small sample. Percentiles are diagnostics, not forecasts.</p></section>
<p class="foot notice">Simulation only. No real orders are placed. Historical results do not predict future performance and are not financial advice.</p>
</body></html>"""


def main():
    report = json.loads(SOURCE.read_text(encoding="utf-8"))
    report["kraken_cvd"] = load_dashboard_cvd_state()
    OUTPUT.write_text(build_dashboard(report), encoding="utf-8")
    print("Dashboard written to dashboard.html")


if __name__ == "__main__":
    main()
