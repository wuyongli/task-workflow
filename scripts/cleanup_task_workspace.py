#!/usr/bin/env python3

from __future__ import annotations

import argparse
from pathlib import Path

from task_workflow_lib import (
    cleanup_task_runtime,
    load_task_meta,
    load_yaml,
    require_task_status,
    resolve_repo_path,
    safe_remove_path,
    save_yaml,
    update_index_status,
    validate_repo_state_for_cleanup,
)


DEFAULT_CONFIG_ROOT = Path("/Users/wuyongli/Documents/sg-project/_workspace/config")


def main() -> int:
    parser = argparse.ArgumentParser(description="Remove one task code directory, including unfinished tasks, while preserving task documents.")
    parser.add_argument("task_id", help="Full task id, e.g. YYYY-MM-DD-原始任务名")
    parser.add_argument("--config-root", type=Path, default=DEFAULT_CONFIG_ROOT)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--discard-local-changes",
        action="store_true",
        help="Explicitly discard uncommitted files and unpushed commits in this task's local clones.",
    )
    args = parser.parse_args()

    workspace_cfg = load_yaml(args.config_root / "workspace.yaml")
    repositories_cfg = load_yaml(args.config_root / "repositories.yaml")
    docs_root = Path(workspace_cfg["docs_root"])
    tasks_root = Path(workspace_cfg["tasks_root"])
    if not args.task_id or Path(args.task_id).name != args.task_id or args.task_id in (".", ".."):
        raise ValueError("cleanup requires a task id directly under tasks_root")
    task_root = tasks_root / args.task_id
    if task_root.is_symlink():
        raise ValueError("cleanup does not accept a symlinked task directory")
    repo_cfg_by_key = {
        str(repo["key"]): repo
        for repo in repositories_cfg.get("repositories", [])
        if isinstance(repo, dict) and repo.get("key")
    }

    meta_path, meta = load_task_meta(docs_root, args.task_id)
    require_task_status(meta, ("方案中", "开发中", "测试中", "暂停中", "已完成"), "cleanup")

    if args.discard_local_changes:
        print("[DISCARD] Explicitly discarding local files and commits in all task clones; task documents are preserved.")

    failed = False
    repos = meta.get("repos", [])
    if not isinstance(repos, list):
        raise ValueError(f"invalid repos in task meta for task: {args.task_id}")
    for repo_meta in repos:
        if not isinstance(repo_meta, dict):
            continue
        repo_key = str(repo_meta.get("key") or "unknown")
        repo_path = resolve_repo_path(tasks_root, args.task_id, repo_meta)
        if repo_path.resolve() == task_root.resolve() or not repo_path.resolve().is_relative_to(task_root.resolve()):
            failed = True
            print(f"[FAIL] {repo_key} -> {repo_path}: repo must be inside this task directory")
            continue
        expected_branch = str(repo_meta.get("branch") or "")
        issues = validate_repo_state_for_cleanup(
            repo_path, expected_branch or None, discard_local_changes=args.discard_local_changes,
        )
        if issues:
            failed = True
            print(f"[FAIL] {repo_key} -> {repo_path}")
            for issue in issues:
                print(f"  - {issue}")
        else:
            print(f"[OK] {repo_key} -> {repo_path}")

    if failed:
        print("cleanup blocked")
        if not args.discard_local_changes:
            print("If intentionally abandoning local work, use --discard-local-changes after explicit authorization.")
        return 2

    # Reuse the existing paused state so automatic dispatch cannot resume a task
    # whose local code is about to be removed. A failed preflight changes nothing.
    if meta["status"] != "已完成":
        changed = meta.get("coding_allowed") is not False or meta["status"] != "暂停中"
        if meta["status"] != "暂停中":
            meta["resume_status"] = meta["status"]
        meta["status"] = "暂停中"
        meta["coding_allowed"] = False
        stage = meta.get("current_stage")
        if isinstance(stage, dict):
            if stage.get("status") != "暂停中":
                stage["resume_status"] = stage.get("status") or meta.get("resume_status")
                stage["status"] = "暂停中"
                changed = True
        if changed:
            save_yaml(meta_path, meta, args.dry_run)
        index_name = workspace_cfg.get("documents", {}).get("index", "index.md")
        update_index_status(docs_root / args.task_id / index_name, "暂停中", args.dry_run)

    for repo_meta in repos:
        if not isinstance(repo_meta, dict):
            continue
        repo_key = str(repo_meta.get("key") or "unknown")
        repo_path = resolve_repo_path(tasks_root, args.task_id, repo_meta)
        repo_cfg = repo_cfg_by_key.get(repo_key, repo_meta)
        for message in cleanup_task_runtime(repo_cfg, repo_path, args.dry_run):
            print(f"[CLEANUP] {repo_key} -> {message}")

    safe_remove_path(task_root, args.dry_run)
    print(f"task documents preserved: {docs_root / args.task_id}")
    print("task code cleanup preview complete" if args.dry_run else "task code cleanup complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
