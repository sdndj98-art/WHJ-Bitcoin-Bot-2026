import unittest
from datetime import datetime, timezone

from whj_agent_office import ROLES, build_plan, render_markdown, validate_plan


class WHJAgentOfficeTests(unittest.TestCase):
    def test_roster_has_24_distinct_roles(self):
        plan = build_plan()
        self.assertEqual(len(plan["roles"]), 24)
        self.assertEqual(len({row["role_id"] for row in plan["roles"]}), 24)
        self.assertEqual(plan["worker_role_count"], 20)
        self.assertEqual(len(ROLES), 24)

    def test_plan_is_reproducible_for_fixed_timestamp(self):
        now = datetime(2026, 11, 12, tzinfo=timezone.utc)
        first = build_plan(now)
        second = build_plan(now)
        self.assertEqual(first, second)
        self.assertEqual(first["generated_at_utc"], "2026-11-12T00:00:00+00:00")

    def test_every_task_has_distinct_owner_and_reviewer(self):
        plan = build_plan()
        for task in plan["tasks"]:
            self.assertNotEqual(task["owner_role"], task["reviewer_role"])
            self.assertIn(task["owner_role"], ROLES)
            self.assertIn(task["reviewer_role"], ROLES)

    def test_plan_has_acyclic_dependencies_and_valid_render(self):
        plan = build_plan()
        validate_plan(plan)
        markdown = render_markdown(plan)
        self.assertIn("PLAN ONLY", markdown)
        self.assertIn("UNKNOWN", markdown)
        self.assertEqual(plan["task_count"], len(plan["tasks"]))

    def test_rejects_unsafe_live_trading_configuration(self):
        plan = build_plan()
        plan["governance"]["live_trading_enabled"] = True
        with self.assertRaisesRegex(ValueError, "live-trading"):
            validate_plan(plan)

    def test_rejects_accepted_task_without_evidence(self):
        plan = build_plan()
        plan["tasks"][0]["status"] = "accepted"
        with self.assertRaisesRegex(ValueError, "without evidence"):
            validate_plan(plan)

    def test_rejects_unknown_dependency(self):
        plan = build_plan()
        plan["tasks"][0]["dependencies"] = ["missing_task"]
        with self.assertRaisesRegex(ValueError, "Unknown task dependency"):
            validate_plan(plan)


if __name__ == "__main__":
    unittest.main()
