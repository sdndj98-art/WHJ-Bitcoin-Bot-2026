import unittest
from collections import Counter
from html.parser import HTMLParser
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

    def test_navigation_targets_exist_and_ids_are_unique(self):
        ids = set(self.parser.ids)
        duplicates = [key for key, count in Counter(self.parser.ids).items() if count > 1]
        self.assertEqual(duplicates, [], "Dashboard HTML contains duplicate element IDs")
        self.assertTrue(self.parser.nav_views, "Dashboard navigation is missing")
        for target in self.parser.nav_views:
            self.assertIn(target, ids, f"Navigation target #{target} has no matching view")

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
