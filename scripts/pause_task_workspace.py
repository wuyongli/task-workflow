#!/usr/bin/env python3

from __future__ import annotations

import argparse
from pathlib import Path

from task_workflow_lib import load_task_meta, load_yaml, require_task_status, save_yaml, update_index_status


DEFAULT_CONFIG_ROOT = Path("/Users/wuyongli/Documents/sg-project/_workspace/config")


def main() -> int:
    parser = argparse.ArgumentParser(description="Pause one task without deleting its task-scoped repos.")
    parser.add_argument("task_id", help="Full task id, e.g. YYYY-MM-DD-原始任务名")
    parser.add_argument("--config-root", type=Path, default=DEFAULT_CONFIG_ROOT)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    workspace_cfg = load_yaml(args.config_root / "workspace.yaml")
    docs_root = Path(workspace_cfg["docs_root"])
    documents = workspace_cfg.get("documents", {})

    meta_path, meta = load_task_meta(docs_root, args.task_id)
    previous_status = require_task_status(meta, ("方案中", "开发中", "测试中"), "pause")
    meta["resume_status"] = previous_status
    meta["status"] = "暂停中"
    save_yaml(meta_path, meta, args.dry_run)

    index_path = docs_root / args.task_id / documents.get("index", "index.md")
    update_index_status(index_path, "暂停中", args.dry_run)
    print("task pause complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
