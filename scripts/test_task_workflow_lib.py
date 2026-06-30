#!/usr/bin/env python3

from __future__ import annotations

import socket
import subprocess
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

import publish_task_workspace as publish_script
import render_task_dev_portal as portal_script
import serve_task_dev_portal as portal_server_script
import sync_task_workspace as sync_script
import task_workflow_lib as lib
import create_task_workspace as create_script
import next_task_workspace as next_script
import complete_task_workspace as complete_script
import cleanup_task_workspace as cleanup_script


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

    def test_start_repo_runtime_ensures_pytest_for_shared_backend_app(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            docker_dir = repo_path / "docker"
            docker_dir.mkdir()
            (docker_dir / ".task.env").write_text("COMPOSE_PROJECT_NAME=demo\n", encoding="utf-8")
            (docker_dir / "docker-compose.task.yml").write_text("services:\n  app:\n", encoding="utf-8")
            repo_cfg = {
                "key": "producer-backend",
                "runtime": {
                    "mode": "shared-backend-app",
                    "auto_start_on_prepare": True,
                    "auto_start_steps": [
                        {
                            "cwd": "__TASK_DOCKER_DIR__",
                            "command": "docker compose --env-file .task.env -f docker-compose.task.yml up -d app",
                        },
                    ],
                },
            }

            with mock.patch.object(lib, "run_shell") as run_shell_mock:
                summary = lib.start_repo_runtime(repo_cfg, repo_path, dry_run=False)

        commands = [call.args[0] for call in run_shell_mock.call_args_list]
        self.assertIn("docker compose --env-file .task.env -f docker-compose.task.yml up -d app", commands)
        self.assertTrue(any("python -m pytest --version" in command for command in commands))
        self.assertTrue(any("pytest==7.4.4" in command for command in commands))
        self.assertEqual(summary["warnings"], [])

    def test_start_repo_runtime_warns_when_pytest_install_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            docker_dir = repo_path / "docker"
            docker_dir.mkdir()
            (docker_dir / ".task.env").write_text("COMPOSE_PROJECT_NAME=demo\n", encoding="utf-8")
            (docker_dir / "docker-compose.task.yml").write_text("services:\n  app:\n", encoding="utf-8")
            repo_cfg = {
                "key": "producer-backend",
                "runtime": {
                    "mode": "shared-backend-app",
                    "auto_start_on_prepare": True,
                    "auto_start_steps": [],
                },
            }

            with mock.patch.object(
                lib,
                "run_shell",
                side_effect=subprocess.CalledProcessError(1, "docker compose exec app"),
            ):
                summary = lib.start_repo_runtime(repo_cfg, repo_path, dry_run=False)

        self.assertEqual(summary["executed"], [])
        self.assertEqual(len(summary["warnings"]), 1)
        self.assertIn("pytest check/install failed", summary["warnings"][0])


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


class StopTaskRuntimeTests(unittest.TestCase):
    def test_stop_task_runtime_stops_node_frontend_listener(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            (repo_path / ".codex").mkdir()
            (repo_path / ".codex/task-runtime.env").write_text("TASK_WEB_PORT=3018\n", encoding="utf-8")

            with (
                mock.patch.object(
                    lib,
                    "_find_listening_processes",
                    return_value=[{"pid": 12345, "cwd": str(repo_path)}],
                ),
                mock.patch.object(lib.subprocess, "run") as run_mock,
            ):
                messages = lib.stop_task_runtime(
                    {"key": "pf-mproducer-supplier", "runtime": {"mode": "patch-node-frontend-environment"}},
                    repo_path,
                    dry_run=False,
                )

        self.assertEqual(messages, ["pf-mproducer-supplier: stopped pid 12345 on port 3018"])
        run_mock.assert_called_once_with(["kill", "12345"], check=True, text=True)

    def test_stop_task_runtime_skips_listener_outside_current_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "task-repo"
            repo_path.mkdir()
            (repo_path / ".codex").mkdir()
            (repo_path / ".codex/task-runtime.env").write_text("TASK_WEB_PORT=3018\n", encoding="utf-8")

            with (
                mock.patch.object(
                    lib,
                    "_find_listening_processes",
                    return_value=[{"pid": 54321, "cwd": "/tmp/other-task"}],
                ),
                mock.patch.object(lib.subprocess, "run") as run_mock,
            ):
                messages = lib.stop_task_runtime(
                    {"key": "pf-mproducer-supplier", "runtime": {"mode": "patch-node-frontend-environment"}},
                    repo_path,
                    dry_run=False,
                )

        self.assertEqual(
            messages,
            ["pf-mproducer-supplier: skip pid 54321 on port 3018 because it does not belong to current repo"],
        )
        run_mock.assert_not_called()

    def test_stop_task_runtime_stops_shared_backend_container(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            docker_dir = repo_path / "docker"
            docker_dir.mkdir()
            (docker_dir / ".task.env").write_text("TASK_APP_HOST_PORT=18897\n", encoding="utf-8")
            (docker_dir / "docker-compose.task.yml").write_text("services:\n  app:\n", encoding="utf-8")

            with mock.patch.object(lib.subprocess, "run") as run_mock:
                messages = lib.stop_task_runtime(
                    {"key": "producer-backend", "runtime": {"mode": "shared-backend-app"}},
                    repo_path,
                    dry_run=False,
                )

        self.assertEqual(messages, ["producer-backend: stopped task app container"])
        run_mock.assert_called_once_with(
            [
                "docker",
                "compose",
                "--env-file",
                ".task.env",
                "-f",
                "docker-compose.task.yml",
                "stop",
                "app",
            ],
            check=True,
            text=True,
            cwd=str(docker_dir),
        )


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

    def test_run_publish_job_uses_cli_log_failed_status_even_when_exit_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            with (
                mock.patch.object(
                    publish_script.subprocess,
                    "run",
                    return_value=subprocess.CompletedProcess(
                        args=["sg", "publish", "local"],
                        returncode=0,
                        stdout="",
                        stderr="",
                    ),
                ),
                mock.patch.object(
                    publish_script,
                    "find_publish_cli_log_entry",
                    return_value={
                        "status": "failed",
                        "error": {"message": "CONFLICTS: src/a.ts:add/add"},
                    },
                ),
            ):
                result = publish_script.run_publish_job(
                    {
                        "repo_key": "demo-repo",
                        "repo_path": repo_path,
                        "command": ["sg", "publish", "local"],
                    }
                )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["returncode"], 0)
        self.assertEqual(result["log_status"], "failed")
        self.assertIn("CONFLICTS:", result["error_message"])

    def test_parse_unmerged_files_reads_porcelain_conflict_entries(self) -> None:
        status_short = "\n".join(
            [
                "UU pfsource/demo.py",
                "AA src/demo.ts",
                " M unrelated.py",
            ]
        )

        self.assertEqual(
            publish_script.parse_unmerged_files(status_short),
            ["pfsource/demo.py", "src/demo.ts"],
        )

    def test_run_publish_job_reports_develop_merge_conflict_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            with (
                mock.patch.object(
                    publish_script.subprocess,
                    "run",
                    return_value=subprocess.CompletedProcess(
                        args=["sg", "publish", "local"],
                        returncode=1,
                        stdout="CONFLICTS: src/demo.ts\n",
                        stderr="",
                    ),
                ),
                mock.patch.object(publish_script, "find_publish_cli_log_entry", return_value=None),
                mock.patch.object(
                    publish_script,
                    "read_publish_repo_state",
                    return_value={
                        "branch": "develop",
                        "status_short": "UU src/demo.ts",
                        "unmerged_files": ["src/demo.ts"],
                        "merge_in_progress": True,
                    },
                ),
            ):
                result = publish_script.run_publish_job(
                    {
                        "repo_key": "demo-repo",
                        "repo_path": repo_path,
                        "command": ["sg", "publish", "local"],
                    }
                )

        self.assertEqual(result["status"], "conflict")
        self.assertIn("branch develop", result["error_message"])
        self.assertEqual(result["repo_state"]["unmerged_files"], ["src/demo.ts"])

    def test_run_publish_job_requires_explicit_success_signal_for_local_publish(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            with (
                mock.patch.object(
                    publish_script.subprocess,
                    "run",
                    return_value=subprocess.CompletedProcess(
                        args=["sg", "publish", "local"],
                        returncode=0,
                        stdout="build complete\n",
                        stderr="",
                    ),
                ),
                mock.patch.object(publish_script, "find_publish_cli_log_entry", return_value=None),
            ):
                result = publish_script.run_publish_job(
                    {
                        "repo_key": "demo-repo",
                        "repo_path": repo_path,
                        "command": ["sg", "publish", "local"],
                    }
                )

        self.assertEqual(result["status"], "uncertain")
        self.assertIn("no explicit success signal", result["error_message"])

    def test_run_publish_job_accepts_explicit_terminal_success_for_local_publish(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            with (
                mock.patch.object(
                    publish_script.subprocess,
                    "run",
                    return_value=subprocess.CompletedProcess(
                        args=["sg", "publish", "local"],
                        returncode=0,
                        stdout="发布成功\n",
                        stderr="",
                    ),
                ),
                mock.patch.object(publish_script, "find_publish_cli_log_entry", return_value=None),
            ):
                result = publish_script.run_publish_job(
                    {
                        "repo_key": "demo-repo",
                        "repo_path": repo_path,
                        "command": ["sg", "publish", "local"],
                    }
                )

        self.assertEqual(result["status"], "success")

    def test_run_publish_job_wraps_local_publish_with_repo_node_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            with (
                mock.patch.object(
                    publish_script.subprocess,
                    "run",
                    return_value=subprocess.CompletedProcess(
                        args=["zsh", "-lc", "wrapped"],
                        returncode=0,
                        stdout="发布成功\n",
                        stderr="",
                    ),
                ) as run,
                mock.patch.object(publish_script, "find_publish_cli_log_entry", return_value=None) as find_log,
            ):
                result = publish_script.run_publish_job(
                    {
                        "repo_key": "demo-repo",
                        "repo_path": repo_path,
                        "command": ["sg", "publish", "local"],
                        "node_version": "24.14.0",
                    }
                )

        run.assert_called_once()
        executed_command = run.call_args.args[0]
        self.assertEqual(executed_command[:2], ["zsh", "-lc"])
        self.assertIn("fnm use --install-if-missing 24.14.0", executed_command[2])
        self.assertIn("sg publish local", executed_command[2])
        find_log.assert_called_once()
        self.assertEqual(find_log.call_args.args[1], ["sg", "publish", "local"])
        self.assertEqual(result["status"], "success")

    def test_run_publish_job_keeps_cli_log_success_as_uncertain_without_terminal_signal(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            with (
                mock.patch.object(
                    publish_script.subprocess,
                    "run",
                    return_value=subprocess.CompletedProcess(
                        args=["sg", "publish", "local"],
                        returncode=0,
                        stdout="build complete\n",
                        stderr="",
                    ),
                ),
                mock.patch.object(
                    publish_script,
                    "find_publish_cli_log_entry",
                    return_value={"status": "success"},
                ),
            ):
                result = publish_script.run_publish_job(
                    {
                        "repo_key": "demo-repo",
                        "repo_path": repo_path,
                        "command": ["sg", "publish", "local"],
                    }
                )

        self.assertEqual(result["status"], "uncertain")
        self.assertIn("CLI log marked success", result["error_message"])


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


class TaskPortalTests(unittest.TestCase):
    def test_build_frontend_url_uses_pfzone_host(self) -> None:
        self.assertEqual(
            portal_script.build_frontend_url("mobile_frontend", "3018"),
            "http://pfzone.senguo.me:3018/mproducer/",
        )
        self.assertEqual(
            portal_script.build_frontend_url("pc_frontend", "3110"),
            "http://pfzone.senguo.me:3110/producer/",
        )

    def test_portal_server_rerenders_on_every_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_root = Path(tmpdir) / "config"
            config_root.mkdir(parents=True)
            (config_root / "workspace.yaml").write_text(
                'workspace_root: "/tmp/workspace"\n'
                'tasks_root: "/tmp/workspace/_tasks"\n'
                'docs_root: "/tmp/workspace/_docs"\n',
                encoding="utf-8",
            )
            output_path = Path("/tmp/workspace/task-dev-portal.html")
            call_count = 0

            def fake_build_portal_html(*, config_root, output_path, include_completed):
                nonlocal call_count
                call_count += 1
                return (f"<html><body>render-{call_count}</body></html>", 1)

            with mock.patch.object(portal_server_script, "build_portal_html", side_effect=fake_build_portal_html):
                server = portal_server_script.ThreadingHTTPServer(
                    ("127.0.0.1", 0),
                    portal_server_script.make_handler(config_root, output_path),
                )
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    base_url = f"http://127.0.0.1:{server.server_port}/"
                    first = urllib.request.urlopen(base_url, timeout=5).read().decode("utf-8")
                    second = urllib.request.urlopen(base_url, timeout=5).read().decode("utf-8")
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=5)

        self.assertIn("render-1", first)
        self.assertIn("render-2", second)
        self.assertEqual(call_count, 2)


class NextTaskWorkspaceTests(unittest.TestCase):
    def test_create_task_render_plan_is_seed_version(self) -> None:
        text = create_script.render_plan("拍照水印", ["pf-mproducer-supplier"])

        self.assertIn("当前处于任务初始阶段时，默认使用种子版结构", text)
        self.assertIn("## 当前初步判断", text)
        self.assertIn("## 核心决策与原因", text)
        self.assertIn("执行过程写到 `progress.md`", text)
        self.assertNotIn("默认沉淀到 `progress.md`", text)
        self.assertNotIn("## 项目惯例与复用结论", text)
        self.assertNotIn("## 开发方案", text)

    def test_create_task_render_decision_log_template(self) -> None:
        text = create_script.render_decision_log("拍照水印")

        self.assertIn("# 拍照水印 决策记录", text)
        self.assertIn("候选方案", text)
        self.assertIn("当前结论", text)
        self.assertIn("默认不主动创建", text)
        self.assertIn("影响 `plan.md` 阅读", text)

    def test_create_task_render_progress_is_execution_record_only(self) -> None:
        text = create_script.render_progress("拍照水印")

        self.assertIn("当前有效方案、核心决策原因和上线口径写到 `plan.md`", text)
        self.assertNotIn("## 关键取舍", text)

    def test_next_task_workspace_resets_current_stage_and_creates_new_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_root = Path(tmpdir) / "workspace"
            docs_root = workspace_root / "_docs"
            tasks_root = workspace_root / "_tasks"
            config_root = workspace_root / "config"
            task_id = "2026-06-03-部门转货"
            task_docs_root = docs_root / task_id
            task_code_root = tasks_root / task_id
            task_docs_root.mkdir(parents=True)
            task_code_root.mkdir(parents=True)
            config_root.mkdir(parents=True)

            (config_root / "workspace.yaml").write_text(
                "\n".join(
                    [
                        f'workspace_root: "{workspace_root}"',
                        f'tasks_root: "{tasks_root}"',
                        f'docs_root: "{docs_root}"',
                        "documents:",
                        '  index: "index.md"',
                        '  plan: "plan.md"',
                        '  decision_log: "decision-log.md"',
                        '  progress: "progress.md"',
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            (task_docs_root / "meta.yaml").write_text(
                "\n".join(
                    [
                        f"task_id: {task_id}",
                        "status: 已完成",
                        "resume_status: 已完成",
                        "coding_allowed: false",
                        "repos:",
                        "- key: producer-backend",
                        "  repo_dir: producer-backend__部门转货",
                        "  branch: 一期分支",
                        "- key: pf-mproducer-supplier",
                        "  repo_dir: pf-mproducer-supplier__部门转货",
                        "  branch: 一期分支",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            (task_docs_root / "index.md").write_text(
                "\n".join(
                    [
                        "# 部门转货",
                        "",
                        "## 任务摘要",
                        "- 当前状态：已完成",
                        "- 一句话目标：一期目标",
                        "- 当前结论：一期已上线",
                        "- 当前阻塞：无",
                        "- 下一步：无",
                        "",
                        "## 文档导航",
                        "- 事实文件：./meta.yaml",
                        "- 计划文档：./plan.md",
                        "- 进度文档：./progress.md",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            (task_docs_root / "plan.md").write_text("# 一期方案\n", encoding="utf-8")
            (task_docs_root / "decision-log.md").write_text("# 一期决策记录\n", encoding="utf-8")
            (task_docs_root / "progress.md").write_text(
                "# 部门转货 任务进度\n\n## 当前进展\n- 已完成：一期完成\n",
                encoding="utf-8",
            )

            (task_code_root / "producer-backend__部门转货").mkdir()
            (task_code_root / "pf-mproducer-supplier__部门转货").mkdir()

            with (
                mock.patch.object(next_script, "validate_repo_state", return_value=[]),
                mock.patch.object(next_script, "run") as run_mock,
                mock.patch("sys.argv", [
                    "next_task_workspace.py",
                    task_id,
                    "加工单扫码支持托盘码二期",
                    "--config-root",
                    str(config_root),
                ]),
            ):
                self.assertEqual(next_script.main(), 0)

            meta = lib.load_yaml(task_docs_root / "meta.yaml")
            self.assertEqual(meta["status"], "方案中")
            self.assertEqual(meta["resume_status"], "方案中")
            self.assertFalse(meta["coding_allowed"])
            self.assertEqual(meta["phase"], 2)
            self.assertEqual(meta["current_task_name"], "加工单扫码支持托盘码二期")
            self.assertEqual(meta["active_plan"], "plan-加工单扫码支持托盘码二期.md")
            self.assertNotIn("active_decision_log", meta)
            self.assertEqual(meta["repos"][0]["branch"], "加工单扫码支持托盘码二期")
            self.assertEqual(meta["previous_phases"][0]["plan"], "plan.md")
            self.assertEqual(meta["previous_phases"][0]["decision_log"], "decision-log.md")

            new_plan_path = task_docs_root / "plan-加工单扫码支持托盘码二期.md"
            self.assertTrue(new_plan_path.exists())
            new_plan_text = new_plan_path.read_text(encoding="utf-8")
            self.assertIn("# 加工单扫码支持托盘码二期", new_plan_text)
            self.assertIn("## 核心决策与原因", new_plan_text)
            new_decision_log_path = task_docs_root / "decision-log-加工单扫码支持托盘码二期.md"
            self.assertFalse(new_decision_log_path.exists())

            index_text = (task_docs_root / "index.md").read_text(encoding="utf-8")
            self.assertIn("- 当前状态：方案中", index_text)
            self.assertIn("- 当前阶段任务：加工单扫码支持托盘码二期", index_text)
            self.assertIn("- 前置阶段任务：部门转货", index_text)
            self.assertIn("- 当前阶段计划：./plan-加工单扫码支持托盘码二期.md", index_text)
            self.assertIn("- 历史阶段计划：./plan.md", index_text)

            progress_text = (task_docs_root / "progress.md").read_text(encoding="utf-8")
            self.assertIn("下一阶段开启", progress_text)
            self.assertIn("加工单扫码支持托盘码二期", progress_text)
            self.assertNotIn("decision-log-加工单扫码支持托盘码二期.md", progress_text)

            commands = [call.args[0] for call in run_mock.call_args_list]
            self.assertIn(
                ["git", "-C", str(task_code_root / "producer-backend__部门转货"), "fetch", "origin", "--prune"],
                commands,
            )
            self.assertIn(
                [
                    "git",
                    "-C",
                    str(task_code_root / "producer-backend__部门转货"),
                    "checkout",
                    "-B",
                    "加工单扫码支持托盘码二期",
                    "origin/master",
                ],
                commands,
            )

    def test_next_task_workspace_can_switch_only_selected_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_root = Path(tmpdir) / "workspace"
            docs_root = workspace_root / "_docs"
            tasks_root = workspace_root / "_tasks"
            config_root = workspace_root / "config"
            task_id = "2026-06-14-加工扫托盘码"
            task_docs_root = docs_root / task_id
            task_code_root = tasks_root / task_id
            task_docs_root.mkdir(parents=True)
            task_code_root.mkdir(parents=True)
            config_root.mkdir(parents=True)

            (config_root / "workspace.yaml").write_text(
                "\n".join(
                    [
                        f'workspace_root: "{workspace_root}"',
                        f'tasks_root: "{tasks_root}"',
                        f'docs_root: "{docs_root}"',
                        "documents:",
                        '  index: "index.md"',
                        '  plan: "plan.md"',
                        '  decision_log: "decision-log.md"',
                        '  progress: "progress.md"',
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            (task_docs_root / "meta.yaml").write_text(
                "\n".join(
                    [
                        f"task_id: {task_id}",
                        "status: 已完成",
                        "resume_status: 已完成",
                        "coding_allowed: false",
                        "repos:",
                        "- key: producer-backend",
                        "  repo_dir: producer-backend__加工扫托盘码",
                        "  branch: 一期后端分支",
                        "- key: pf-mproducer-supplier",
                        "  repo_dir: pf-mproducer-supplier__加工扫托盘码",
                        "  branch: 一期手机分支",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            (task_docs_root / "index.md").write_text("# 加工扫托盘码\n", encoding="utf-8")
            (task_docs_root / "plan.md").write_text("# 一期方案\n", encoding="utf-8")
            (task_docs_root / "decision-log.md").write_text("# 一期决策记录\n", encoding="utf-8")
            (task_docs_root / "progress.md").write_text("# 任务进度\n\n## 变更记录\n", encoding="utf-8")

            (task_code_root / "producer-backend__加工扫托盘码").mkdir()
            (task_code_root / "pf-mproducer-supplier__加工扫托盘码").mkdir()

            def fake_validate(repo_path: Path, require_remote_sync: bool, expected_branch: str | None = None) -> list[str]:
                if repo_path.name == "pf-mproducer-supplier__加工扫托盘码":
                    return []
                if expected_branch == "一期后端分支":
                    return []
                return ["unexpected branch check"]

            with (
                mock.patch.object(next_script, "validate_repo_state", side_effect=fake_validate),
                mock.patch.object(next_script, "run") as run_mock,
                mock.patch("sys.argv", [
                    "next_task_workspace.py",
                    task_id,
                    "先建优化任务-加工一个托盘码一行",
                    "--repo",
                    "pf-mproducer-supplier",
                    "--config-root",
                    str(config_root),
                ]),
            ):
                self.assertEqual(next_script.main(), 0)

            meta = lib.load_yaml(task_docs_root / "meta.yaml")
            self.assertEqual(meta["phase"], 2)
            self.assertEqual(meta["current_task_name"], "先建优化任务-加工一个托盘码一行")
            self.assertNotIn("active_decision_log", meta)
            self.assertEqual(meta["repos"][0]["branch"], "一期后端分支")
            self.assertEqual(meta["repos"][1]["branch"], "先建优化任务-加工一个托盘码一行")

            new_plan_path = task_docs_root / "plan-先建优化任务-加工一个托盘码一行.md"
            self.assertTrue(new_plan_path.exists())
            self.assertIn("涉及仓库：pf-mproducer-supplier", new_plan_path.read_text(encoding="utf-8"))
            new_decision_log_path = task_docs_root / "decision-log-先建优化任务-加工一个托盘码一行.md"
            self.assertFalse(new_decision_log_path.exists())

            commands = [call.args[0] for call in run_mock.call_args_list]
            self.assertIn(
                [
                    "git",
                    "-C",
                    str(task_code_root / "pf-mproducer-supplier__加工扫托盘码"),
                    "checkout",
                    "-B",
                    "先建优化任务-加工一个托盘码一行",
                    "origin/master",
                ],
                commands,
            )
            self.assertNotIn(
                [
                    "git",
                    "-C",
                    str(task_code_root / "producer-backend__加工扫托盘码"),
                    "checkout",
                    "-B",
                    "先建优化任务-加工一个托盘码一行",
                    "origin/master",
                ],
                commands,
            )

    def test_next_task_workspace_allows_previous_phase_branch_without_upstream(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_root = Path(tmpdir) / "workspace"
            docs_root = workspace_root / "_docs"
            tasks_root = workspace_root / "_tasks"
            config_root = workspace_root / "config"
            task_id = "2026-06-24-阶段切换"
            task_docs_root = docs_root / task_id
            task_code_root = tasks_root / task_id
            repo_path = task_code_root / "producer-backend__阶段切换"
            task_docs_root.mkdir(parents=True)
            repo_path.mkdir(parents=True)
            config_root.mkdir(parents=True)

            (config_root / "workspace.yaml").write_text(
                "\n".join(
                    [
                        f'workspace_root: "{workspace_root}"',
                        f'tasks_root: "{tasks_root}"',
                        f'docs_root: "{docs_root}"',
                        "documents:",
                        '  index: "index.md"',
                        '  plan: "plan.md"',
                        '  decision_log: "decision-log.md"',
                        '  progress: "progress.md"',
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            (task_docs_root / "meta.yaml").write_text(
                "\n".join(
                    [
                        f"task_id: {task_id}",
                        "status: 已完成",
                        "resume_status: 已完成",
                        "coding_allowed: false",
                        "repos:",
                        "- key: producer-backend",
                        "  repo_dir: producer-backend__阶段切换",
                        "  branch: 已上线一期分支",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            (task_docs_root / "index.md").write_text("# 阶段切换\n", encoding="utf-8")
            (task_docs_root / "plan.md").write_text("# 一期方案\n", encoding="utf-8")
            (task_docs_root / "decision-log.md").write_text("# 一期决策记录\n", encoding="utf-8")
            (task_docs_root / "progress.md").write_text("# 任务进度\n\n## 变更记录\n", encoding="utf-8")

            subprocess.run(["git", "-C", str(repo_path), "init"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(
                ["git", "-C", str(repo_path), "checkout", "-b", "已上线一期分支"],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            with (
                mock.patch.object(next_script, "run") as run_mock,
                mock.patch("sys.argv", [
                    "next_task_workspace.py",
                    task_id,
                    "二期新任务",
                    "--config-root",
                    str(config_root),
                ]),
            ):
                self.assertEqual(next_script.main(), 0)

            meta = lib.load_yaml(task_docs_root / "meta.yaml")
            self.assertEqual(meta["phase"], 2)
            self.assertEqual(meta["repos"][0]["branch"], "二期新任务")

            commands = [call.args[0] for call in run_mock.call_args_list]
            self.assertIn(
                ["git", "-C", str(repo_path), "fetch", "origin", "--prune"],
                commands,
            )
            self.assertIn(
                ["git", "-C", str(repo_path), "checkout", "-B", "二期新任务", "origin/master"],
                commands,
            )

    def test_next_task_workspace_accepts_human_target_alias(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_root = Path(tmpdir) / "workspace"
            docs_root = workspace_root / "_docs"
            tasks_root = workspace_root / "_tasks"
            config_root = workspace_root / "config"
            task_id = "2026-06-14-加工扫托盘码"
            task_docs_root = docs_root / task_id
            task_code_root = tasks_root / task_id
            task_docs_root.mkdir(parents=True)
            task_code_root.mkdir(parents=True)
            config_root.mkdir(parents=True)

            (config_root / "workspace.yaml").write_text(
                "\n".join(
                    [
                        f'workspace_root: "{workspace_root}"',
                        f'tasks_root: "{tasks_root}"',
                        f'docs_root: "{docs_root}"',
                        "documents:",
                        '  index: "index.md"',
                        '  plan: "plan.md"',
                        '  decision_log: "decision-log.md"',
                        '  progress: "progress.md"',
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            (config_root / "repositories.yaml").write_text(
                "\n".join(
                    [
                        "repositories:",
                        "- key: producer-backend",
                        '  path: "/tmp/producer-backend"',
                        '  remote: "git@example.com:producer-backend.git"',
                        '  notes: "产地通后端"',
                        "  runtime:",
                        '    mode: "shared-backend-app"',
                        "- key: pf-mproducer-supplier",
                        '  path: "/tmp/pf-mproducer-supplier"',
                        '  remote: "git@example.com:pf-mproducer-supplier.git"',
                        '  notes: "产地通手机前端"',
                        "  runtime:",
                        '    mode: "patch-node-frontend-environment"',
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            (task_docs_root / "meta.yaml").write_text(
                "\n".join(
                    [
                        f"task_id: {task_id}",
                        "status: 已完成",
                        "resume_status: 已完成",
                        "coding_allowed: false",
                        "repos:",
                        "- key: producer-backend",
                        "  repo_dir: producer-backend__加工扫托盘码",
                        "  branch: 一期后端分支",
                        "- key: pf-mproducer-supplier",
                        "  repo_dir: pf-mproducer-supplier__加工扫托盘码",
                        "  branch: 一期手机分支",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            (task_docs_root / "index.md").write_text("# 加工扫托盘码\n", encoding="utf-8")
            (task_docs_root / "plan.md").write_text("# 一期方案\n", encoding="utf-8")
            (task_docs_root / "decision-log.md").write_text("# 一期决策记录\n", encoding="utf-8")
            (task_docs_root / "progress.md").write_text("# 任务进度\n\n## 变更记录\n", encoding="utf-8")

            (task_code_root / "producer-backend__加工扫托盘码").mkdir()
            (task_code_root / "pf-mproducer-supplier__加工扫托盘码").mkdir()

            with (
                mock.patch.object(next_script, "validate_repo_state", return_value=[]),
                mock.patch.object(next_script, "run") as run_mock,
                mock.patch("sys.argv", [
                    "next_task_workspace.py",
                    task_id,
                    "先建优化任务-加工一个托盘码一行",
                    "--repo",
                    "手机前端",
                    "--config-root",
                    str(config_root),
                ]),
            ):
                self.assertEqual(next_script.main(), 0)

            commands = [call.args[0] for call in run_mock.call_args_list]
            self.assertIn(
                [
                    "git",
                    "-C",
                    str(task_code_root / "pf-mproducer-supplier__加工扫托盘码"),
                    "checkout",
                    "-B",
                    "先建优化任务-加工一个托盘码一行",
                    "origin/master",
                ],
                commands,
            )

    def test_next_task_workspace_requires_completed_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_root = Path(tmpdir) / "workspace"
            docs_root = workspace_root / "_docs"
            tasks_root = workspace_root / "_tasks"
            config_root = workspace_root / "config"
            task_id = "2026-06-03-部门转货"
            task_docs_root = docs_root / task_id
            task_code_root = tasks_root / task_id
            task_docs_root.mkdir(parents=True)
            task_code_root.mkdir(parents=True)
            config_root.mkdir(parents=True)

            (config_root / "workspace.yaml").write_text(
                "\n".join(
                    [
                        f'workspace_root: "{workspace_root}"',
                        f'tasks_root: "{tasks_root}"',
                        f'docs_root: "{docs_root}"',
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            (task_docs_root / "meta.yaml").write_text(
                "\n".join(
                    [
                        f"task_id: {task_id}",
                        "status: 开发中",
                        "resume_status: 开发中",
                        "coding_allowed: true",
                        "repos: []",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            with mock.patch("sys.argv", [
                "next_task_workspace.py",
                task_id,
                "加工单扫码支持托盘码二期",
                "--config-root",
                str(config_root),
            ]):
                with self.assertRaisesRegex(ValueError, "next requires task status in \\[已完成\\]"):
                    next_script.main()


class CompleteCleanupRuntimeTests(unittest.TestCase):
    def test_complete_task_workspace_stops_runtime_before_marking_complete(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_root = Path(tmpdir) / "workspace"
            docs_root = workspace_root / "_docs"
            tasks_root = workspace_root / "_tasks"
            config_root = workspace_root / "config"
            task_id = "2026-06-03-部门转货"
            task_docs_root = docs_root / task_id
            task_code_root = tasks_root / task_id
            task_docs_root.mkdir(parents=True)
            task_code_root.mkdir(parents=True)
            config_root.mkdir(parents=True)

            (config_root / "workspace.yaml").write_text(
                "\n".join(
                    [
                        f'workspace_root: "{workspace_root}"',
                        f'tasks_root: "{tasks_root}"',
                        f'docs_root: "{docs_root}"',
                        "documents:",
                        '  index: "index.md"',
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            (config_root / "repositories.yaml").write_text(
                "\n".join(
                    [
                        "repositories:",
                        "- key: producer-backend",
                        '  path: "/tmp/producer-backend"',
                        '  remote: "git@example.com:producer-backend.git"',
                        "  runtime:",
                        '    mode: "shared-backend-app"',
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            (task_docs_root / "meta.yaml").write_text(
                "\n".join(
                    [
                        f"task_id: {task_id}",
                        "status: 测试中",
                        "resume_status: 测试中",
                        "coding_allowed: true",
                        "repos:",
                        "- key: producer-backend",
                        "  repo_dir: producer-backend__部门转货",
                        "  branch: 部门转货",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            (task_docs_root / "index.md").write_text("- 当前状态：测试中\n", encoding="utf-8")
            (task_code_root / "producer-backend__部门转货").mkdir()

            with (
                mock.patch.object(complete_script, "validate_repo_state", return_value=[]),
                mock.patch.object(complete_script, "stop_task_runtime", create=True) as stop_runtime_mock,
                mock.patch("sys.argv", [
                    "complete_task_workspace.py",
                    task_id,
                    "--config-root",
                    str(config_root),
                ]),
            ):
                self.assertEqual(complete_script.main(), 0)

            stop_runtime_mock.assert_called_once()
            self.assertEqual(stop_runtime_mock.call_args.args[0]["runtime"]["mode"], "shared-backend-app")

    def test_cleanup_task_workspace_stops_runtime_before_removing_task_code(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_root = Path(tmpdir) / "workspace"
            docs_root = workspace_root / "_docs"
            tasks_root = workspace_root / "_tasks"
            config_root = workspace_root / "config"
            task_id = "2026-06-03-部门转货"
            task_docs_root = docs_root / task_id
            task_code_root = tasks_root / task_id
            task_docs_root.mkdir(parents=True)
            task_code_root.mkdir(parents=True)
            config_root.mkdir(parents=True)

            (config_root / "workspace.yaml").write_text(
                "\n".join(
                    [
                        f'workspace_root: "{workspace_root}"',
                        f'tasks_root: "{tasks_root}"',
                        f'docs_root: "{docs_root}"',
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            (config_root / "repositories.yaml").write_text(
                "\n".join(
                    [
                        "repositories:",
                        "- key: producer-backend",
                        '  path: "/tmp/producer-backend"',
                        '  remote: "git@example.com:producer-backend.git"',
                        "  runtime:",
                        '    mode: "shared-backend-app"',
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            (task_docs_root / "meta.yaml").write_text(
                "\n".join(
                    [
                        f"task_id: {task_id}",
                        "status: 已完成",
                        "resume_status: 已完成",
                        "coding_allowed: false",
                        "repos:",
                        "- key: producer-backend",
                        "  repo_dir: producer-backend__部门转货",
                        "  branch: 部门转货",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            (task_code_root / "producer-backend__部门转货").mkdir()

            with (
                mock.patch.object(cleanup_script, "validate_repo_state", return_value=[]),
                mock.patch.object(cleanup_script, "stop_task_runtime", create=True) as stop_runtime_mock,
                mock.patch("sys.argv", [
                    "cleanup_task_workspace.py",
                    task_id,
                    "--config-root",
                    str(config_root),
                ]),
            ):
                self.assertEqual(cleanup_script.main(), 0)

            stop_runtime_mock.assert_called_once()
            self.assertEqual(stop_runtime_mock.call_args.args[0]["runtime"]["mode"], "shared-backend-app")


if __name__ == "__main__":
    unittest.main()
