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
report.scanner_review = {
  status: "WATCH", paper_candidate_only: true, live_orders_placed: false,
  reasons: ["volume_spike_not_confirmed"], confluence_score: 6, confluence_total: 8,
  current_close: 68000, volume_ratio: 1.2
};
report.paper_decision_gates = Object.fromEntries([
  "1h_sma_trend", "1h_ema_trend", "1h_rsi14_mean_reversion"
].map(key => [key, {
  status: "BLOCKED", reasons: ["scanner_candidate_not_approved"],
  paper_only: true, execution_enabled: false, order_placed: false
}]));

assert.equal(validate(report), report, "Valid five-sleeve report should pass");
assert.match(report.cycle_status, /WAITING_FOR_NEW_CLOSED_CANDLES/);
assert.equal(report.gross_exposure_usd, 0);
assert.equal(report.open_positions, 0);

const unsafeDecisionGate = structuredClone(report);
unsafeDecisionGate.paper_decision_gates["1h_sma_trend"].order_placed = true;
assert.throws(() => validate(unsafeDecisionGate), /بوابة GUARD\/SIZER غير صالحة/);
const unsafeScanner = structuredClone(report);
unsafeScanner.scanner_review.live_orders_placed = true;
assert.throws(() => validate(unsafeScanner), /حالة SCANNER أو ضمانات البحث غير صالحة/);
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
const decisionRendererMatch = html.match(/function renderDecisionTools\(x\)\{[\s\S]*?\n\}/);
assert.ok(decisionRendererMatch, "Could not locate SCANNER/GUARD/SIZER renderer");
const context = {
  $: getElement,
  money: (value) => value === undefined || value === null ? "—" : "$" + Number(value).toFixed(2),
  pct: (value) => value === undefined || value === null ? "—" : Number(value).toFixed(2) + "%",
  fmt: (value) => value === undefined || value === null ? "—" : String(value),
  esc: (value) => String(value ?? ""),
  renderDecisionTools: vm.runInNewContext(decisionRendererMatch[0] + "; renderDecisionTools", {
    $: getElement,
    money: (value) => value === undefined || value === null ? "—" : "$" + Number(value).toFixed(2),
    pct: (value) => value === undefined || value === null ? "—" : Number(value).toFixed(2) + "%",
    fmt: (value) => value === undefined || value === null ? "—" : String(value),
    esc: (value) => String(value ?? "")
  })
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
assert.match(getElement("decisionScannerStatus").textContent, /مراقبة فقط/);
assert.equal(getElement("decisionScannerScore").textContent, "6 / 8");
assert.match(getElement("decisionGuardStatus").textContent, /لا يوجد إيقاف مسجل/);
assert.match(getElement("decisionSizerRows").innerHTML, /scanner_candidate_not_approved/);
assert.match(getElement("decisionSizerStatus").textContent, /0 \/ 3 مؤهل للمراجعة الورقية فقط/);

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


assert.match(html, /whjThemeToggle/, "Dashboard must expose a theme switch");
assert.match(html, /whj-compact/, "Dashboard must expose compact layout mode");
assert.match(html, /whjClock/, "Dashboard must show the Baghdad local clock");
assert.match(html, /whjShortcutHelp/, "Dashboard must expose keyboard shortcut help");
assert.match(html, /requestFullscreen/, "Dashboard must support fullscreen mode");
assert.match(html, /aria-current/, "Dashboard navigation must expose its active page accessibly");


assert.match(html, /grid-template-columns:230px minmax\(0,1fr\)/, "Desktop shell must constrain the content column");
assert.match(html, /html,body\{width:100%;max-width:100%;overflow-x:clip\}/, "Dashboard must prevent horizontal viewport drift");
assert.match(html, /main\{min-width:0;width:100%\}/, "Main content must shrink inside the shell");
assert.match(html, /\.tablewrap\{min-width:0;max-width:100%;overflow-x:auto\}/, "Wide tables must scroll inside their own container");
assert.match(html, /\.nav\{width:100%;min-width:0\}/, "Mobile navigation must stay within viewport width");


assert.match(html, /whjCommandOverlay/, "Dashboard must expose a searchable command palette");
assert.match(html, /Ctrl \+ K/, "Dashboard must document the command-palette shortcut");
assert.match(html, /whjAlertPanel/, "Dashboard must expose a live data alert center");
assert.match(html, /latest_closed_candle_age_minutes/, "Dashboard alerts must inspect candle freshness");
assert.match(html, /recent_missing_hour_gaps/, "Dashboard alerts must surface missing candle gaps");
assert.match(html, /whjToast/, "Dashboard must expose accessible status notifications");

console.log("Dashboard forward-report and premium UX tests passed.");


// Isolated ADX forward report validation: four exact sleeves, no live orders, and no historical trades.
const adxMatch = html.match(/function validateAdxForwardReport\(x\)\{[\s\S]*?\n\}\nfunction renderAdxForward\(/);
assert.ok(adxMatch, "Could not locate isolated ADX report validator");
const adxValidatorSource = adxMatch[0].replace(/\nfunction renderAdxForward\($/, "");
const validateAdx = vm.runInNewContext(`${adxValidatorSource}; validateAdxForwardReport`);
const adxKeys = { adx15_4h:[15,4], adx20_4h:[20,4], adx15_6h:[15,6], adx20_6h:[20,6] };
const adxReport = {
  schema_version:1, mode:"ISOLATED_ADX_FORWARD_PAPER_ONLY",
  generated_at_utc:"2026-11-09T00:00:00Z", live_orders_enabled:false,
  existing_paper_ledgers_touched:false,
  allocation:"Separate 500 USD virtual sleeve per timeframe/threshold; not combined with existing accounts",
  data_quality:"VALIDATED_NO_GAPS_NO_IMPUTED_CANDLES",
  results:Object.fromEntries(Object.entries(adxKeys).map(([key,[threshold,timeframe]])=>[key,{
    mode:"FORWARD_ONLY_PAPER_NO_LIVE_ORDERS",strategy:"EMA50_200_ADX14_ENTRY_ONLY",
    threshold,timeframe_hours:timeframe,seeded_without_historical_trades:true,
    processed_new_bars:0,last_processed_timestamp:Math.floor(Date.UTC(2026,10,8,0,0,0)/(timeframe*3600000))*(timeframe*3600000),
    initial_cash_usd:500,equity_usd:500,return_pct:0,closed_trades:0,win_rate_pct:0,
    profit_factor:0,max_drawdown_pct:0,fees_paid_usd:0,open_position:false,
    risk_paused:false,risk_pause_reasons:[],minimum_trades_for_review:30,
    assessment:"INSUFFICIENT_FORWARD_SAMPLE"
  }]))
};
assert.equal(validateAdx(adxReport), adxReport);
const adxBadLive = structuredClone(adxReport); adxBadLive.live_orders_enabled=true;
assert.throws(()=>validateAdx(adxBadLive),/ضمانات العزل/);
const adxMissingSleeve = structuredClone(adxReport); delete adxMissingSleeve.results.adx20_6h;
assert.throws(()=>validateAdx(adxMissingSleeve),/المحافظ الأربع فقط/);
const adxBadIdentity = structuredClone(adxReport); adxBadIdentity.results.adx15_4h.threshold=20;
assert.throws(()=>validateAdx(adxBadIdentity),/هوية المحفظة/);
const adxBadReturn = structuredClone(adxReport); adxBadReturn.results.adx15_4h.return_pct=2;
assert.throws(()=>validateAdx(adxBadReturn),/العائد لا يطابق/);
const adxHistoricalTrades = structuredClone(adxReport); adxHistoricalTrades.results.adx15_4h.closed_trades=1;
assert.throws(()=>validateAdx(adxHistoricalTrades),/تهيئة/);

// Exercise the ADX renderer with a minimal DOM to catch runtime errors.
const adxRenderMatch=html.match(/function renderAdxForward\(x\)\{[\s\S]*?\n\}\n\$\("adxForwardFile"\)/);
assert.ok(adxRenderMatch,"Could not locate ADX renderer");
const adxRendererSource=adxRenderMatch[0].replace(/\n\$\("adxForwardFile"\)$/,"");
const adxElements=new Map();
const adxGet=(id)=>{if(!adxElements.has(id))adxElements.set(id,{textContent:"",innerHTML:""});return adxElements.get(id)};
const adxRender=vm.runInNewContext(`${adxRendererSource}; renderAdxForward`,{
  $:adxGet,fmt:(v)=>v===undefined||v===null?"—":String(v),
  money:(v)=>"$"+Number(v).toFixed(2),pct:(v)=>Number(v).toFixed(2)+"%",
  esc:(v)=>String(v??"")
});
adxRender(adxReport);
assert.equal((adxGet("adxForwardRows").innerHTML.match(/<tr>/g)||[]).length,4);
assert.match(adxGet("adxForwardRows").innerHTML,/ADX15 · 4h/);
assert.match(adxGet("adxForwardSeed").textContent,/تهيئة المحافظ الأربع/);
