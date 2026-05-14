#!/usr/bin/env python3

from __future__ import annotations

import argparse
from pathlib import Path

from task_workflow_lib import load_task_meta, load_yaml, read_current_branch, resolve_repo_path


DEFAULT_CONFIG_ROOT = Path("/Users/wuyongli/Documents/sg-project/_workspace/config")


def repo_state(repo_path: Path) -> str:
    if repo_path.exists():
        return "present"
    return "missing"


def main() -> int:
    parser = argparse.ArgumentParser(description="Show task and repo status for task-workflow.")
    parser.add_argument("--config-root", type=Path, default=DEFAULT_CONFIG_ROOT)
    args = parser.parse_args()

    workspace_cfg = load_yaml(args.config_root / "workspace.yaml")
    docs_root = Path(workspace_cfg["docs_root"])
    tasks_root = Path(workspace_cfg["tasks_root"])

    task_dirs = sorted([path for path in docs_root.iterdir() if path.is_dir() and not path.name.startswith(".")])
    print("## Tasks")
    if not task_dirs:
        print("- no tasks")
        return 0

    for task_dir in task_dirs:
        meta_path = task_dir / "meta.yaml"
        if not meta_path.exists():
            print(f"- {task_dir.name} [legacy-docs-without-meta]")
            continue
        _meta_path, meta = load_task_meta(docs_root, task_dir.name)
        status = str(meta.get("status") or "未知")
        print(f"- {task_dir.name} [{status}]")
        repos = meta.get("repos", [])
        if not isinstance(repos, list):
            continue
        for repo_meta in repos:
            if not isinstance(repo_meta, dict):
                continue
            repo_key = str(repo_meta.get("key") or "unknown")
            repo_path = resolve_repo_path(tasks_root, task_dir.name, repo_meta)
            recorded_branch = str(repo_meta.get("branch") or "unknown")
            actual_branch = read_current_branch(repo_path)
            print(
                f"  - {repo_key}: state={repo_state(repo_path)}, recorded_branch={recorded_branch}, actual_branch={actual_branch}, path={repo_path}"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
