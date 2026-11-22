import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from office.ai_code_agent import MAX_FILE_CHARS, choose_gemini_model, parse_requested_files


class AICodeAgentAllowlistTests(unittest.TestCase):
    def test_accepts_existing_allowlisted_source(self):
        self.assertEqual(
            parse_requested_files("Task details\nFiles: whj_24h_development_team.py"),
            ["whj_24h_development_team.py"],
        )

    def test_accepts_shared_paper_engine_file(self):
        self.assertEqual(
            parse_requested_files("Task details\nFiles: shared_paper_portfolio.py"),
            ["shared_paper_portfolio.py"],
        )

    def test_rejects_workflow_path(self):
        with self.assertRaises(ValueError):
            parse_requested_files("Task\nFiles: .github/workflows/whj-ai-code-agent.yml")

    def test_rejects_path_traversal(self):
        with self.assertRaises(ValueError):
            parse_requested_files("Task\nFiles: ../README.md")

    def test_rejects_too_many_files(self):
        with self.assertRaises(ValueError):
            parse_requested_files(
                "Task\nFiles: whj_24h_development_team.py, "
                "strategy_lab.py, tests/test_main.py, tests/test_dashboard_contract.py"
            )

    def test_context_limit_covers_multi_market_scanner_source(self):
        source = ROOT / "multi_market_opportunity_scan.py"
        self.assertLessEqual(source.stat().st_size, MAX_FILE_CHARS)

    def test_auto_model_prefers_current_flash_lite_version(self):
        models = [
            {"name": "models/gemini-pro-x", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/gemini-2.5-flash-lite", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/gemini-3.5-flash-lite", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/text-embedding-x", "supportedGenerationMethods": ["embedContent"]},
        ]
        self.assertEqual(choose_gemini_model(models), "gemini-3.5-flash-lite")

    def test_model_candidates_keep_fallbacks_in_preference_order(self):
        from office.ai_code_agent import choose_gemini_models
        models = [
            {"name": "models/gemini-2.5-flash-lite", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/gemini-3.5-flash", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/gemini-3.5-flash-lite", "supportedGenerationMethods": ["generateContent"]},
        ]
        self.assertEqual(
            choose_gemini_models(models),
            ["gemini-3.5-flash-lite", "gemini-2.5-flash-lite", "gemini-3.5-flash"],
        )

    def test_auto_model_rejects_models_without_generation_support(self):
        with self.assertRaises(RuntimeError):
            choose_gemini_model([
                {"name": "models/embedding-x", "supportedGenerationMethods": ["embedContent"]}
            ])

    def test_explicit_model_is_preserved(self):
        self.assertEqual(choose_gemini_model([], "custom-model-id"), "custom-model-id")

    def test_rejects_missing_file(self):
        with self.assertRaises(ValueError):
            parse_requested_files("Task\nFiles: whj_nonexistent_file.py")


if __name__ == "__main__":
    unittest.main()
