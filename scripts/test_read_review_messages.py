from __future__ import annotations

import contextlib
import datetime as dt
import importlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


class ReadReviewMessagesTests(unittest.TestCase):
    def reader(self):
        self.assertTrue(Path(__file__).with_name("read_review_messages.py").is_file())
        return importlib.import_module("read_review_messages")

    def call_reader(self, reader, *args: str) -> int:
        with mock.patch("sys.argv", ["read_review_messages.py", *args]):
            return reader.main()

    def test_fresh_upper_bound_includes_message_missed_by_old_query(self) -> None:
        reader = self.reader()
        received = dt.datetime(2026, 11, 10, 16, 33)
        old_upper = dt.datetime(2026, 11, 10, 15, 42)
        self.assertGreater(received, old_upper)
        found = []

        def fake_dws(command, **_kwargs):
            cutoff = dt.datetime.strptime(command[command.index("--time") + 1], "%Y-%m-%d %H:%M:%S")
            if received < cutoff:
                found.append("review-at-16:33")
            return SimpleNamespace(returncode=0)

        # 09:05 UTC is 17:05 Beijing time, after the review arrived.
        with (
            mock.patch.object(reader.dt, "datetime", wraps=dt.datetime) as clock,
            mock.patch.object(reader.subprocess, "run", side_effect=fake_dws) as run,
            contextlib.redirect_stderr(io.StringIO()) as diagnostics,
        ):
            clock.now.return_value = dt.datetime(2026, 11, 10, 9, 5, tzinfo=dt.timezone.utc)
            self.assertEqual(self.call_reader(reader, "--user", "reviewer"), 0)
        command = run.call_args.args[0]
        self.assertEqual(found, ["review-at-16:33"])
        self.assertIn("--forward=false", command)
        self.assertEqual(command[command.index("--limit") + 1], "10")
        self.assertEqual(command[command.index("--format") + 1], "json")
        self.assertIn("2026-11-10T17:05:00+08:00", diagnostics.getvalue())

    def test_each_invocation_refreshes_upper_bound(self) -> None:
        reader = self.reader()
        instants = [dt.datetime(2026, 11, 10, 7, 42, tzinfo=dt.timezone.utc),
                    dt.datetime(2026, 11, 10, 9, 5, tzinfo=dt.timezone.utc)]
        with (
            mock.patch.object(reader.dt, "datetime", wraps=dt.datetime) as clock,
            mock.patch.object(reader.subprocess, "run", return_value=SimpleNamespace(returncode=0)) as run,
            contextlib.redirect_stderr(io.StringIO()),
        ):
            clock.now.side_effect = instants
            self.call_reader(reader, "--user", "reviewer")
            self.call_reader(reader, "--user", "reviewer")
        cutoffs = [call.args[0][call.args[0].index("--time") + 1] for call in run.call_args_list]
        self.assertEqual(cutoffs, ["2026-11-10 15:42:00", "2026-11-10 17:05:00"])

    def test_open_id_profile_limit_and_beijing_date_rollover(self) -> None:
        reader = self.reader()
        with (
            mock.patch.object(reader.dt, "datetime", wraps=dt.datetime) as clock,
            mock.patch.object(reader.subprocess, "run", return_value=SimpleNamespace(returncode=0)) as run,
            contextlib.redirect_stderr(io.StringIO()),
        ):
            clock.now.return_value = dt.datetime(2026, 11, 10, 23, 50, tzinfo=dt.timezone.utc)
            self.assertEqual(self.call_reader(reader, "--open-dingtalk-id", "open-reviewer",
                                             "--profile", "verified-org", "--limit", "20"), 0)
        command = run.call_args.args[0]
        self.assertEqual(command[command.index("--time") + 1], "2026-11-11 07:50:00")
        self.assertEqual(command[command.index("--open-dingtalk-id") + 1], "open-reviewer")
        self.assertEqual(command[command.index("--profile") + 1], "verified-org")
        self.assertEqual(command[command.index("--limit") + 1], "20")
        self.assertNotIn("--user", command)

    def test_dry_run_does_not_query_dws(self) -> None:
        reader = self.reader()
        with (
            mock.patch.object(reader.subprocess, "run") as run,
            contextlib.redirect_stdout(io.StringIO()) as preview,
            contextlib.redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(self.call_reader(reader, "--user", "reviewer", "--dry-run"), 0)
        run.assert_not_called()
        self.assertIn("--time", preview.getvalue())

    def test_invalid_arguments_never_query_dws(self) -> None:
        reader = self.reader()
        for args in ([], ["--user", "a", "--open-dingtalk-id", "b"],
                     ["--user", "a", "--limit", "0"], ["--user", "a", "--time", "2026-11-10 15:42:00"]):
            with self.subTest(args=args), mock.patch.object(reader.subprocess, "run") as run:
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                    self.call_reader(reader, *args)
                self.assertEqual(error.exception.code, 2)
                run.assert_not_called()

    def test_dws_failure_is_not_retried_or_reported_as_empty_success(self) -> None:
        reader = self.reader()
        with (
            mock.patch.object(reader.subprocess, "run", return_value=SimpleNamespace(returncode=7)) as run,
            contextlib.redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(self.call_reader(reader, "--user", "reviewer"), 7)
        run.assert_called_once()

    def test_subprocess_preserves_dws_json_errors_and_exit_code(self) -> None:
        self.reader()
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "dws"
            for exit_code in (0, 7):
                with self.subTest(exit_code=exit_code):
                    executable.write_text(
                        "#!/bin/sh\nprintf '%s\\n' '{\"fixture\":true}'\n"
                        f"printf '%s\\n' 'fixture diagnostic' >&2\nexit {exit_code}\n",
                        encoding="utf-8",
                    )
                    executable.chmod(0o755)
                    result = subprocess.run([
                        sys.executable, str(Path(__file__).with_name("read_review_messages.py")),
                        "--user", "fixture-reviewer",
                    ], env={**os.environ, "PATH": directory}, capture_output=True, text=True)
                    self.assertEqual(result.returncode, exit_code)
                    self.assertEqual(json.loads(result.stdout), {"fixture": True})
                    self.assertIn("[QUERY]", result.stderr)
                    self.assertIn("fixture diagnostic", result.stderr)


if __name__ == "__main__":
    unittest.main()
