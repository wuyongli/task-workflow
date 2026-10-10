from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import next_task_workspace as next_script
import switch_task_stage as stage_script
import task_workflow_lib as lib


class ExecutionModeCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.config = root / "config"
        self.config.mkdir()
        self.task_id = "2026-09-30-自动模式测试"
        self.task_dir = root / "_docs" / self.task_id
        self.task_dir.mkdir(parents=True)
        self.meta_path = self.task_dir / "meta.yaml"
        lib.save_yaml(self.config / "workspace.yaml", {
            "docs_root": str(root / "_docs"), "tasks_root": str(root / "_tasks"),
        }, False)
        self.meta = {
            "task_id": self.task_id, "phase": 1, "status": "方案中",
            "resume_status": "方案中", "coding_allowed": False,
            "active_plan": "plan.md", "repos": [{"key": "backend", "branch": "测试", "repo_dir": "backend__测试"}],
            "current_stage": {"phase": 1, "task_name": "自动模式测试", "status": "方案中", "plan": "plan.md"},
            "previous_phases": [],
        }
        lib.save_yaml(self.meta_path, self.meta, False)

    def run_mode(self, mode: str, *extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([
            sys.executable, str(Path(__file__).with_name("set_task_execution_mode.py")),
            self.task_id, mode, "--config-root", str(self.config), *extra,
        ], text=True, capture_output=True)

    def run_status(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run([
            sys.executable, str(Path(__file__).with_name("status_task_workspace.py")),
            "--config-root", str(self.config),
        ], text=True, capture_output=True)

    def test_status_reports_invalid_mode_and_continues_with_later_tasks(self) -> None:
        self.meta["execution_mode"] = "automatic"
        lib.save_yaml(self.meta_path, self.meta, False)
        later_id = "2026-10-01-正常任务"
        later_dir = self.task_dir.parent / later_id
        later_dir.mkdir()
        lib.save_yaml(later_dir / "meta.yaml", {
            "task_id": later_id, "status": "方案中", "repos": [],
            "execution_mode": "auto",
        }, False)
        result = self.run_status()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn(self.task_id, result.stdout)
        self.assertIn("invalid execution_mode", result.stdout)
        self.assertIn(later_id, result.stdout)
        self.assertIn("execution_mode=auto", result.stdout)
        self.assertNotIn("execution_mode=manual", result.stdout)
        self.assertNotIn("Traceback", result.stderr)

    def test_status_defaults_legacy_tasks_to_manual_and_shows_valid_modes(self) -> None:
        self.meta["repos"] = []
        for mode in (None, "manual", "auto"):
            with self.subTest(mode=mode):
                self.meta.pop("execution_mode", None)
                if mode is not None:
                    self.meta["execution_mode"] = mode
                lib.save_yaml(self.meta_path, self.meta, False)
                result = self.run_status()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(f"execution_mode={mode or 'manual'}", result.stdout)

    def test_stage_summary_shows_workspace_mode(self) -> None:
        for mode in ("manual", "auto"):
            with self.subTest(mode=mode):
                summary = stage_script.render_stage_index("任务", {}, "plan.md", [], execution_mode=mode)
                self.assertIn(f"- 执行模式：{mode}", summary)

    def test_phase_mode_cannot_override_workspace_mode(self) -> None:
        self.meta["repos"] = []
        self.meta["current_stage"]["execution_mode"] = "auto"
        for mode in (None, "manual"):
            with self.subTest(mode=mode):
                if mode is not None:
                    self.meta["execution_mode"] = mode
                lib.save_yaml(self.meta_path, self.meta, False)
                result = self.run_status()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("execution_mode=manual", result.stdout)

    def test_invalid_persisted_mode_cannot_be_silently_overwritten(self) -> None:
        self.meta["execution_mode"] = "automatic"
        lib.save_yaml(self.meta_path, self.meta, False)
        before = self.meta_path.read_bytes()
        result = self.run_mode("auto")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid execution_mode", result.stderr)
        self.assertEqual(self.meta_path.read_bytes(), before)

    def test_mismatched_stage_status_rejected_without_changes(self) -> None:
        self.meta["current_stage"]["status"] = "开发中"
        lib.save_yaml(self.meta_path, self.meta, False)
        before = self.meta_path.read_bytes()
        result = self.run_mode("auto")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("current stage status differs", result.stderr)
        self.assertEqual(self.meta_path.read_bytes(), before)

    def test_enable_changes_only_workspace_mode_and_is_idempotent(self) -> None:
        result = self.run_mode("auto")
        self.assertEqual(result.returncode, 0, result.stderr)
        expected = self.meta
        expected["execution_mode"] = "auto"
        self.assertEqual(lib.load_yaml(self.meta_path), expected)
        saved = self.meta_path.read_bytes()
        self.assertEqual(self.run_mode("auto").returncode, 0)
        self.assertEqual(self.meta_path.read_bytes(), saved)

    def test_manual_does_not_revoke_existing_development_permission(self) -> None:
        self.meta.update(status="开发中", resume_status="开发中", coding_allowed=True)
        self.meta["current_stage"].update(status="开发中")
        self.meta["execution_mode"] = "auto"
        lib.save_yaml(self.meta_path, self.meta, False)
        result = self.run_mode("manual")
        self.assertEqual(result.returncode, 0, result.stderr)
        expected = self.meta
        expected["execution_mode"] = "manual"
        self.assertEqual(lib.load_yaml(self.meta_path), expected)

    def test_enabling_paused_task_does_not_resume_it(self) -> None:
        self.meta.update(status="暂停中", resume_status="开发中", coding_allowed=False)
        self.meta["current_stage"].update(status="暂停中", resume_status="开发中")
        lib.save_yaml(self.meta_path, self.meta, False)
        result = self.run_mode("auto")
        self.assertEqual(result.returncode, 0, result.stderr)
        actual = lib.load_yaml(self.meta_path)
        self.assertEqual(actual["status"], "暂停中")
        self.assertFalse(actual["coding_allowed"])

    def test_dry_run_does_not_change_metadata(self) -> None:
        before = self.meta_path.read_bytes()
        result = self.run_mode("auto", "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.meta_path.read_bytes(), before)

    def test_legacy_metadata_gets_only_workspace_mode_without_losing_context(self) -> None:
        self.meta.pop("current_stage")
        self.meta["bbs_id"] = "12345"
        lib.save_yaml(self.meta_path, self.meta, False)
        result = self.run_mode("auto")
        self.assertEqual(result.returncode, 0, result.stderr)
        actual = lib.load_yaml(self.meta_path)
        self.assertEqual(actual.pop("execution_mode"), "auto")
        self.assertEqual(actual, self.meta)
        self.assertNotIn("current_stage", actual)

    def test_invalid_mode_rejected_without_changes(self) -> None:
        before = self.meta_path.read_bytes()
        self.assertNotEqual(self.run_mode("automatic").returncode, 0)
        self.assertEqual(self.meta_path.read_bytes(), before)

    def test_completed_task_cannot_be_enabled(self) -> None:
        self.meta["status"] = "已完成"
        self.meta["current_stage"]["status"] = "已完成"
        lib.save_yaml(self.meta_path, self.meta, False)
        before = self.meta_path.read_bytes()
        self.assertNotEqual(self.run_mode("auto").returncode, 0)
        self.assertEqual(self.meta_path.read_bytes(), before)

    def test_next_and_switch_preserve_workspace_mode(self) -> None:
        self.meta.update(status="开发中", resume_status="开发中", coding_allowed=True)
        self.meta["current_stage"].update(status="开发中", resume_status="开发中")
        self.meta["execution_mode"] = "auto"
        lib.save_yaml(self.meta_path, self.meta, False)
        (self.task_dir / "plan.md").write_text("# 一期方案\n", encoding="utf-8")
        with (
            mock.patch.object(next_script, "validate_repo_state", return_value=[]),
            mock.patch.object(next_script, "run"),
            mock.patch("sys.argv", ["next_task_workspace.py", self.task_id, "二期", "--config-root", str(self.config)]),
        ):
            self.assertEqual(next_script.main(), 0)
        actual = lib.load_yaml(self.meta_path)
        self.assertEqual(actual["execution_mode"], "auto")
        self.assertNotIn("execution_mode", actual["current_stage"])
        self.assertNotIn("execution_mode", actual["previous_phases"][0])
        self.assertIn("- 执行模式：auto", (self.task_dir / "index.md").read_text(encoding="utf-8"))
        self.assertFalse(actual["coding_allowed"])

        with (
            mock.patch.object(stage_script, "validate_repo_state", return_value=[]),
            mock.patch.object(stage_script, "_local_branch_exists", return_value=True),
            mock.patch.object(stage_script, "run"),
            mock.patch("sys.argv", ["switch_task_stage.py", self.task_id, "1", "--config-root", str(self.config)]),
        ):
            self.assertEqual(stage_script.main(), 0)
        actual = lib.load_yaml(self.meta_path)
        self.assertEqual(actual["execution_mode"], "auto")
        self.assertNotIn("execution_mode", actual["current_stage"])
        self.assertIn("- 执行模式：auto", (self.task_dir / "index.md").read_text(encoding="utf-8"))
        self.assertFalse(actual["coding_allowed"], "恢复自动阶段后须重新核对开发准入")
        self.assertNotIn("execution_mode", actual["previous_phases"][0])

        self.assertEqual(self.run_mode("manual").returncode, 0)
        with (
            mock.patch.object(stage_script, "validate_repo_state", return_value=[]),
            mock.patch.object(stage_script, "_local_branch_exists", return_value=True),
            mock.patch.object(stage_script, "run"),
            mock.patch("sys.argv", ["switch_task_stage.py", self.task_id, "2", "--config-root", str(self.config)]),
        ):
            self.assertEqual(stage_script.main(), 0)
        actual = lib.load_yaml(self.meta_path)
        self.assertEqual(actual["execution_mode"], "manual")
        self.assertIn("- 执行模式：manual", (self.task_dir / "index.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
