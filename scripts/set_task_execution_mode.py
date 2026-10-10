#!/usr/bin/env python3

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from task_workflow_lib import (
    task_execution_mode,
    load_task_meta,
    load_yaml,
    require_task_status,
    save_yaml,
)


DEFAULT_CONFIG_ROOT = Path("/Users/wuyongli/Documents/sg-project/_workspace/config")


def main() -> int:
    parser = argparse.ArgumentParser(description="Set the task workspace's execution mode without changing coding permission.")
    parser.add_argument("task_id", help="Full task id, e.g. YYYY-MM-DD-任务名")
    parser.add_argument("mode", choices=("manual", "auto"))
    parser.add_argument("--config-root", type=Path, default=DEFAULT_CONFIG_ROOT)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    workspace_cfg = load_yaml(args.config_root / "workspace.yaml")
    docs_root = Path(workspace_cfg["docs_root"])
    if (docs_root / args.task_id).resolve().parent != docs_root.resolve():
        parser.error("task_id must identify one task directly under docs_root")
    meta_path, meta = load_task_meta(docs_root, args.task_id)
    allowed = ("方案中", "开发中", "测试中", "暂停中")
    if args.mode == "manual":
        allowed += ("已完成",)
    require_task_status(meta, allowed, "set execution mode")
    stage = meta.get("current_stage")
    previous_mode = task_execution_mode(meta)
    if stage is not None and not isinstance(stage, dict):
        raise ValueError("invalid current stage: expected a mapping")
    if stage is not None and stage.get("status", meta["status"]) != meta["status"]:
        raise ValueError("current stage status differs from task status; reconcile metadata first")
    if previous_mode == args.mode:
        print(f"execution_mode already {args.mode}; no changes")
        return 0
    meta["execution_mode"] = args.mode
    save_yaml(meta_path, meta, args.dry_run)
    print(f"execution_mode: {previous_mode} -> {args.mode}; status and coding_allowed unchanged")
    print("Record the user's instruction and scope in the active plan; sync index/progress before continuing.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2)
