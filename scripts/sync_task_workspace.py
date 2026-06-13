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
    read_status_short,
    resolve_origin_default_branch,
    resolve_repo_path,
    resolve_requested_repo_keys,
)


DEFAULT_CONFIG_ROOT = Path("/Users/wuyongli/Documents/sg-project/_workspace/config")


def _run_git_command(repo_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo_path), *args],
        text=True,
        capture_output=True,
    )


def run_sync_job(job: dict[str, object]) -> dict[str, object]:
    repo_key = str(job["repo_key"])
    repo_path = Path(str(job["repo_path"]))
    expected_branch = str(job.get("expected_branch") or "")

    actual_branch = read_current_branch(repo_path)
    if actual_branch in {"missing", "not-a-git-repo", "detached"}:
        return {
            "repo_key": repo_key,
            "status": "failed",
            "reason": f"repo is not syncable: {actual_branch}",
            "stdout": "",
            "stderr": "",
        }
    if expected_branch and actual_branch != expected_branch:
        return {
            "repo_key": repo_key,
            "status": "failed",
            "reason": f"current branch is {actual_branch}, expected {expected_branch}",
            "stdout": "",
            "stderr": "",
        }

    status_output = read_status_short(repo_path)
    if status_output.strip():
        return {
            "repo_key": repo_key,
            "status": "failed",
            "reason": "working tree has uncommitted changes",
            "stdout": status_output,
            "stderr": "",
        }

    fetch_result = _run_git_command(repo_path, "fetch", "origin", "--prune")
    if fetch_result.returncode != 0:
        return {
            "repo_key": repo_key,
            "status": "failed",
            "reason": "git fetch failed",
            "stdout": fetch_result.stdout,
            "stderr": fetch_result.stderr,
        }

    try:
        default_branch = resolve_origin_default_branch(repo_path)
    except ValueError as exc:
        return {
            "repo_key": repo_key,
            "status": "failed",
            "reason": str(exc),
            "stdout": fetch_result.stdout,
            "stderr": fetch_result.stderr,
        }

    merge_ref = f"origin/{default_branch}"
    merge_result = _run_git_command(repo_path, "merge", "--no-edit", merge_ref)
    if merge_result.returncode != 0:
        return {
            "repo_key": repo_key,
            "status": "failed",
            "reason": f"git merge failed against {merge_ref}",
            "stdout": (fetch_result.stdout or "") + (merge_result.stdout or ""),
            "stderr": (fetch_result.stderr or "") + (merge_result.stderr or ""),
        }

    return {
        "repo_key": repo_key,
        "status": "ok",
        "reason": f"synced from {merge_ref}",
        "stdout": (fetch_result.stdout or "") + (merge_result.stdout or ""),
        "stderr": (fetch_result.stderr or "") + (merge_result.stderr or ""),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync task repos with remote default branch in parallel.")
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
        expected_branch = str(repo_meta.get("branch") or "")
        print(f"[PLAN] {repo_key}")
        print(f"  path: {repo_path}")
        print(f"  expected_branch: {expected_branch or '<none>'}")
        print("  action: fetch origin --prune && merge origin/<default-branch>")
        jobs.append(
            {
                "repo_key": repo_key,
                "repo_path": repo_path,
                "expected_branch": expected_branch,
            }
        )

    if not jobs:
        print("no sync jobs resolved")
        return 0

    print(f"[RUN] parallel sync jobs: {len(jobs)}")
    results: list[dict[str, object]] = []
    with ThreadPoolExecutor(max_workers=len(jobs)) as executor:
        future_map = {executor.submit(run_sync_job, job): job for job in jobs}
        for future in as_completed(future_map):
            result = future.result()
            repo_key = str(result["repo_key"])
            status = str(result["status"])
            reason = str(result["reason"])
            stdout = str(result["stdout"] or "")
            stderr = str(result["stderr"] or "")
            if status == "ok":
                print(f"[OK] {repo_key} -> {reason}")
            else:
                print(f"[FAILED] {repo_key} -> {reason}")
                if stdout.strip():
                    print("  stdout:")
                    print(stdout.rstrip())
                if stderr.strip():
                    print("  stderr:")
                    print(stderr.rstrip())
            results.append(result)

    failed = [item for item in results if str(item["status"]) != "ok"]
    print(f"[SUMMARY] success={len(results) - len(failed)} failed={len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
