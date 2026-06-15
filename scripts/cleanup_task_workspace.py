#!/usr/bin/env python3

from __future__ import annotations

import argparse
from pathlib import Path

from task_workflow_lib import (
    load_task_meta,
    load_yaml,
    require_task_status,
    resolve_repo_path,
    safe_remove_path,
    stop_task_runtime,
    validate_repo_state,
)


DEFAULT_CONFIG_ROOT = Path("/Users/wuyongli/Documents/sg-project/_workspace/config")


def main() -> int:
    parser = argparse.ArgumentParser(description="Remove one completed task code directory after publish-safe checks.")
    parser.add_argument("task_id", help="Full task id, e.g. YYYY-MM-DD-原始任务名")
    parser.add_argument("--config-root", type=Path, default=DEFAULT_CONFIG_ROOT)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    workspace_cfg = load_yaml(args.config_root / "workspace.yaml")
    repositories_cfg = load_yaml(args.config_root / "repositories.yaml")
    docs_root = Path(workspace_cfg["docs_root"])
    tasks_root = Path(workspace_cfg["tasks_root"])
    require_remote_sync = bool(workspace_cfg.get("cleanup_requires_remote_sync", True))
    repo_cfg_by_key = {
        str(repo["key"]): repo
        for repo in repositories_cfg.get("repositories", [])
        if isinstance(repo, dict) and repo.get("key")
    }

    _meta_path, meta = load_task_meta(docs_root, args.task_id)
    require_task_status(meta, ("已完成",), "cleanup")

    failed = False
    repos = meta.get("repos", [])
    if not isinstance(repos, list):
        raise ValueError(f"invalid repos in task meta for task: {args.task_id}")
    for repo_meta in repos:
        if not isinstance(repo_meta, dict):
            continue
        repo_key = str(repo_meta.get("key") or "unknown")
        repo_path = resolve_repo_path(tasks_root, args.task_id, repo_meta)
        expected_branch = str(repo_meta.get("branch") or "")
        issues = validate_repo_state(repo_path, require_remote_sync, expected_branch or None)
        if issues:
            failed = True
            print(f"[FAIL] {repo_key} -> {repo_path}")
            for issue in issues:
                print(f"  - {issue}")
        else:
            print(f"[OK] {repo_key} -> {repo_path}")

    if failed:
        print("cleanup blocked")
        return 2

    for repo_meta in repos:
        if not isinstance(repo_meta, dict):
            continue
        repo_key = str(repo_meta.get("key") or "unknown")
        repo_path = resolve_repo_path(tasks_root, args.task_id, repo_meta)
        repo_cfg = repo_cfg_by_key.get(repo_key, repo_meta)
        for message in stop_task_runtime(repo_cfg, repo_path, args.dry_run):
            print(f"[STOP] {repo_key} -> {message}")

    safe_remove_path(tasks_root / args.task_id, args.dry_run)
    print("task code cleanup complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
