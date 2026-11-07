const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const html = fs.readFileSync("web/index.html", "utf8");
const match = html.match(/function validateForwardReport\(x\)\{[\s\S]*?\n\}\nfunction renderForward\(/);
assert.ok(match, "Could not locate validateForwardReport in dashboard");
const validatorSource = match[0].replace(/\nfunction renderForward\($/, "");
const validate = vm.runInNewContext(`${validatorSource}; validateForwardReport`);

const keys = ["1h_sma_trend", "1h_ema_trend", "1h_rsi14_mean_reversion", "4h", "6h"];
const allocations = [200, 200, 200, 500, 500];
const report = {
  schema_version: 1,
  mode: "FORWARD_ONLY_PAPER_NO_LIVE_ORDERS",
  status: "PAPER_MONITORING",
  initial_cash_usd: 1600,
  equity_after_estimated_exit_costs_usd: 1600,
  return_pct: 0,
  completed_trades: 0,
  generated_at_utc: "2026-11-07T16:56:55.281047+00:00",
  latest_hourly_candle_timestamp: 1794070000000,
  data_quality: { quality: "HEALTHY" },
  sleeves_summary: Object.fromEntries(keys.map((key, index) => [key, {
    equity_usd: allocations[index],
    return_pct: 0,
    completed_trades: 0,
    risk_pause_reasons: [],
    health_assessment: {
      status: "INSUFFICIENT_FORWARD_SAMPLE",
      live_trading_eligible: false,
      rolling_status: "INSUFFICIENT_ROLLING_SAMPLE"
    }
  }]))
};

assert.equal(validate(report), report, "Valid five-sleeve report should pass");

// The three 1h accounts must be included in aggregate equity and trade totals.
const missingOneHourEquity = structuredClone(report);
missingOneHourEquity.sleeves_summary["1h_sma_trend"].equity_usd = 199;
assert.throws(() => validate(missingOneHourEquity), /إجماليات الحسابات/);

const missingOneHourTrade = structuredClone(report);
missingOneHourTrade.sleeves_summary["1h_ema_trend"].completed_trades = 1;
assert.throws(() => validate(missingOneHourTrade), /إجماليات الحسابات/);

// Execute the actual renderer with a minimal DOM. This catches runtime-only scope errors.
const renderMatch = html.match(/function renderForward\(x\)\{[\s\S]*?\n\}\n\$\("forwardFile"\)/);
assert.ok(renderMatch, "Could not locate renderForward in dashboard");
const rendererSource = renderMatch[0].replace(/\n\$\("forwardFile"\)$/, "");
const elements = new Map();
const getElement = (id) => {
  if (!elements.has(id)) elements.set(id, { textContent: "", className: "", innerHTML: "" });
  return elements.get(id);
};
const context = {
  $: getElement,
  money: (value) => value === undefined || value === null ? "—" : "$" + Number(value).toFixed(2),
  pct: (value) => value === undefined || value === null ? "—" : Number(value).toFixed(2) + "%",
  fmt: (value) => value === undefined || value === null ? "—" : String(value),
  esc: (value) => String(value ?? "")
};
const render = vm.runInNewContext(`${rendererSource}; renderForward`, context);
const renderableReport = structuredClone(report);
for (const key of keys) {
  renderableReport.sleeves_summary[key].health_assessment.rolling_net_pnl_usd = 2.5;
  renderableReport.sleeves_summary[key].health_assessment.rolling_max_drawdown_pct = 4.25;
}
render(renderableReport);
assert.match(getElement("forwardRows").innerHTML, /1h · SMA Trend/);
assert.match(getElement("forwardRows").innerHTML, /\$2\.50/);
assert.match(getElement("forwardRows").innerHTML, /4\.25%/);
assert.equal((getElement("forwardRows").innerHTML.match(/<tr>/g) || []).length, 5);

console.log("Dashboard forward-report validation and rendering tests passed (five sleeves, aggregates, and runtime rendering).");
