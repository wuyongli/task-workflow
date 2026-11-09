from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import cleanup_task_workspace as cleanup
import task_workflow_lib as lib
import task_dispatch as dispatch


class CleanupWorkspaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.task_id = "2026-11-09-放弃任务"
        self.task_root = self.root / "_tasks" / self.task_id
        self.repo = self.task_root / "repo__放弃任务"
        self.docs = self.root / "_docs" / self.task_id
        self.config = self.root / "config"
        for path in (self.repo, self.docs, self.config):
            path.mkdir(parents=True)
        lib.save_yaml(self.config / "workspace.yaml", {
            "tasks_root": str(self.root / "_tasks"),
            "docs_root": str(self.root / "_docs"),
        }, False)
        lib.save_yaml(self.config / "repositories.yaml", {"repositories": []}, False)
        self.meta_path = self.docs / "meta.yaml"
        self.meta = {
            "task_id": self.task_id,
            "status": "暂停中",
            "resume_status": "开发中",
            "coding_allowed": False,
            "current_stage": {"phase": 1, "status": "暂停中", "resume_status": "开发中"},
            "repos": [{"key": "repo", "repo_dir": self.repo.name, "branch": "task"}],
        }
        lib.save_yaml(self.meta_path, self.meta, False)
        (self.docs / "progress.md").write_text("尚未完成，决定不再开发。\n", encoding="utf-8")
        self.git("init", "--initial-branch=task")
        self.git("config", "user.email", "test@example.com")
        self.git("config", "user.name", "Test User")
        (self.repo / "base.txt").write_text("base\n", encoding="utf-8")
        self.git("add", "base.txt")
        self.git("commit", "-m", "base")

    def git(self, *args: str) -> str:
        return subprocess.run(["git", "-C", str(self.repo), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def run_cleanup(self, *args: str) -> int:
        with mock.patch("sys.argv", ["cleanup_task_workspace.py", self.task_id,
                                     "--config-root", str(self.config), *args]):
            return cleanup.main()

    def add_unpushed_commit(self) -> None:
        origin = self.root / "origin.git"
        subprocess.run(["git", "init", "--bare", str(origin)], check=True, capture_output=True)
        self.git("remote", "add", "origin", str(origin))
        self.git("push", "-u", "origin", "task")
        (self.repo / "local.txt").write_text("local only\n", encoding="utf-8")
        self.git("add", "local.txt")
        self.git("commit", "-m", "unfinished local work")

    def test_all_supported_statuses_allow_cleanup_without_marking_complete(self) -> None:
        for status in ("方案中", "开发中", "测试中", "暂停中", "已完成"):
            with self.subTest(status=status):
                self.meta["status"] = status
                self.meta["current_stage"]["status"] = status
                lib.save_yaml(self.meta_path, self.meta, False)
                before = self.meta_path.read_bytes()
                self.assertEqual(self.run_cleanup("--dry-run"), 0)
                self.assertEqual(self.meta_path.read_bytes(), before)
                self.assertTrue(self.repo.exists())

    def test_paused_task_is_removed_and_documents_are_preserved(self) -> None:
        before = {path.name: path.read_bytes() for path in self.docs.iterdir()}
        with mock.patch.object(cleanup, "cleanup_task_runtime", return_value=[]) as runtime:
            self.assertEqual(self.run_cleanup(), 0)
        runtime.assert_called_once()
        self.assertFalse(self.task_root.exists())
        self.assertEqual({path.name: path.read_bytes() for path in self.docs.iterdir()}, before)

    def test_dirty_worktree_blocks_default_cleanup_before_runtime_changes(self) -> None:
        (self.repo / "base.txt").write_text("unfinished\n", encoding="utf-8")
        with mock.patch.object(cleanup, "cleanup_task_runtime") as runtime:
            self.assertEqual(self.run_cleanup(), 2)
        runtime.assert_not_called()
        self.assertTrue(self.repo.exists())

    def test_unpushed_commits_block_default_cleanup(self) -> None:
        self.add_unpushed_commit()
        self.assertEqual(self.run_cleanup(), 2)
        self.assertTrue(self.repo.exists())

    def test_explicit_discard_removes_uncommitted_and_unpushed_work(self) -> None:
        self.add_unpushed_commit()
        (self.repo / "base.txt").write_text("unfinished\n", encoding="utf-8")
        (self.repo / "untracked.txt").write_text("untracked\n", encoding="utf-8")
        remote_before = self.git("ls-remote", "origin")
        with mock.patch.object(cleanup, "cleanup_task_runtime", return_value=[]):
            self.assertEqual(self.run_cleanup("--discard-local-changes"), 0)
        self.assertFalse(self.task_root.exists())
        remote_after = subprocess.run(["git", "ls-remote", str(self.root / "origin.git")],
                                      check=True, capture_output=True, text=True).stdout.strip()
        self.assertEqual(remote_after, remote_before)
        self.assertEqual(lib.load_yaml(self.meta_path), self.meta)

    def test_discard_dry_run_preserves_dirty_work_and_metadata(self) -> None:
        (self.repo / "base.txt").write_text("unfinished\n", encoding="utf-8")
        before = self.meta_path.read_bytes()
        self.assertEqual(self.run_cleanup("--discard-local-changes", "--dry-run"), 0)
        self.assertEqual((self.repo / "base.txt").read_text(), "unfinished\n")
        self.assertEqual(self.meta_path.read_bytes(), before)

    def test_discard_still_blocks_wrong_branch(self) -> None:
        self.git("checkout", "-b", "other")
        with mock.patch.object(cleanup, "cleanup_task_runtime") as runtime:
            self.assertEqual(self.run_cleanup("--discard-local-changes"), 2)
        runtime.assert_not_called()
        self.assertTrue(self.repo.exists())

    def test_discard_still_blocks_repo_outside_task_directory(self) -> None:
        outside = self.root / "source"
        self.repo.rename(outside)
        self.meta["repos"][0]["repo_dir"] = str(outside)
        lib.save_yaml(self.meta_path, self.meta, False)
        with mock.patch.object(cleanup, "cleanup_task_runtime") as runtime:
            self.assertEqual(self.run_cleanup("--discard-local-changes"), 2)
        runtime.assert_not_called()
        self.assertTrue(outside.exists())
        self.assertTrue(self.task_root.exists())

    def test_all_repos_are_checked_before_any_runtime_or_code_is_removed(self) -> None:
        self.meta["repos"].append({"key": "missing", "repo_dir": "missing", "branch": "task"})
        lib.save_yaml(self.meta_path, self.meta, False)
        with mock.patch.object(cleanup, "cleanup_task_runtime") as runtime:
            self.assertEqual(self.run_cleanup("--discard-local-changes"), 2)
        runtime.assert_not_called()
        self.assertTrue(self.repo.exists())

    def test_default_cleanup_protects_unpushed_historical_branch(self) -> None:
        self.add_unpushed_commit()
        self.git("branch", "-m", "history")
        self.git("checkout", "-b", "task", "origin/task")
        with mock.patch.object(cleanup, "cleanup_task_runtime") as runtime:
            self.assertEqual(self.run_cleanup(), 2)
        runtime.assert_not_called()
        self.assertTrue(self.repo.exists())
        self.assertEqual(self.run_cleanup("--discard-local-changes", "--dry-run"), 0)

    def test_cleanup_pauses_unfinished_auto_task_before_releasing_runtime(self) -> None:
        self.meta.update(status="开发中", resume_status="开发中", coding_allowed=True,
                         execution_mode="auto", phase=1)
        self.meta["current_stage"]["status"] = "开发中"
        lib.save_yaml(self.meta_path, self.meta, False)
        (self.docs / "index.md").write_text("- 当前状态：开发中\n", encoding="utf-8")

        def check_paused(*_args):
            actual = lib.load_yaml(self.meta_path)
            self.assertEqual(actual["status"], "暂停中")
            self.assertEqual(actual["current_stage"]["status"], "暂停中")
            self.assertEqual(actual["resume_status"], "开发中")
            self.assertFalse(actual["coding_allowed"])
            self.assertEqual(dispatch.gate({"docs": str(self.docs), "phase": 1}), ("skip", "暂停中"))
            return []

        with mock.patch.object(cleanup, "cleanup_task_runtime", side_effect=check_paused):
            self.assertEqual(self.run_cleanup(), 0)
        self.assertIn("- 当前状态：暂停中", (self.docs / "index.md").read_text())
        self.assertEqual(lib.load_yaml(self.meta_path)["execution_mode"], "auto")

    def test_cleanup_keeps_completed_status(self) -> None:
        self.meta["status"] = "已完成"
        self.meta["current_stage"]["status"] = "已完成"
        lib.save_yaml(self.meta_path, self.meta, False)
        before = self.meta_path.read_bytes()
        self.assertEqual(self.run_cleanup(), 0)
        self.assertEqual(self.meta_path.read_bytes(), before)

    def test_failed_preflight_leaves_active_task_metadata_unchanged(self) -> None:
        self.meta.update(status="开发中", coding_allowed=True, execution_mode="auto")
        self.meta["current_stage"]["status"] = "开发中"
        lib.save_yaml(self.meta_path, self.meta, False)
        before = self.meta_path.read_bytes()
        (self.repo / "base.txt").write_text("unfinished\n", encoding="utf-8")
        self.assertEqual(self.run_cleanup(), 2)
        self.assertEqual(self.meta_path.read_bytes(), before)

    def test_runtime_failure_keeps_code_and_stops_task_from_auto_dispatch(self) -> None:
        self.meta.update(status="测试中", coding_allowed=True, execution_mode="auto")
        self.meta["current_stage"]["status"] = "测试中"
        lib.save_yaml(self.meta_path, self.meta, False)
        with mock.patch.object(cleanup, "cleanup_task_runtime", side_effect=RuntimeError("runtime cleanup failed")):
            with self.assertRaisesRegex(RuntimeError, "runtime cleanup failed"):
                self.run_cleanup()
        self.assertTrue(self.repo.exists())
        actual = lib.load_yaml(self.meta_path)
        self.assertEqual(actual["status"], "暂停中")
        self.assertEqual(actual["resume_status"], "测试中")
        self.assertFalse(actual["coding_allowed"])

    def test_symlinked_repo_cannot_escape_task_boundary(self) -> None:
        outside = self.root / "source"
        self.repo.rename(outside)
        self.repo.symlink_to(outside, target_is_directory=True)
        with mock.patch.object(cleanup, "cleanup_task_runtime") as runtime:
            self.assertEqual(self.run_cleanup("--discard-local-changes"), 2)
        runtime.assert_not_called()
        self.assertTrue(outside.exists())


if __name__ == "__main__":
    unittest.main()
