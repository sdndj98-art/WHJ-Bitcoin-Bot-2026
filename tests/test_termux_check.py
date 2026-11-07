"""Regression checks for the read-only Termux diagnostics script."""
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "termux_check.sh"


class TermuxDiagnosticsTests(unittest.TestCase):
    def test_diagnostics_script_exists(self):
        self.assertTrue(SCRIPT.is_file())

    def test_diagnostics_script_has_valid_bash_syntax(self):
        result = subprocess.run(
            ["bash", "-n", str(SCRIPT)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_diagnostics_script_does_not_run_the_market_application(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("python main.py", source)
        self.assertNotIn("python dashboard.py", source)
        self.assertNotIn("git reset --hard", source)
        self.assertNotIn("git clean -fd", source)


if __name__ == "__main__":
    unittest.main()
