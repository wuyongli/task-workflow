#!/usr/bin/env python3

from __future__ import annotations

import argparse
import datetime as dt
import json
import shlex
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from task_workflow_lib import (
    classify_repo_publish_kind,
    load_task_meta,
    load_yaml,
    read_current_branch,
    resolve_node_version_for_repo,
    resolve_publish_command,
    resolve_requested_repo_keys,
    resolve_repo_path,
)


DEFAULT_CONFIG_ROOT = Path("/Users/wuyongli/Documents/sg-project/_workspace/config")


def resolve_publish_log_path(cli_home: Path | None = None, now: dt.datetime | None = None) -> Path:
    resolved_cli_home = cli_home or (Path.home() / ".senguo-cli")
    resolved_now = now or dt.datetime.now()
    return resolved_cli_home / "logs" / f"commands-{resolved_now.strftime('%Y%m%d')}.json"


def find_publish_cli_log_entry(
    repo_path: Path,
    command: list[str],
    started_at_ms: int,
    ended_at_ms: int,
    cli_home: Path | None = None,
) -> dict[str, object] | None:
    if len(command) < 3 or command[0] != "sg" or command[1] != "publish":
        return None

    log_path = resolve_publish_log_path(cli_home)
    if not log_path.exists():
        return None

    try:
        entries = json.loads(log_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(entries, list):
        return None

    expected_subcommand = command[2]
    matched: list[dict[str, object]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if entry.get("command") != "publish":
            continue
        if entry.get("subCommand") != expected_subcommand:
            continue
        if Path(str(entry.get("workingDir") or "")) != repo_path:
            continue
        timestamp = entry.get("timestamp")
        if not isinstance(timestamp, int):
            continue
        if timestamp < started_at_ms - 1000 or timestamp > ended_at_ms + 1000:
            continue
        matched.append(entry)

    if not matched:
        return None
    matched.sort(key=lambda item: int(item.get("timestamp") or 0))
    return matched[-1]


def classify_publish_result(
    command: list[str],
    returncode: int,
    stdout: str,
    stderr: str,
    log_entry: dict[str, object] | None,
) -> tuple[str, str | None]:
    combined = "\n".join(part for part in [stdout.strip(), stderr.strip()] if part.strip())
    combined_lower = combined.lower()
    log_status = str(log_entry.get("status") or "") if isinstance(log_entry, dict) else ""
    log_error = log_entry.get("error") if isinstance(log_entry, dict) else None

    if log_status == "failed":
        if isinstance(log_error, dict):
            message = str(log_error.get("message") or "").strip()
            if message:
                return "failed", message
        return "failed", "publish CLI log marked this run as failed"

    if returncode != 0:
        return "failed", f"publish command exited with {returncode}"

    if "conflicts:" in combined_lower or "you are still merging" in combined_lower:
        return "failed", "publish output reported merge conflicts"

    is_local_publish = len(command) >= 3 and command[:3] == ["sg", "publish", "local"]
    explicit_success_output = "发布成功" in combined
    if is_local_publish:
        if explicit_success_output:
            return "success", None
        if log_status == "success":
            return "uncertain", "CLI log marked success, but terminal output had no explicit '发布成功' signal"
        return "uncertain", "no explicit success signal from sg publish local"

    return "success", None


def build_publish_execution_command(command: list[str], node_version: str | None = None) -> list[str]:
    if command[:3] != ["sg", "publish", "local"] or not node_version:
        return command

    shell_command = " && ".join(
        [
            'eval "$(fnm env --shell zsh)"',
            f"fnm use --install-if-missing {shlex.quote(node_version)} >/dev/null",
            shlex.join(command),
        ]
    )
    return ["zsh", "-lc", shell_command]


def run_publish_job(job: dict[str, object]) -> dict[str, object]:
    command = list(job["command"])
    execution_command = build_publish_execution_command(command, str(job.get("node_version") or "") or None)
    repo_path = Path(str(job["repo_path"]))
    started_at_ms = int(time.time() * 1000)
    result = subprocess.run(execution_command, cwd=repo_path, text=True, capture_output=True)
    ended_at_ms = int(time.time() * 1000)
    log_entry = find_publish_cli_log_entry(repo_path, command, started_at_ms, ended_at_ms)
    status, error_message = classify_publish_result(command, result.returncode, result.stdout, result.stderr, log_entry)
    return {
        "repo_key": job["repo_key"],
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "status": status,
        "error_message": error_message,
        "log_status": str(log_entry.get("status") or "") if isinstance(log_entry, dict) else "",
        "execution_command": execution_command,
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
        target_kind = classify_repo_publish_kind(repo_cfg)
        node_version = (
            resolve_node_version_for_repo(repo_path)
            if target_kind in {"mobile_frontend", "pc_frontend"}
            else None
        )
        print(f"[PLAN] {repo_key}")
        print(f"  path: {repo_path}")
        print(f"  branch: {actual_branch}")
        print(f"  command: {' '.join(command)}")
        if node_version:
            print(f"  node: {node_version}")
        jobs.append(
            {
                "repo_key": repo_key,
                "repo_path": repo_path,
                "command": command,
                "node_version": node_version,
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
            status = str(result.get("status") or "")
            error_message = str(result.get("error_message") or "")
            if status == "success":
                print(f"[OK] {repo_key}")
            elif status == "uncertain":
                print(f"[UNCERTAIN] {repo_key}")
                if error_message:
                    print(f"  reason: {error_message}")
                if stdout.strip():
                    print("  stdout:")
                    print(stdout.rstrip())
                if stderr.strip():
                    print("  stderr:")
                    print(stderr.rstrip())
            else:
                print(f"[FAILED] {repo_key} (exit={returncode})")
                if error_message:
                    print(f"  reason: {error_message}")
                if stdout.strip():
                    print("  stdout:")
                    print(stdout.rstrip())
                if stderr.strip():
                    print("  stderr:")
                    print(stderr.rstrip())
            results.append(result)

    success = [item for item in results if str(item.get("status") or "") == "success"]
    failed = [item for item in results if str(item.get("status") or "") == "failed"]
    uncertain = [item for item in results if str(item.get("status") or "") == "uncertain"]
    print(f"[SUMMARY] success={len(success)} failed={len(failed)} uncertain={len(uncertain)}")
    return 1 if failed or uncertain else 0


if __name__ == "__main__":
    raise SystemExit(main())
