import json
import tempfile
import unittest
from pathlib import Path

from paper_ledger_audit import CANDIDATES, audit_ledger, build_audit


class PaperLedgerAuditTests(unittest.TestCase):
    def test_missing_ledgers_are_reported_without_creation(self):
        with tempfile.TemporaryDirectory() as folder:
            report = build_audit(folder)
            self.assertEqual(report["mode"], "READ_ONLY_PAPER_LEDGER_AUDIT")
            self.assertEqual(report["present_ledgers"], 0)
            self.assertEqual(len(report["missing_ledgers"]), 4)
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_reports_realized_trade_metrics(self):
        with tempfile.TemporaryDirectory() as folder:
            filename = CANDIDATES["1d_sma_trend"]
            path = Path(folder) / filename
            path.write_text(json.dumps({
                "strategy": "sma_trend",
                "initial_cash": 250.0,
                "cash": 260.0,
                "btc": 0.0,
                "trades": [
                    {"pnl_usd": 15.0},
                    {"pnl_usd": -5.0},
                    {"pnl_usd": 0.0},
                ],
            }), encoding="utf-8")
            before = path.read_bytes()
            result = audit_ledger(Path(folder), "1d_sma_trend", filename)
            self.assertEqual(result["trades_with_realized_pnl"], 3)
            self.assertEqual(result["wins"], 1)
            self.assertEqual(result["losses"], 1)
            self.assertEqual(result["realized_pnl_usd"], 10.0)
            self.assertEqual(result["profit_factor"], 3.0)
            self.assertEqual(result["cash_vs_initial_pct"], 4.0)
            self.assertEqual(path.read_bytes(), before)

    def test_rejects_non_finite_trade_pnl(self):
        with tempfile.TemporaryDirectory() as folder:
            filename = CANDIDATES["1d_sma_trend"]
            (Path(folder) / filename).write_text(
                '{"trades":[{"pnl_usd":NaN}]}', encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "must be finite"):
                audit_ledger(Path(folder), "1d_sma_trend", filename)

    def test_rejects_symlink_ledger(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            target = root / "target.json"
            target.write_text("{}", encoding="utf-8")
            link = root / CANDIDATES["1d_sma_trend"]
            link.symlink_to(target)
            with self.assertRaisesRegex(ValueError, "symlink"):
                audit_ledger(root, "1d_sma_trend", link.name)


if __name__ == "__main__":
    unittest.main()
