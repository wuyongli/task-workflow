#!/usr/bin/env python3

from __future__ import annotations

import argparse
import datetime as dt
import shlex
import subprocess
import sys
from zoneinfo import ZoneInfo


def main() -> int:
    parser = argparse.ArgumentParser(description="Read recent direct messages using a fresh Beijing-time upper bound.")
    recipient = parser.add_mutually_exclusive_group(required=True)
    recipient.add_argument("--user", help="Verified DWS userId")
    recipient.add_argument("--open-dingtalk-id", help="Verified DWS openDingTalkId")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--profile", help="Verified DWS organization profile, if needed")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("--limit must be positive")

    command = ["dws", "chat", "message", "list-direct"]
    if args.user is not None:
        command.extend(["--user", args.user])
    else:
        command.extend(["--open-dingtalk-id", args.open_dingtalk_id])
    if args.profile is not None:
        command.extend(["--profile", args.profile])

    # Read the clock at execution, never from the conversation or saved progress.
    query_time = dt.datetime.now(dt.timezone.utc).astimezone(ZoneInfo("Asia/Shanghai"))
    command.extend([
        "--time", query_time.strftime("%Y-%m-%d %H:%M:%S"),
        "--forward=false", "--limit", str(args.limit), "--format", "json",
    ])
    print(f"[QUERY] upper_bound={query_time.isoformat(timespec='seconds')} timezone=Asia/Shanghai limit={args.limit}",
          file=sys.stderr)
    if args.dry_run:
        print(shlex.join(command))
        return 0
    # Keep DWS's JSON stdout and errors intact; failures are not empty results.
    return subprocess.run(command, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
