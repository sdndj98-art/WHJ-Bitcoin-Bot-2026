import json
import tempfile
import unittest
from pathlib import Path

from whj_evidence_verifier import run_verification, verify_report


class WHJEvidenceVerifierTests(unittest.TestCase):
    def make_repo(self, root: Path, quote: str = "def calculate_signal():"):
        source = root / "sample.py"
        source.write_text(quote + "\n    return 'HOLD'\n", encoding="utf-8")
        import hashlib
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        report = {
            "reports": [{
                "task_id": "sample",
                "files_inspected": [{
                    "path": "sample.py",
                    "sha256": digest,
                }],
                "findings": [{
                    "claim": "The sample defines a signal function.",
                    "source_path": "sample.py",
                    "evidence_quote": quote,
                    "confidence": "high",
                }],
            }]
        }
        report_path = root / "report.json"
        report_path.write_text(json.dumps(report), encoding="utf-8")
        return report_path

    def test_accepts_exact_quote_and_matching_fingerprint(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report = self.make_repo(root)
            result = verify_report(root, report)
            self.assertEqual(result["status"], "passed")
            self.assertEqual(result["findings_checked"], 1)
            self.assertEqual(result["issues"], [])

    def test_rejects_quote_that_is_not_in_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report = self.make_repo(root, "def calculate_signal():")
            data = json.loads(report.read_text(encoding="utf-8"))
            data["reports"][0]["findings"][0]["evidence_quote"] = "def invented_signal():"
            report.write_text(json.dumps(data), encoding="utf-8")
            result = verify_report(root, report)
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["issues"][0]["type"], "quote_not_in_source")

    def test_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report = self.make_repo(root)
            data = json.loads(report.read_text(encoding="utf-8"))
            data["reports"][0]["findings"][0]["source_path"] = "../outside.py"
            report.write_text(json.dumps(data), encoding="utf-8")
            result = verify_report(root, report)
            self.assertEqual(result["issues"][0]["type"], "source_missing_or_unsafe")

    def test_detects_source_changed_after_inventory(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report = self.make_repo(root)
            (root / "sample.py").write_text(
                "def calculate_signal():\n    return 'BUY'\n",
                encoding="utf-8",
            )
            result = verify_report(root, report)
            self.assertEqual(result["status"], "failed")
            self.assertEqual(
                result["issues"][0]["type"],
                "source_changed_since_inventory",
            )

    def test_no_reports_is_not_reported_as_success(self):
        with tempfile.TemporaryDirectory() as temp:
            result = run_verification(Path(temp))
            self.assertEqual(result["status"], "no_reports")
            self.assertEqual(result["reports_checked"], 0)


if __name__ == "__main__":
    unittest.main()
