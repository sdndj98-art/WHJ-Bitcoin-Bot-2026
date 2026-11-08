import unittest
from collections import Counter
from html.parser import HTMLParser
from dashboard import build_dashboard, summarize_cvd_state
from pathlib import Path


class DashboardContractParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.nav_views = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if "id" in values:
            self.ids.append(values["id"])
        if tag == "button" and values.get("data-view"):
            self.nav_views.append(values["data-view"])


class DashboardContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path("web/index.html").read_text(encoding="utf-8")
        cls.parser = DashboardContractParser()
        cls.parser.feed(cls.source)

    def test_multi_agent_command_center_is_present_and_paper_only(self):
        required = {
            "agents", "agentReportState", "agentReportTime",
            "agentTradeCount", "agentDataQuality",
        }
        self.assertTrue(required.issubset(set(self.parser.ids)))
        self.assertIn('data-view="agents"', self.source)
        for label in ("SCANNER", "GUARD", "SIZER", "EXECUTOR", "LOGGER", "EQUITY"):
            self.assertIn(label, self.source)
        self.assertIn("لا تتحول إشارة الماسح وحدها إلى أمر تداول", self.source)
        self.assertIn("ليست ستة وكلاء ذكاء اصطناعي مستقلين", self.source)
        self.assertIn("التداول الحقيقي", self.source)
        self.assertIn("محاكاة ورقية فقط", self.source)

    def test_generated_dashboard_displays_all_paper_risk_pause_reasons(self):
        report = {
            "persistent_paper_portfolio": {
                "accounts": {
                    "sma_trend": {
                        "equity_after_estimated_exit_costs_usd": 1000.0,
                        "return_pct": 0.0,
                        "max_drawdown_pct": 0.0,
                        "completed_trades": 0,
                        "fees_paid_usd": 0.0,
                        "open_position": False,
                        "paused_for_drawdown": False,
                        "daily_loss_paused": False,
                        "paused_for_loss_streak": True,
                        "paused_for_strategy_health": True,
                    }
                }
            }
        }
        rendered = build_dashboard(report)
        self.assertIn("<th>Loss streak paused</th>", rendered)
        self.assertIn("<th>Strategy health paused</th>", rendered)
        self.assertIn("<td>True</td><td>True</td>", rendered)



    def test_cvd_panel_displays_read_only_metrics_and_escapes_values(self):
        rendered = build_dashboard({
            "kraken_cvd": {
                "status": "FRESH",
                "pair": "BTC/USD <script>",
                "cumulative_buy_volume": 12.5,
                "cumulative_sell_volume": 4.0,
                "cumulative_delta": 8.5,
                "cumulative_delta_pct": 51.515,
                "cumulative_bias": "BUY_PRESSURE",
                "last_trade_id": 12345,
                "processed_trade_count": 99,
                "last_trade_age_seconds": 2.5,
            }
        })
        self.assertIn("Kraken CVD · Public market feed", rendered)
        self.assertIn("BUY_PRESSURE", rendered)
        self.assertIn("BTC/USD &lt;script&gt;", rendered)
        self.assertNotIn("BTC/USD <script>", rendered)
        self.assertIn("Freshness is based on the saved trade timestamp", rendered)

    def test_cvd_state_summary_marks_fresh_stale_and_clock_skew(self):
        now = 1_800_000_000_000_000_000
        state = {
            "symbol": "BTC/USD",
            "processed_trade_count": 10,
            "last_trade_id": 10,
            "cumulative_buy_volume": 3.0,
            "cumulative_sell_volume": 1.0,
            "last_trade_timestamp_ns": now - 30_000_000_000,
        }
        fresh = summarize_cvd_state(state, now_ns=now)
        self.assertEqual(fresh["status"], "FRESH")
        self.assertEqual(fresh["cumulative_delta"], 2.0)
        self.assertEqual(fresh["cumulative_bias"], "BUY_PRESSURE")
        stale = summarize_cvd_state(
            {**state, "last_trade_timestamp_ns": now - 181_000_000_000},
            now_ns=now,
        )
        self.assertEqual(stale["status"], "STALE")
        skew = summarize_cvd_state(
            {**state, "last_trade_timestamp_ns": now + 60_000_000_000},
            now_ns=now,
        )
        self.assertEqual(skew["status"], "CLOCK_SKEW")

    def test_cvd_state_summary_rejects_corrupt_metrics_and_handles_empty_state(self):
        self.assertEqual(
            summarize_cvd_state({"processed_trade_count": 0})["status"],
            "NO_TRADES",
        )
        invalid = summarize_cvd_state({
            "processed_trade_count": 2,
            "last_trade_id": 2,
            "cumulative_buy_volume": float("nan"),
            "cumulative_sell_volume": 1,
            "last_trade_timestamp_ns": 100,
        })
        self.assertEqual(invalid["status"], "INVALID_STATE")

    def test_navigation_targets_exist_and_ids_are_unique(self):
        ids = set(self.parser.ids)
        duplicates = [key for key, count in Counter(self.parser.ids).items() if count > 1]
        self.assertEqual(duplicates, [], "Dashboard HTML contains duplicate element IDs")
        self.assertTrue(self.parser.nav_views, "Dashboard navigation is missing")
        for target in self.parser.nav_views:
            self.assertIn(target, ids, f"Navigation target #{target} has no matching view")

    def test_scanner_view_exposes_six_confirmation_gates_and_indicator_context(self):
        required = {
            "gateQuality", "gateVolume", "gateBreakout", "gateBreakoutQuality",
            "gateTrend", "gateRsi", "gateCandle", "scannerBreakoutQuality",
            "scannerBreakoutClearance", "scannerUpperWick", "scannerTrend", "scannerRsi", "scannerCandle",
            "scannerEma20", "scannerEma50", "scannerRsiValue", "scannerAtr",
            "scannerRiskStop", "scannerRiskTarget", "scannerRiskRatio",
            "scannerTimeframeRows", "scannerMtfConsensus",
            "scannerAtrPct", "scannerClosePosition", "scannerScore",
            "scannerMtfAverage", "scannerStrongestTf", "scannerTrendTfCount",
            "scannerBreakoutTfCount", "harmonicPattern", "harmonicDirection",
            "supplyZone", "demandZone", "supplyDistance", "demandDistance",
            "rsiDivergence", "divergenceRsi", "zoneStatus",
        }
        self.assertTrue(required.issubset(set(self.parser.ids)))
        self.assertIn("7 GATES", self.source)
        self.assertIn("confluence_score", self.source)
        self.assertIn("breakout_quality_confirmed", self.source)
        self.assertIn("breakout_upper_wick_rejection_risk", self.source)
        self.assertIn("EMA20 و EMA50", self.source)
        self.assertIn("RSI", self.source)
        self.assertIn("ATR", self.source)
        self.assertIn("وقف افتراضي بحثي (1.5 ATR)", self.source)
        self.assertIn("هدف افتراضي بحثي (3 ATR)", self.source)
        self.assertIn("hypothetical_risk_map", self.source)
        self.assertIn("رادار توافق الأطر الزمنية", self.source)
        self.assertIn("market_scanner_multi_timeframe", self.source)
        self.assertIn("شموع مكتملة فقط", self.source)
        self.assertIn("renderHarmonicResearch", self.source)
        self.assertIn("harmonic_supply_demand_divergence", self.source)
        self.assertIn("الهارمونيك والعرض والطلب", self.source)

    def test_forward_monitor_view_has_required_controls(self):
        required = {
            "forward", "forwardFile", "clearForward", "forwardMessage",
            "forwardStatus", "forwardInitial", "forwardEquity", "forwardReturn",
            "forwardTrades", "forwardCash", "forwardExposure", "forwardOpenPositions", "forwardFees", "forwardRows", "forwardAllocation", "forwardMaxDD",
            "forwardDaily", "forwardStreak", "forwardQuality", "forwardCandle", "forwardCycle",
        }
        self.assertTrue(required.issubset(set(self.parser.ids)))
        self.assertIn("function validateForwardReport(x)", self.source)
        self.assertIn("function renderForward(x)", self.source)
        self.assertIn("function resetForwardView()", self.source)
        self.assertIn("تقييم الاستراتيجية", self.source)
        self.assertIn("CONTINUE_PAPER_REVIEW", self.source)
        self.assertIn("REVIEW_REQUIRED", self.source)
        self.assertIn("ROLLING_REVIEW_REQUIRED", self.source)
        self.assertIn("صافي آخر الصفقات", self.source)
        for sleeve in ("1h_sma_trend", "1h_ema_trend", "1h_rsi14_mean_reversion", "4h", "6h"):
            self.assertIn(sleeve, self.source)
        self.assertIn("خمسة حسابات مستقلة", self.source)
        self.assertIn("تفاصيل الاستراتيجيات الخمس", self.source)
        self.assertIn("التعرّض السوقي الإجمالي", self.source)
        self.assertIn("تفاصيل الحسابات لا تطابق إجمالي التعرّض والسيولة", self.source)

    def test_mt5_dashboard_import_is_local_validated_and_paper_only(self):
        required = {
            "mt5", "mt5SnapshotFile", "clearMt5", "mt5Message", "mt5Status",
            "mt5Symbol", "mt5Bid", "mt5Ask", "mt5Spread", "mt5Quality",
            "mt5Scanner", "mt5Score", "mt5PaperMode", "mt5TimeframeRows",
            "mt5PaperInitial", "mt5PaperEquity", "mt5PaperReturn",
            "mt5PaperTrades", "mt5PaperRows",
        }
        self.assertTrue(required.issubset(set(self.parser.ids)))
        self.assertIn('data-view="mt5"', self.source)
        self.assertIn("function validateMt5Snapshot(x)", self.source)
        self.assertIn("function renderMt5()", self.source)
        self.assertIn("MT5_MARKET_DATA_PAPER_ONLY", self.source)
        self.assertIn("لا يتم إرسالها إلى الخادم", self.source)
        self.assertIn("لا توجد أوامر لدى الوسيط", self.source)

    def test_forward_report_freshness_is_visible_and_old_reports_are_flagged(self):
        self.assertIn('id="forwardFreshness"', self.source)
        self.assertIn("reportAgeMinutes", self.source)
        self.assertIn("التقرير قديم جداً", self.source)
        self.assertIn("التقرير متأخر", self.source)
        self.assertIn("التقرير حديث", self.source)

    def test_market_regime_diagnostics_are_visible_and_caveated(self):
        self.assertIn("regimeRows", set(self.parser.ids))
        self.assertIn("تحليل الاستراتيجيات حسب حالة السوق", self.source)
        self.assertIn("ليس ربح صفقات فعلياً", self.source)
        self.assertIn("strategy_signal_diagnostics", self.source)
        self.assertIn("فاصل الثقة 95%", self.source)
        self.assertIn("positive_active_forward_bar_ci95_pct", self.source)

    def test_forward_report_is_paper_only_and_consistency_checked(self):
        self.assertIn("FORWARD_ONLY_PAPER_NO_LIVE_ORDERS", self.source)
        self.assertIn("إجماليات الحسابات لا تطابق ملخص المحفظة", self.source)
        self.assertIn("نسبة العائد لا تطابق قيمة المحفظة", self.source)
        self.assertIn('x.data_quality.quality!=="HEALTHY"', self.source)
        self.assertIn('accept=".json,application/json"', self.source)
        self.assertIn("imputed_hourly_candles", self.source)
        self.assertIn("شموع تاريخية اصطناعية", self.source)
        self.assertIn("WAITING_FOR_NEW_CLOSED_CANDLES", self.source)
        self.assertIn("تمت معالجة شموع مغلقة جديدة", self.source)


if __name__ == "__main__":
    unittest.main()
