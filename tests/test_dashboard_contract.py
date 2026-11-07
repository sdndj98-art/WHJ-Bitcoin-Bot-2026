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
            "forwardTrades", "forwardRows", "forwardAllocation", "forwardMaxDD",
            "forwardDaily", "forwardStreak", "forwardQuality", "forwardCandle",
        }
        self.assertTrue(required.issubset(set(self.parser.ids)))
        self.assertIn("function validateForwardReport(x)", self.source)
        self.assertIn("function renderForward(x)", self.source)
        self.assertIn("function resetForwardView()", self.source)
        self.assertIn("تقييم الاستراتيجية", self.source)
        self.assertIn("CONTINUE_PAPER_REVIEW", self.source)
        self.assertIn("REVIEW_REQUIRED", self.source)

    def test_forward_report_is_paper_only_and_consistency_checked(self):
        self.assertIn("FORWARD_ONLY_PAPER_NO_LIVE_ORDERS", self.source)
        self.assertIn("إجماليات الحسابات لا تطابق ملخص المحفظة", self.source)
        self.assertIn("نسبة العائد لا تطابق قيمة المحفظة", self.source)
        self.assertIn('x.data_quality.quality!=="HEALTHY"', self.source)
        self.assertIn('accept=".json,application/json"', self.source)


if __name__ == "__main__":
    unittest.main()
