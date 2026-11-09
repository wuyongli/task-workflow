from __future__ import annotations

import copy
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import next_task_workspace as next_script
import switch_task_stage as stage_script
import task_workflow_lib as lib


class TaskPublicationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = self.root / "config"
        self.config.mkdir()
        self.task_id = "2026-11-05-公示记录"
        self.task_dir = self.root / "_docs" / self.task_id
        self.task_dir.mkdir(parents=True)
        self.meta_path = self.task_dir / "meta.yaml"
        lib.save_yaml(self.config / "workspace.yaml", {
            "docs_root": str(self.root / "_docs"),
            "tasks_root": str(self.root / "_tasks"),
        }, False)
        self.meta = {
            "task_id": self.task_id, "phase": 1, "status": "开发中",
            "resume_status": "开发中", "coding_allowed": True,
            "active_plan": "plan.md", "execution_mode": "manual",
            "repos": [{"key": "backend", "branch": "一期", "repo_dir": "backend__公示记录"}],
            "current_stage": {
                "phase": 1, "task_name": "一期", "status": "开发中",
                "resume_status": "开发中", "plan": "plan.md",
                "repos": [{"key": "backend", "branch": "一期"}],
            },
            "previous_phases": [],
        }
        self.publication = {
            "title": "一期2026.11.05", "node_id": "node-one",
            "url": "https://alidocs.dingtalk.com/i/nodes/node-one",
            "kind": "proposal", "generated_at": "2026-11-05T10:00:00+08:00",
        }
        self.save()
        (self.task_dir / "plan.md").write_text("# 一期方案\n", encoding="utf-8")

    def save(self) -> None:
        lib.save_yaml(self.meta_path, self.meta, False)

    def next_stage(self) -> None:
        with (
            mock.patch.object(next_script, "validate_repo_state", return_value=[]),
            mock.patch.object(next_script, "run"),
            mock.patch("sys.argv", ["next_task_workspace.py", self.task_id, "二期", "--config-root", str(self.config)]),
        ):
            self.assertEqual(next_script.main(), 0)

    def switch_stage(self, phase: int) -> None:
        with (
            mock.patch.object(stage_script, "validate_repo_state", return_value=[]),
            mock.patch.object(stage_script, "_local_branch_exists", return_value=True),
            mock.patch.object(stage_script, "run"),
            mock.patch("sys.argv", ["switch_task_stage.py", self.task_id, str(phase), "--config-root", str(self.config)]),
        ):
            self.assertEqual(stage_script.main(), 0)

    def record(self, phase: int = 1, publication: dict | None = None, *extra: str) -> subprocess.CompletedProcess[str]:
        entry = publication or self.publication
        return subprocess.run([
            sys.executable, str(Path(__file__).with_name("record_task_publication.py")),
            self.task_id, "--phase", str(phase), "--config-root", str(self.config),
            "--title", entry["title"], "--node-id", entry["node_id"],
            "--url", entry["url"], "--kind", entry["kind"],
            "--generated-at", entry["generated_at"], *extra,
        ], text=True, capture_output=True)

    def test_next_archives_publications_without_inheriting_them(self) -> None:
        self.meta["current_stage"]["publications"] = [self.publication]
        self.save()
        self.next_stage()
        actual = lib.load_yaml(self.meta_path)
        self.assertEqual(actual["previous_phases"][0]["publications"], [self.publication])
        self.assertNotIn("publications", actual["current_stage"])

    def test_switch_round_trip_keeps_each_stages_publications(self) -> None:
        self.next_stage()
        actual = lib.load_yaml(self.meta_path)
        second = {**self.publication, "node_id": "node-two", "title": "二期公示", "url": "https://alidocs.dingtalk.com/i/nodes/node-two"}
        actual["previous_phases"][0]["publications"] = [self.publication]
        actual["current_stage"]["publications"] = [second]
        lib.save_yaml(self.meta_path, actual, False)
        self.switch_stage(1)
        actual = lib.load_yaml(self.meta_path)
        self.assertEqual(actual["current_stage"]["publications"], [self.publication])
        self.assertEqual(actual["previous_phases"][0]["publications"], [second])
        self.switch_stage(2)
        actual = lib.load_yaml(self.meta_path)
        self.assertEqual(actual["current_stage"]["publications"], [second])
        self.assertEqual(actual["previous_phases"][0]["publications"], [self.publication])

    def test_record_is_idempotent_and_changes_only_stage_publications(self) -> None:
        before = copy.deepcopy(self.meta)
        result = self.record()
        self.assertEqual(result.returncode, 0, result.stderr)
        before["current_stage"]["publications"] = [self.publication]
        self.assertEqual(lib.load_yaml(self.meta_path), before)
        saved = self.meta_path.read_bytes()
        self.assertEqual(self.record().returncode, 0)
        self.assertEqual(self.meta_path.read_bytes(), saved)

    def test_multiple_documents_remain_in_history(self) -> None:
        self.assertEqual(self.record().returncode, 0)
        second = {**self.publication, "node_id": "result", "url": "https://alidocs.dingtalk.com/i/nodes/result", "kind": "result"}
        result = self.record(publication=second)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(lib.load_yaml(self.meta_path)["current_stage"]["publications"], [self.publication, second])

    def test_record_targets_historical_stage_without_switching(self) -> None:
        self.next_stage()
        before = lib.load_yaml(self.meta_path)
        result = self.record(phase=1)
        self.assertEqual(result.returncode, 0, result.stderr)
        before["previous_phases"][0]["publications"] = [self.publication]
        self.assertEqual(lib.load_yaml(self.meta_path), before)

    def test_legacy_task_gets_current_stage_without_changing_authorization(self) -> None:
        self.meta.pop("current_stage")
        self.save()
        result = self.record()
        self.assertEqual(result.returncode, 0, result.stderr)
        actual = lib.load_yaml(self.meta_path)
        stage = actual.pop("current_stage")
        self.assertEqual(actual, self.meta)
        self.assertEqual(stage["phase"], 1)
        self.assertEqual(stage["publications"], [self.publication])

    def test_invalid_target_or_receipt_leaves_metadata_unchanged(self) -> None:
        cases = [
            (99, self.publication),
            (1, {**self.publication, "node_id": ""}),
            (1, {**self.publication, "url": "not-a-url"}),
            (1, {**self.publication, "generated_at": "yesterday"}),
        ]
        for phase, entry in cases:
            with self.subTest(phase=phase, entry=entry):
                before = self.meta_path.read_bytes()
                self.assertNotEqual(self.record(phase, entry).returncode, 0)
                self.assertEqual(self.meta_path.read_bytes(), before)

    def test_dry_run_does_not_write(self) -> None:
        before = self.meta_path.read_bytes()
        result = self.record(1, self.publication, "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.meta_path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
