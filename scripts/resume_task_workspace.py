#!/usr/bin/env python3

from __future__ import annotations

import argparse
from pathlib import Path

from task_workflow_lib import (
    load_task_meta,
    load_yaml,
    require_task_status,
    resolve_repo_path,
    save_yaml,
    update_index_status,
)


DEFAULT_CONFIG_ROOT = Path("/Users/wuyongli/Documents/sg-project/_workspace/config")


def main() -> int:
    parser = argparse.ArgumentParser(description="Resume one paused task without moving task-scoped repos.")
    parser.add_argument("task_id", help="Full task id, e.g. YYYY-MM-DD-原始任务名")
    parser.add_argument("--config-root", type=Path, default=DEFAULT_CONFIG_ROOT)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    workspace_cfg = load_yaml(args.config_root / "workspace.yaml")
    docs_root = Path(workspace_cfg["docs_root"])
    tasks_root = Path(workspace_cfg["tasks_root"])
    documents = workspace_cfg.get("documents", {})

    meta_path, meta = load_task_meta(docs_root, args.task_id)
    require_task_status(meta, ("暂停中",), "resume")
    repos = meta.get("repos", [])
    if not isinstance(repos, list):
        raise ValueError(f"invalid repos in task meta: {meta_path}")
    missing_repos: list[str] = []
    for repo_meta in repos:
        if not isinstance(repo_meta, dict):
            continue
        repo_key = str(repo_meta.get("key") or "unknown")
        repo_path = resolve_repo_path(tasks_root, args.task_id, repo_meta)
        if not repo_path.exists():
            missing_repos.append(f"{repo_key}: {repo_path}")
    if missing_repos:
        raise ValueError("resume blocked because task repo paths are missing:\n- " + "\n- ".join(missing_repos))

    meta["status"] = str(meta.get("resume_status") or "开发中")
    save_yaml(meta_path, meta, args.dry_run)

    index_path = docs_root / args.task_id / documents.get("index", "index.md")
    update_index_status(index_path, str(meta["status"]), args.dry_run)
    print("task resume complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
