#!/usr/bin/env python3

from __future__ import annotations

import socket
import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
