#!/usr/bin/env python3

from __future__ import annotations

import socket
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import publish_task_workspace as publish_script
import sync_task_workspace as sync_script
import task_workflow_lib as lib


class PortAvailabilityTests(unittest.TestCase):
    def test_port_is_unavailable_when_any_interface_listener_exists(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
            server.bind(("0.0.0.0", 0))
            server.listen(1)
            port = server.getsockname()[1]

            self.assertFalse(lib._port_is_available(port))


class StartRepoRuntimeTests(unittest.TestCase):
    def test_start_repo_runtime_continues_after_allowed_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            marker_path = repo_path / "marker.txt"
            repo_cfg = {
                "key": "demo-repo",
                "runtime": {
                    "auto_start_on_prepare": True,
                    "auto_start_steps": [
                        {
                            "command": "python3 -c 'import sys; sys.exit(9)'",
                            "allow_failure": True,
                        },
                        {
                            "command": "python3 -c \"from pathlib import Path; Path('marker.txt').write_text('ok', encoding='utf-8')\"",
                        },
                    ],
                },
            }

            summary = lib.start_repo_runtime(repo_cfg, repo_path, dry_run=False)

            self.assertTrue(marker_path.exists())
            self.assertEqual(marker_path.read_text(encoding="utf-8"), "ok")
            self.assertEqual(len(summary["executed"]), 1)
            self.assertEqual(len(summary["warnings"]), 1)


class FrontendLocalBackendPatchTests(unittest.TestCase):
    def test_rewrite_node_frontend_environment_creates_missing_environment_toml(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            (repo_path / "package.json").write_text(
                '{"name":"demo-frontend","scripts":{"dev":"vite --host 0.0.0.0"}}',
                encoding="utf-8",
            )

            summary = lib._rewrite_node_frontend_environment(
                {"key": "demo-frontend"},
                {
                    "environment_toml": ".codex/environments/environment.toml",
                    "install_commands": ["npm install"],
                    "start_commands": ["npm run dev"],
                },
                repo_path,
                assigned_port=3110,
                dry_run=False,
            )

            environment_path = repo_path / ".codex/environments/environment.toml"
            self.assertTrue(environment_path.exists())
            content = environment_path.read_text(encoding="utf-8")
            self.assertIn('name = "demo-frontend"', content)
            self.assertIn("npm run dev -- --port 3110 --strictPort", content)
            self.assertEqual(summary["generated_files"], [".codex/environments/environment.toml"])

    def test_patch_frontend_local_backend_env_updates_proxy_and_api_urls(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            task_root = Path(tmpdir) / "2026-06-04-demo-task"
            backend_repo = task_root / "producer-backend__demo-task"
            frontend_repo = task_root / "pf-producer-supplier__demo-task"
            backend_repo.mkdir(parents=True)
            frontend_repo.mkdir(parents=True)

            (backend_repo / "docker").mkdir()
            (backend_repo / "docker/.task.env").write_text(
                "COMPOSE_PROJECT_NAME=20260604-demo\nTASK_APP_HOST_PORT=18897\n",
                encoding="utf-8",
            )
            (frontend_repo / ".env.development").write_text(
                '\n'.join(
                    [
                        'VITE_DEV_HOST = "auto"',
                        'VITE_DEV_PORT = "5173"',
                        'VITE_DEV_PROXY_TARGET = "https://pftest.senguo.me"',
                        'VITE_PF_API_URL = "https://pftest.senguo.me"',
                        'VITE_PASSPORT_API_URL = "https://passporttest.senguo.me"',
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            summary = lib._patch_frontend_local_backend_env(
                {
                    "local_backend_env_file": ".env.development",
                    "local_backend_repo_key": "producer-backend",
                    "backend_task_env_file": "docker/.task.env",
                    "local_backend_proxy_host": "localhost",
                    "local_backend_api_host": "pfzone.senguo.cc",
                },
                frontend_repo,
                dry_run=False,
            )

            updated = (frontend_repo / ".env.development").read_text(encoding="utf-8")
            self.assertIn('VITE_DEV_PROXY_TARGET = "http://localhost:18897"', updated)
            self.assertIn('VITE_PF_API_URL = "http://pfzone.senguo.cc:18897"', updated)
            self.assertEqual(summary["generated_files"], [".env.development"])


class PublishTargetTests(unittest.TestCase):
    def test_resolve_publish_target_kind_supports_human_targets(self) -> None:
        self.assertEqual(lib.resolve_publish_target_kind("产地后端"), "backend")
        self.assertEqual(lib.resolve_publish_target_kind("前端"), "frontend")
        self.assertEqual(lib.resolve_publish_target_kind("产地手机前端"), "mobile_frontend")
        self.assertEqual(lib.resolve_publish_target_kind("产地PC前端"), "pc_frontend")

    def test_classify_repo_publish_kind_uses_runtime_and_notes(self) -> None:
        self.assertEqual(
            lib.classify_repo_publish_kind(
                {"key": "demo-backend", "notes": "产地通后端", "runtime": {"mode": "shared-backend-app"}}
            ),
            "backend",
        )
        self.assertEqual(
            lib.classify_repo_publish_kind(
                {
                    "key": "demo-mobile",
                    "notes": "产地通手机前端",
                    "runtime": {"mode": "patch-node-frontend-environment"},
                }
            ),
            "mobile_frontend",
        )
        self.assertEqual(
            lib.classify_repo_publish_kind(
                {
                    "key": "demo-pc",
                    "notes": "产地通 PC 前端",
                    "runtime": {"mode": "patch-node-frontend-environment"},
                }
            ),
            "pc_frontend",
        )

    def test_resolve_task_publish_repo_key_matches_bound_repo_dynamically(self) -> None:
        repo_cfg_by_key = {
            "custom-backend": {
                "key": "custom-backend",
                "notes": "产地通后端",
                "runtime": {"mode": "shared-backend-app"},
            },
            "custom-mobile": {
                "key": "custom-mobile",
                "notes": "产地通手机前端",
                "runtime": {"mode": "patch-node-frontend-environment"},
            },
            "custom-pc": {
                "key": "custom-pc",
                "notes": "产地通 PC 前端",
                "runtime": {"mode": "patch-node-frontend-environment"},
            },
        }
        bound_repo_keys = ["custom-mobile", "custom-pc", "custom-backend"]

        self.assertEqual(
            lib.resolve_task_publish_repo_key("backend", bound_repo_keys, repo_cfg_by_key),
            "custom-backend",
        )
        self.assertEqual(
            lib.resolve_task_publish_repo_key("mobile_frontend", bound_repo_keys, repo_cfg_by_key),
            "custom-mobile",
        )
        self.assertEqual(
            lib.resolve_task_publish_repo_key("pc_frontend", bound_repo_keys, repo_cfg_by_key),
            "custom-pc",
        )

    def test_resolve_task_publish_repo_key_allows_generic_frontend_when_only_one_exists(self) -> None:
        repo_cfg_by_key = {
            "custom-backend": {
                "key": "custom-backend",
                "notes": "产地通后端",
                "runtime": {"mode": "shared-backend-app"},
            },
            "custom-mobile": {
                "key": "custom-mobile",
                "notes": "产地通手机前端",
                "runtime": {"mode": "patch-node-frontend-environment"},
            },
        }
        bound_repo_keys = ["custom-backend", "custom-mobile"]

        self.assertEqual(
            lib.resolve_task_publish_repo_key("frontend", bound_repo_keys, repo_cfg_by_key),
            "custom-mobile",
        )

    def test_resolve_task_publish_repo_key_rejects_ambiguous_generic_frontend(self) -> None:
        repo_cfg_by_key = {
            "custom-mobile": {
                "key": "custom-mobile",
                "notes": "产地通手机前端",
                "runtime": {"mode": "patch-node-frontend-environment"},
            },
            "custom-pc": {
                "key": "custom-pc",
                "notes": "产地通 PC 前端",
                "runtime": {"mode": "patch-node-frontend-environment"},
            },
        }
        bound_repo_keys = ["custom-mobile", "custom-pc"]

        with self.assertRaisesRegex(ValueError, "generic frontend target is ambiguous"):
            lib.resolve_task_publish_repo_key("frontend", bound_repo_keys, repo_cfg_by_key)

    def test_resolve_requested_repo_keys_returns_all_bound_repos_when_no_targets(self) -> None:
        repo_cfg_by_key = {
            "custom-backend": {"key": "custom-backend", "notes": "产地通后端", "runtime": {"mode": "shared-backend-app"}},
            "custom-mobile": {
                "key": "custom-mobile",
                "notes": "产地通手机前端",
                "runtime": {"mode": "patch-node-frontend-environment"},
            },
        }
        bound_repo_keys = ["custom-backend", "custom-mobile"]

        self.assertEqual(
            lib.resolve_requested_repo_keys([], bound_repo_keys, repo_cfg_by_key),
            ["custom-backend", "custom-mobile"],
        )

    def test_resolve_requested_repo_keys_drops_redundant_frontend_target(self) -> None:
        repo_cfg_by_key = {
            "custom-mobile": {
                "key": "custom-mobile",
                "notes": "产地通手机前端",
                "runtime": {"mode": "patch-node-frontend-environment"},
            },
            "custom-pc": {
                "key": "custom-pc",
                "notes": "产地通 PC 前端",
                "runtime": {"mode": "patch-node-frontend-environment"},
            },
        }
        bound_repo_keys = ["custom-mobile", "custom-pc"]

        self.assertEqual(
            lib.resolve_requested_repo_keys(["前端", "手机前端", "PC前端"], bound_repo_keys, repo_cfg_by_key),
            ["custom-mobile", "custom-pc"],
        )

    def test_resolve_publish_command_uses_runtime_mode(self) -> None:
        self.assertEqual(
            lib.resolve_publish_command({"key": "producer-backend", "runtime": {"mode": "shared-backend-app"}}),
            ["sg", "publish", "jenkins"],
        )
        self.assertEqual(
            lib.resolve_publish_command(
                {"key": "pf-mproducer-supplier", "runtime": {"mode": "patch-node-frontend-environment"}}
            ),
            ["sg", "publish", "local"],
        )

    def test_publish_targets_use_fixed_execution_order(self) -> None:
        ordered = lib.ordered_target_kinds(["pc_frontend", "mobile_frontend", "backend"])
        self.assertEqual(ordered, ["backend", "mobile_frontend", "pc_frontend"])

    def test_normalize_requested_target_kinds_drops_redundant_frontend(self) -> None:
        ordered = lib.normalize_requested_target_kinds(["frontend", "pc_frontend", "mobile_frontend"])
        self.assertEqual(ordered, ["mobile_frontend", "pc_frontend"])

    def test_run_publish_job_returns_error_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = publish_script.run_publish_job(
                {
                    "repo_key": "demo-repo",
                    "target_kind": "backend",
                    "repo_path": tmpdir,
                    "command": [
                        "python3",
                        "-c",
                        "import sys; print('oops-out'); print('oops-err', file=sys.stderr); sys.exit(7)",
                    ],
                }
            )

        self.assertEqual(result["repo_key"], "demo-repo")
        self.assertEqual(result["returncode"], 7)
        self.assertIn("oops-out", result["stdout"])
        self.assertIn("oops-err", result["stderr"])


class SyncTaskTests(unittest.TestCase):
    def test_run_sync_job_reports_dirty_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "repo"
            repo_path.mkdir()
            subprocess.run(["git", "-C", str(repo_path), "init"], check=True, capture_output=True, text=True)
            subprocess.run(
                ["git", "-C", str(repo_path), "config", "user.email", "test@example.com"],
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                ["git", "-C", str(repo_path), "config", "user.name", "Test User"],
                check=True,
                capture_output=True,
                text=True,
            )
            (repo_path / "demo.txt").write_text("base\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo_path), "add", "demo.txt"], check=True, capture_output=True, text=True)
            subprocess.run(
                ["git", "-C", str(repo_path), "commit", "-m", "init"],
                check=True,
                capture_output=True,
                text=True,
            )
            branch = lib.read_current_branch(repo_path)
            (repo_path / "demo.txt").write_text("dirty\n", encoding="utf-8")

            result = sync_script.run_sync_job(
                {
                    "repo_key": "demo-repo",
                    "repo_path": repo_path,
                    "expected_branch": branch,
                }
            )

        self.assertEqual(result["repo_key"], "demo-repo")
        self.assertEqual(result["status"], "failed")
        self.assertIn("working tree has uncommitted changes", result["reason"])
        self.assertIn("M demo.txt", result["stdout"])

    def test_run_sync_job_reports_merge_failure_without_auto_repair(self) -> None:
        repo_path = Path("/tmp/demo-repo")
        with (
            mock.patch.object(sync_script, "read_current_branch", return_value="feature-branch"),
            mock.patch.object(sync_script, "read_status_short", return_value=""),
            mock.patch.object(sync_script, "resolve_origin_default_branch", return_value="master"),
            mock.patch.object(
                sync_script,
                "_run_git_command",
                side_effect=[
                    subprocess.CompletedProcess(args=["git", "fetch"], returncode=0, stdout="fetch-ok\n", stderr=""),
                    subprocess.CompletedProcess(
                        args=["git", "merge"],
                        returncode=1,
                        stdout="Auto-merging demo.txt\nCONFLICT (content): Merge conflict in demo.txt\n",
                        stderr="",
                    ),
                ],
            ) as run_git_command,
        ):
            result = sync_script.run_sync_job(
                {
                    "repo_key": "demo-repo",
                    "repo_path": repo_path,
                    "expected_branch": "feature-branch",
                }
            )

        self.assertEqual(result["repo_key"], "demo-repo")
        self.assertEqual(result["status"], "failed")
        self.assertIn("git merge failed against origin/master", result["reason"])
        self.assertIn("CONFLICT (content)", result["stdout"])
        self.assertEqual(run_git_command.call_count, 2)


if __name__ == "__main__":
    unittest.main()
