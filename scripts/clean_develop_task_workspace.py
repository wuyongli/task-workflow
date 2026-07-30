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
    resolve_repo_path,
    resolve_requested_repo_keys,
)


DEFAULT_CONFIG_ROOT = Path("/Users/wuyongli/Documents/sg-project/_workspace/config")
LOCAL_DEVELOP_BRANCH = "develop"


def _run_git_command(repo_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo_path), *args],
        text=True,
        capture_output=True,
    )


def _local_develop_exists(repo_path: Path) -> bool:
    result = _run_git_command(
        repo_path,
        "branch",
        "--list",
        "--format=%(refname:short)",
        LOCAL_DEVELOP_BRANCH,
    )
    return result.returncode == 0 and LOCAL_DEVELOP_BRANCH in {line.strip() for line in result.stdout.splitlines()}


def run_clean_develop_job(job: dict[str, object]) -> dict[str, object]:
    repo_key = str(job["repo_key"])
    repo_path = Path(str(job["repo_path"]))

    actual_branch = read_current_branch(repo_path)
    if actual_branch in {"missing", "not-a-git-repo"}:
        return {
            "repo_key": repo_key,
            "status": "failed",
            "reason": f"repo is not cleanable: {actual_branch}",
            "stdout": "",
            "stderr": "",
        }
    if actual_branch == LOCAL_DEVELOP_BRANCH:
        return {
            "repo_key": repo_key,
            "status": "failed",
            "reason": "current branch is local develop; switch away before deleting it",
            "stdout": "",
            "stderr": "",
        }

    if not _local_develop_exists(repo_path):
        return {
            "repo_key": repo_key,
            "status": "skipped",
            "reason": "local develop branch does not exist",
            "stdout": "",
            "stderr": "",
        }

    delete_result = _run_git_command(repo_path, "branch", "-D", LOCAL_DEVELOP_BRANCH)
    if delete_result.returncode != 0:
        return {
            "repo_key": repo_key,
            "status": "failed",
            "reason": "failed to delete local develop branch",
            "stdout": delete_result.stdout,
            "stderr": delete_result.stderr,
        }

    return {
        "repo_key": repo_key,
        "status": "ok",
        "reason": "deleted local develop branch",
        "stdout": delete_result.stdout,
        "stderr": delete_result.stderr,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Delete local develop branch for selected task repos.")
    parser.add_argument("task_id", help="Task id such as 2026-06-03-部门转货")
    parser.add_argument("targets", nargs="*", help="Optional targets such as 后端 / 前端 / 手机前端 / PC前端")
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
    selected_repo_keys = resolve_requested_repo_keys(args.targets, bound_repo_keys, repo_cfg_by_key)

    jobs: list[dict[str, object]] = []
    for repo_key in selected_repo_keys:
        repo_meta = repo_meta_by_key.get(repo_key)
        if repo_meta is None:
            raise ValueError(f"repo {repo_key} is not bound to task {args.task_id}")

        repo_path = resolve_repo_path(tasks_root, args.task_id, repo_meta)
        print(f"[PLAN] {repo_key}")
        print(f"  path: {repo_path}")
        print("  action: delete local develop branch if it exists")
        jobs.append({"repo_key": repo_key, "repo_path": repo_path})

    if not jobs:
        print("no clean-develop jobs resolved")
        return 0

    print(f"[RUN] parallel clean-develop jobs: {len(jobs)}")
    results: list[dict[str, object]] = []
    with ThreadPoolExecutor(max_workers=len(jobs)) as executor:
        future_map = {executor.submit(run_clean_develop_job, job): job for job in jobs}
        for future in as_completed(future_map):
            result = future.result()
            repo_key = str(result["repo_key"])
            status = str(result["status"])
            reason = str(result["reason"])
            stdout = str(result["stdout"] or "")
            stderr = str(result["stderr"] or "")
            if status == "ok":
                print(f"[OK] {repo_key} -> {reason}")
            elif status == "skipped":
                print(f"[SKIPPED] {repo_key} -> {reason}")
            else:
                print(f"[FAILED] {repo_key} -> {reason}")
                if stdout.strip():
                    print("  stdout:")
                    print(stdout.rstrip())
                if stderr.strip():
                    print("  stderr:")
                    print(stderr.rstrip())
            results.append(result)

    failed = [item for item in results if str(item["status"]) == "failed"]
    skipped = [item for item in results if str(item["status"]) == "skipped"]
    success = len(results) - len(failed) - len(skipped)
    print(f"[SUMMARY] success={success} skipped={len(skipped)} failed={len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
