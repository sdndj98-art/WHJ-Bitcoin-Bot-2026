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
  cash_usd: 1600,
  btc_units: 0,
  gross_exposure_usd: 0,
  gross_exposure_pct_of_equity: 0,
  fees_paid_usd: 0,
  open_positions: 0,
  return_pct: 0,
  cycle_status: "WAITING_FOR_NEW_CLOSED_CANDLES",
  total_processed_new_candles: 0,
  completed_trades: 0,
  generated_at_utc: "2026-11-07T16:56:55.281047+00:00",
  latest_hourly_candle_timestamp: 1794070000000,
  data_quality: { quality: "HEALTHY" },
  sleeves_summary: Object.fromEntries(keys.map((key, index) => [key, {
    equity_usd: allocations[index],
    win_rate_pct: 0,
    profit_factor: null,
    max_drawdown_pct: 0,
    cash_usd: allocations[index],
    btc_units: 0,
    exposure_usd: 0,
    exposure_pct_of_equity: 0,
    fees_paid_usd: 0,
    current_consecutive_losses: 0,
    open_position: false,
    return_pct: 0,
    completed_trades: 0,
    processed_new_candles: 0,
    risk_pause_reasons: [],
    health_assessment: {
      status: "INSUFFICIENT_FORWARD_SAMPLE",
      live_trading_eligible: false,
      rolling_status: "INSUFFICIENT_ROLLING_SAMPLE"
    }
  }]))
};

assert.equal(validate(report), report, "Valid five-sleeve report should pass");
assert.match(report.cycle_status, /WAITING_FOR_NEW_CLOSED_CANDLES/);
assert.equal(report.gross_exposure_usd, 0);
assert.equal(report.open_positions, 0);
const inconsistentExposure = structuredClone(report);
inconsistentExposure.gross_exposure_usd = 10;
assert.throws(() => validate(inconsistentExposure), /تفاصيل الحسابات لا تطابق إجمالي التعرّض والسيولة/);
const inconsistentExposureRatio = structuredClone(report);
inconsistentExposureRatio.gross_exposure_pct_of_equity = 1;
assert.throws(() => validate(inconsistentExposureRatio), /نسبة التعرّض الإجمالية/);
const inconsistentCycle = structuredClone(report);
inconsistentCycle.total_processed_new_candles = 1;
assert.throws(() => validate(inconsistentCycle), /إجمالي الشموع المعالجة/);

// The three 1h accounts must be included in aggregate equity and trade totals.
const missingOneHourEquity = structuredClone(report);
missingOneHourEquity.sleeves_summary["1h_sma_trend"].equity_usd = 199;
assert.throws(() => validate(missingOneHourEquity), /إجماليات الحسابات/);

const missingOneHourTrade = structuredClone(report);
missingOneHourTrade.sleeves_summary["1h_ema_trend"].completed_trades = 1;
assert.throws(() => validate(missingOneHourTrade), /إجماليات الحسابات/);

const invalidWinRate = structuredClone(report);
invalidWinRate.sleeves_summary["1h_sma_trend"].win_rate_pct = 101;
assert.throws(() => validate(invalidWinRate), /بيانات الاستراتيجيات الخمس/);
const invalidDrawdown = structuredClone(report);
invalidDrawdown.sleeves_summary["4h"].max_drawdown_pct = 101;
assert.throws(() => validate(invalidDrawdown), /بيانات الاستراتيجيات الخمس/);
const invalidPosition = structuredClone(report);
invalidPosition.sleeves_summary["6h"].btc_units = 0.01;
assert.throws(() => validate(invalidPosition), /بيانات الاستراتيجيات الخمس/);
const promotedHealth = structuredClone(report);
promotedHealth.sleeves_summary["1h_ema_trend"].health_assessment.live_trading_eligible = true;
assert.throws(() => validate(promotedHealth), /بيانات الاستراتيجيات الخمس/);
const missingHealth = structuredClone(report);
delete missingHealth.sleeves_summary["1h_rsi14_mean_reversion"].health_assessment;
assert.throws(() => validate(missingHealth), /بيانات الاستراتيجيات الخمس/);

const incorrectPortfolioStatus = structuredClone(report);
incorrectPortfolioStatus.status = "REVIEW_REQUIRED";
assert.throws(() => validate(incorrectPortfolioStatus), /حالة المحفظة لا تطابق حالات الاستراتيجيات الخمس/);
const incorrectPausedStatus = structuredClone(report);
incorrectPausedStatus.sleeves_summary["4h"].health_assessment.status = "RISK_PAUSED";
assert.throws(() => validate(incorrectPausedStatus), /حالة المحفظة لا تطابق حالات الاستراتيجيات الخمس/);

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
assert.match(getElement("forwardCycle").textContent, /لا توجد شموع ساعة مغلقة جديدة/);
assert.match(getElement("forwardRows").innerHTML, /1h · SMA Trend/);
assert.match(getElement("forwardRows").innerHTML, /\$2\.50/);
assert.match(getElement("forwardRows").innerHTML, /4\.25%/);
assert.match(getElement("forwardRows").innerHTML, /\$0\.00/);
assert.equal(getElement("forwardExposure").textContent, "$0.00 · 0.00%");
assert.equal(getElement("forwardOpenPositions").textContent, "0");
assert.equal(getElement("forwardFees").textContent, "$0.00");
assert.equal((getElement("forwardRows").innerHTML.match(/<tr>/g) || []).length, 5);


const pauseMatch = html.match(/function paperRiskPauseLabel\(a\)\{[\s\S]*?\n\}/);
assert.ok(pauseMatch, "Could not locate paper risk pause label helper");
const paperRiskPauseLabel = vm.runInNewContext(`(${pauseMatch[0]})`);
assert.equal(paperRiskPauseLabel({}), "محاكاة");
assert.equal(paperRiskPauseLabel({ paused_for_drawdown: true }), "متوقف: تراجع الحساب");
assert.equal(
  paperRiskPauseLabel({ daily_loss_paused: true, paused_for_loss_streak: true, paused_for_strategy_health: true }),
  "متوقف: الخسارة اليومية، خسائر متتالية، تراجع صحة الاستراتيجية"
);
assert.equal(
  paperRiskPauseLabel({ paused_for_drawdown: true, daily_loss_paused: true, paused_for_loss_streak: true, paused_for_strategy_health: true }),
  "متوقف: تراجع الحساب، الخسارة اليومية، خسائر متتالية، تراجع صحة الاستراتيجية"
);
assert.match(html, /paperRiskPauseLabel\(x\)/, "Portfolio table must use the complete risk-pause label");

console.log("Dashboard forward-report validation and rendering tests passed (five sleeves, aggregates, and runtime rendering).");
