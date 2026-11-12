import unittest

from whj_grok_worker import (
    REPORT_SCHEMA,
    estimate_cost,
    parse_response,
    validate_worker_report,
)


class WHJGrokWorkerTests(unittest.TestCase):
    def test_response_schema_requires_evidence_and_limits_recommendations(self):
        self.assertIn("findings", REPORT_SCHEMA["required"])
        self.assertFalse(REPORT_SCHEMA["additionalProperties"])
        self.assertEqual(
            REPORT_SCHEMA["properties"]["recommendation"]["enum"],
            ["continue_research", "hold", "reject", "needs_more_data"],
        )

    def test_parse_response_extracts_structured_json_and_usage(self):
        response = {
            "output": [{
                "type": "message",
                "content": [{
                    "type": "output_text",
                    "text": '{"status":"blocked","summary":"No evidence","findings":[],"risks":[],"missing_data":["dataset"],"proposed_next_steps":["fetch data"],"recommendation":"needs_more_data"}',
                }],
            }],
            "usage": {"input_tokens": 120, "output_tokens": 40},
        }
        parsed, usage = parse_response(response)
        self.assertEqual(parsed["status"], "blocked")
        self.assertEqual(usage["input_tokens"], 120)

    def test_rejects_fabricated_source_path(self):
        report = {
            "status": "completed",
            "summary": "A finding",
            "findings": [{
                "claim": "The module validates candles",
                "source_path": "made_up.py",
                "evidence_quote": "def validate_candles():",
                "confidence": "high",
            }],
            "risks": [],
            "missing_data": [],
            "proposed_next_steps": [],
            "recommendation": "continue_research",
        }
        with self.assertRaisesRegex(ValueError, "not supplied"):
            validate_worker_report(report, {"real.py": "def validate_candles():"})

    def test_rejects_non_verbatim_evidence(self):
        report = {
            "status": "completed",
            "summary": "A finding",
            "findings": [{
                "claim": "The module validates candles",
                "source_path": "real.py",
                "evidence_quote": "def validate candles():",
                "confidence": "high",
            }],
            "risks": [],
            "missing_data": [],
            "proposed_next_steps": [],
            "recommendation": "continue_research",
        }
        with self.assertRaisesRegex(ValueError, "exact source excerpt"):
            validate_worker_report(report, {"real.py": "def validate_candles():"})

    def test_numeric_claim_requires_numeric_source_excerpt(self):
        report = {
            "status": "completed",
            "summary": "A numeric finding",
            "findings": [{
                "claim": "The test suite has 522 tests",
                "source_path": "readme.md",
                "evidence_quote": "The test suite passed all tests.",
                "confidence": "high",
            }],
            "risks": [],
            "missing_data": [],
            "proposed_next_steps": [],
            "recommendation": "continue_research",
        }
        with self.assertRaisesRegex(ValueError, "Numeric claim"):
            validate_worker_report(report, {"readme.md": "The test suite passed all tests."})

    def test_completed_report_requires_at_least_one_evidenced_finding(self):
        report = {
            "status": "completed",
            "summary": "No evidence",
            "findings": [],
            "risks": [],
            "missing_data": [],
            "proposed_next_steps": [],
            "recommendation": "continue_research",
        }
        with self.assertRaisesRegex(ValueError, "at least one"):
            validate_worker_report(report, {})

    def test_cost_estimate_is_positive_and_bounded(self):
        self.assertGreater(estimate_cost(4000, 1000), 0)
        self.assertGreater(estimate_cost(8000, 1000), estimate_cost(4000, 1000))


if __name__ == "__main__":
    unittest.main()
