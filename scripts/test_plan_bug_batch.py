from __future__ import annotations

import contextlib
import importlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


class PlanBugBatchTests(unittest.TestCase):
    def planner(self):
        self.assertTrue(Path(__file__).with_name("plan_bug_batch.py").is_file())
        return importlib.import_module("plan_bug_batch")

    def bug(self, key, **overrides):
        row = {
            "key": key,
            "verdict": "real",
            "repos": ["backend"],
            "verified": True,
            "pushed": True,
            "published_repos": [],
        }
        row.update(overrides)
        return row

    def test_deduplicates_publish_repos_across_bugs(self) -> None:
        planner = self.planner()
        plan = planner.build_plan({"bugs": [self.bug("BUG-1"), self.bug("BUG-2")]})
        self.assertEqual(plan["publish_repos"], ["backend"])
        self.assertEqual(plan["publish_by_repo"], {"backend": ["BUG-1", "BUG-2"]})
        self.assertEqual(plan["pending_verify"], [])

    def test_deduplicates_repeated_repo_entries_in_one_bug(self) -> None:
        planner = self.planner()
        plan = planner.build_plan(
            {
                "bugs": [
                    self.bug("BUG-1", repos=["backend", "backend"]),
                    self.bug("BUG-2", repos=["backend"], published_repos=["backend", "backend"]),
                ]
            }
        )
        self.assertEqual(plan["publish_by_repo"], {"backend": ["BUG-1"]})
        self.assertEqual(plan["pending_verify"], ["BUG-2"])

    def test_pending_verify_only_after_all_repos_published(self) -> None:
        planner = self.planner()
        partial = self.bug(
            "BUG-1",
            repos=["backend", "pc_frontend"],
            published_repos=["backend"],
        )
        plan = planner.build_plan({"bugs": [partial]})
        self.assertEqual(plan["publish_repos"], ["pc_frontend"])
        self.assertEqual(plan["pending_verify"], [])

        complete = dict(partial, published_repos=["backend", "pc_frontend"])
        plan = planner.build_plan({"bugs": [complete]})
        self.assertEqual(plan["publish_repos"], [])
        self.assertEqual(plan["pending_verify"], ["BUG-1"])

    def test_unverified_or_unclear_bug_does_not_block_verified_bug(self) -> None:
        planner = self.planner()
        plan = planner.build_plan(
            {
                "bugs": [
                    self.bug("BUG-1"),
                    self.bug("BUG-2", verified=False),
                    self.bug("BUG-3", verdict="unclear", repos=[]),
                ]
            }
        )
        self.assertEqual(plan["publish_by_repo"], {"backend": ["BUG-1"]})
        self.assertEqual([item["key"] for item in plan["hold"]], ["BUG-2", "BUG-3"])

    def test_real_bug_hold_reason_keeps_note(self) -> None:
        planner = self.planner()
        plan = planner.build_plan(
            {
                "bugs": [
                    self.bug("BUG-1", verified=False, note="测试环境缺数据"),
                    self.bug("BUG-2", repos=[], note="未定位仓库"),
                ]
            }
        )
        reasons = {item["key"]: item["reason"] for item in plan["hold"]}
        self.assertEqual(reasons["BUG-1"], "verified=false; 测试环境缺数据")
        self.assertEqual(reasons["BUG-2"], "verdict=real but repos is empty; 未定位仓库")

    def test_notify_groups_by_tester_and_marks_unassigned(self) -> None:
        planner = self.planner()
        plan = planner.build_plan(
            {
                "bugs": [
                    self.bug(
                        "BUG-1",
                        tester="张三",
                        tester_id="u1",
                        published_repos=["backend"],
                    ),
                    self.bug("BUG-2", verdict="unclear", tester="张三", tester_id="u1"),
                    self.bug("BUG-3", tester="张三", tester_id="u2"),
                    self.bug("BUG-4", repos=[]),
                ]
            }
        )
        self.assertEqual(len(plan["notify"]), 1)
        bucket = plan["notify"][0]
        self.assertEqual(bucket["tester"], "张三")
        self.assertEqual(bucket["pending_verify"], ["BUG-1"])
        self.assertEqual([item["key"] for item in bucket["hold"]], ["BUG-2"])
        self.assertEqual(bucket["waiting_publish"], ["BUG-3"])
        self.assertEqual(plan["unassigned"], ["BUG-4"])
        self.assertIn("tester 张三 has multiple tester_id values: u1, u2", plan["warnings"])

    def test_marks_bug_unassigned_when_tester_name_is_missing(self) -> None:
        planner = self.planner()
        plan = planner.build_plan(
            {"bugs": [self.bug("BUG-1", tester_id="platform-1", published_repos=["backend"])]}
        )
        self.assertEqual(plan["notify"], [])
        self.assertEqual(plan["unassigned"], ["BUG-1"])

    def test_warns_when_tester_id_is_missing(self) -> None:
        planner = self.planner()
        plan = planner.build_plan(
            {"bugs": [self.bug("BUG-1", tester="张三", published_repos=["backend"])]}
        )
        self.assertEqual(plan["notify"][0]["tester"], "张三")
        self.assertIn("BUG-1: tester_id missing for 张三", plan["warnings"])

    def test_merges_same_tester_when_one_bug_misses_tester_id(self) -> None:
        planner = self.planner()
        plan = planner.build_plan(
            {
                "bugs": [
                    self.bug(
                        "BUG-1",
                        tester="张三",
                        tester_id="u1",
                        published_repos=["backend"],
                    ),
                    self.bug("BUG-2", verdict="unclear", repos=[], tester="张三"),
                ]
            }
        )
        self.assertEqual(len(plan["notify"]), 1)
        bucket = plan["notify"][0]
        self.assertEqual(bucket["tester_id"], "u1")
        self.assertEqual(bucket["pending_verify"], ["BUG-1"])
        self.assertEqual([item["key"] for item in bucket["hold"]], ["BUG-2"])
        self.assertIn("BUG-2: tester_id missing for 张三; inferred u1 from batch", plan["warnings"])

    def test_merges_same_name_and_warns_ambiguous_ids(self) -> None:
        planner = self.planner()
        plan = planner.build_plan(
            {
                "bugs": [
                    self.bug("BUG-1", tester="张三", tester_id="u1"),
                    self.bug("BUG-2", tester="张三", tester_id="u2"),
                    self.bug("BUG-3", verdict="unclear", repos=[], tester="张三"),
                ]
            }
        )
        self.assertEqual(len(plan["notify"]), 1)
        self.assertEqual(plan["notify"][0]["tester"], "张三")
        self.assertIn(
            "BUG-3: tester_id missing for 张三; ambiguous ids in batch: u1, u2",
            plan["warnings"],
        )
        self.assertIn("tester 张三 has multiple tester_id values: u1, u2", plan["warnings"])

    def test_rejects_published_repo_not_in_repos(self) -> None:
        planner = self.planner()
        for bug in [
            self.bug("BUG-1", repos=["backend"], published_repos=["frontend"]),
            self.bug("BUG-2", repos=[], published_repos=["ghost"]),
            self.bug("BUG-3", verdict="not_bug", repos=["backend"], published_repos=["ghost"]),
        ]:
            with self.subTest(bug=bug["key"]):
                with self.assertRaisesRegex(ValueError, "published_repos not in repos"):
                    planner.build_plan({"bugs": [bug]})

    def test_rejects_non_string_repo_entries(self) -> None:
        planner = self.planner()
        with self.assertRaisesRegex(ValueError, "expected list items to be strings"):
            planner.build_plan({"bugs": [self.bug("BUG-1", repos=["backend", None])]})

    def test_rejects_duplicate_keys_and_invalid_verdict(self) -> None:
        planner = self.planner()
        with self.assertRaisesRegex(ValueError, "duplicate bug key"):
            planner.build_plan({"bugs": [self.bug("BUG-1"), self.bug("BUG-1")]})
        with self.assertRaisesRegex(ValueError, "verdict must be one of"):
            planner.build_plan({"bugs": [self.bug("BUG-1", verdict="maybe")]})

    def test_rejects_missing_or_non_boolean_state_fields_for_real_bugs(self) -> None:
        planner = self.planner()
        missing = self.bug("BUG-1")
        missing.pop("verified")
        with self.assertRaisesRegex(ValueError, "verified must be a JSON boolean"):
            planner.build_plan({"bugs": [missing]})

        string_true = self.bug("BUG-2", verified="true")
        with self.assertRaisesRegex(ValueError, "verified must be a JSON boolean"):
            planner.build_plan({"bugs": [string_true]})

        missing_pushed = self.bug("BUG-3")
        missing_pushed.pop("pushed")
        with self.assertRaisesRegex(ValueError, "pushed must be a JSON boolean"):
            planner.build_plan({"bugs": [missing_pushed]})

    def test_cli_returns_json_plan(self) -> None:
        planner = self.planner()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "batch.json"
            path.write_text(
                json.dumps({"batch": "b1", "bugs": [self.bug("BUG-1")]}),
                encoding="utf-8",
            )
            with (
                mock.patch.object(sys, "argv", ["plan_bug_batch.py", "--input", str(path), "--format", "json"]),
                contextlib.redirect_stdout(io.StringIO()) as out,
            ):
                self.assertEqual(planner.main(), 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["publish_repos"], ["backend"])
        self.assertEqual(payload["pending_verify"], [])


if __name__ == "__main__":
    unittest.main()
