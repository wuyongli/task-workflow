#!/usr/bin/env python3

from __future__ import annotations

import argparse
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from task_workflow_lib import (
    load_task_meta,
    load_yaml,
    read_current_branch,
    resolve_publish_command,
    resolve_requested_repo_keys,
    resolve_repo_path,
)


DEFAULT_CONFIG_ROOT = Path("/Users/wuyongli/Documents/sg-project/_workspace/config")


def run_publish_job(job: dict[str, object]) -> dict[str, object]:
    command = list(job["command"])
    repo_path = Path(str(job["repo_path"]))
    result = subprocess.run(command, cwd=repo_path, text=True, capture_output=True)
    return {
        "repo_key": job["repo_key"],
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish selected task repos with task-workflow defaults.")
    parser.add_argument("task_id", help="Task id such as 2026-06-03-部门转货")
    parser.add_argument("targets", nargs="+", help="Publish targets such as 后端 / 前端 / 手机前端 / PC前端")
    parser.add_argument("--config-root", type=Path, default=DEFAULT_CONFIG_ROOT)
    args = parser.parse_args()

    workspace_cfg = load_yaml(args.config_root / "workspace.yaml")
    repositories_cfg = load_yaml(args.config_root / "repositories.yaml")
    docs_root = Path(workspace_cfg["docs_root"])
    tasks_root = Path(workspace_cfg["tasks_root"])

    _meta_path, task_meta = load_task_meta(docs_root, args.task_id)
    repo_rows = task_meta.get("repos", [])
    if not isinstance(repo_rows, list):
        raise ValueError("task meta repos is invalid")

    repo_meta_by_key: dict[str, dict[str, object]] = {}
    for row in repo_rows:
        if not isinstance(row, dict):
            continue
        repo_key = str(row.get("key") or "")
        if repo_key:
            repo_meta_by_key[repo_key] = row

    repo_cfg_by_key = {
        str(row.get("key") or ""): row
        for row in repositories_cfg.get("repositories", [])
        if isinstance(row, dict) and row.get("key")
    }
    bound_repo_keys = list(repo_meta_by_key.keys())
    requested_repo_keys = resolve_requested_repo_keys(args.targets, bound_repo_keys, repo_cfg_by_key)
    jobs: list[dict[str, object]] = []

    for repo_key in requested_repo_keys:
        repo_meta = repo_meta_by_key.get(repo_key)
        if repo_meta is None:
            raise ValueError(f"repo {repo_key} is not bound to task {args.task_id}")

        repo_cfg = repo_cfg_by_key.get(repo_key)
        if repo_cfg is None:
            raise ValueError(f"repo {repo_key} is not configured in repositories.yaml")

        repo_path = resolve_repo_path(tasks_root, args.task_id, repo_meta)
        recorded_branch = str(repo_meta.get("branch") or "")
        actual_branch = read_current_branch(repo_path)
        if actual_branch in {"missing", "not-a-git-repo", "detached"}:
            raise ValueError(f"repo {repo_key} is not publishable: {actual_branch}")
        if recorded_branch and actual_branch != recorded_branch:
            raise ValueError(
                f"repo {repo_key} current branch is {actual_branch}, expected recorded branch {recorded_branch}"
            )

        command = resolve_publish_command(repo_cfg)
        print(f"[PLAN] {repo_key}")
        print(f"  path: {repo_path}")
        print(f"  branch: {actual_branch}")
        print(f"  command: {' '.join(command)}")
        jobs.append(
            {
                "repo_key": repo_key,
                "repo_path": repo_path,
                "command": command,
            }
        )

    if not jobs:
        print("no publish jobs resolved")
        return 0

    print(f"[RUN] parallel publish jobs: {len(jobs)}")
    results: list[dict[str, object]] = []
    with ThreadPoolExecutor(max_workers=len(jobs)) as executor:
        future_map = {executor.submit(run_publish_job, job): job for job in jobs}
        for future in as_completed(future_map):
            job = future_map[future]
            result = future.result()
            repo_key = str(result["repo_key"])
            returncode = int(result["returncode"])
            stdout = str(result["stdout"] or "")
            stderr = str(result["stderr"] or "")
            if returncode == 0:
                print(f"[OK] {repo_key}")
            else:
                print(f"[FAILED] {repo_key} (exit={returncode})")
                if stdout.strip():
                    print("  stdout:")
                    print(stdout.rstrip())
                if stderr.strip():
                    print("  stderr:")
                    print(stderr.rstrip())
            results.append(result)

    failed = [item for item in results if int(item["returncode"]) != 0]
    print(f"[SUMMARY] success={len(results) - len(failed)} failed={len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
