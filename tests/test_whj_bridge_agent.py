import unittest
from unittest.mock import patch
import subprocess

from whj_bridge_agent import git, validate_origin_url


class BridgeOriginValidationTests(unittest.TestCase):
    @patch("whj_bridge_agent.subprocess.run")
    def test_git_preserves_leading_porcelain_status_columns(self, run):
        run.return_value = subprocess.CompletedProcess(
            args=["git", "status", "--porcelain"],
            returncode=0,
            stdout=" M forward_paper_monitor.py\\n?? docs/CVD_FLAG_GUARD.md\\n",
            stderr="",
        )
        self.assertEqual(
            git(["status", "--porcelain"]),
            " M forward_paper_monitor.py\\n?? docs/CVD_FLAG_GUARD.md",
        )

    def test_accepts_only_exact_https_repository_urls(self):
        for remote in (
            "https://github.com/sdndj98-art/WHJ-Bitcoin-Bot-2026",
            "https://github.com/sdndj98-art/WHJ-Bitcoin-Bot-2026.git",
        ):
            with self.subTest(remote=remote):
                self.assertTrue(validate_origin_url(remote))

    def test_rejects_host_confusion_and_repository_prefixes(self):
        for remote in (
            "https://github.com.evil.example/sdndj98-art/WHJ-Bitcoin-Bot-2026",
            "https://github.com/sdndj98-art/WHJ-Bitcoin-Bot-2026.evil",
            "https://github.com/sdndj98-art/WHJ-Bitcoin-Bot-2026@evil.example/attacker",
            "https://github.com/sdndj98-art/WHJ-Bitcoin-Bot-2026/extra",
        ):
            with self.subTest(remote=remote):
                self.assertFalse(validate_origin_url(remote))

    def test_rejects_other_schemes_credentials_ports_and_suffixes(self):
        for remote in (
            "http://github.com/sdndj98-art/WHJ-Bitcoin-Bot-2026",
            "ssh://git@github.com/sdndj98-art/WHJ-Bitcoin-Bot-2026.git",
            "https://user:pass@github.com/sdndj98-art/WHJ-Bitcoin-Bot-2026",
            "https://github.com:8443/sdndj98-art/WHJ-Bitcoin-Bot-2026",
            "https://github.com/sdndj98-art/Other-Repository",
            "https://github.com/sdndj98-art/WHJ-Bitcoin-Bot-2026?redirect=evil",
            "https://github.com/sdndj98-art/WHJ-Bitcoin-Bot-2026#fragment",
            "",
            None,
        ):
            with self.subTest(remote=remote):
                self.assertFalse(validate_origin_url(remote))


if __name__ == "__main__":
    unittest.main()
