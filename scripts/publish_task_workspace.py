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
    prepare_node_frontend_native_optional_runtime,
    read_current_branch,
    resolve_node_version_for_repo,
    resolve_publish_command,
    resolve_requested_repo_keys,
    resolve_repo_path,
    uses_patch_node_frontend_runtime,
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


def should_prepare_frontend_publish_runtime(repo_cfg: dict[str, object], command: list[str]) -> bool:
    return command[:3] == ["sg", "publish", "local"] and uses_patch_node_frontend_runtime(repo_cfg)


def read_package_manifest_diff(repo_path: Path) -> set[str]:
    diff_text = read_git_text(repo_path, "diff", "--name-only", "--", "package.json", "package-lock.json")
    return {line.strip() for line in diff_text.splitlines() if line.strip()}


def prepare_publish_runtime(job: dict[str, object]) -> dict[str, object]:
    repo_cfg = job.get("repo_cfg")
    command = list(job["command"])
    repo_path = Path(str(job["repo_path"]))
    if not isinstance(repo_cfg, dict) or not should_prepare_frontend_publish_runtime(repo_cfg, command):
        return {"skipped": True, "notes": [], "warnings": []}

    before_manifest_diff = read_package_manifest_diff(repo_path)
    summary = prepare_node_frontend_native_optional_runtime(repo_cfg, repo_path, False)
    after_manifest_diff = read_package_manifest_diff(repo_path)
    introduced_manifest_diff = sorted(after_manifest_diff - before_manifest_diff)
    notes = list(summary.get("notes") or [])
    warnings = list(summary.get("warnings") or [])
    if introduced_manifest_diff:
        warnings.append(
            "前端发布前的本地依赖修复导致 package.json/package-lock.json 出现新变更，"
            "这属于异常；已停止发布该仓库："
            + ", ".join(introduced_manifest_diff)
        )

    return {
        "skipped": False,
        "ok": not introduced_manifest_diff and not bool(summary.get("blocking")),
        "notes": notes,
        "warnings": warnings,
    }


def failed_publish_job_result(
    job: dict[str, object],
    repo_path: Path,
    execution_command: list[str],
    error_message: str,
    runtime_prepare: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "repo_key": job["repo_key"],
        "repo_path": str(repo_path),
        "returncode": 1,
        "stdout": "",
        "stderr": "",
        "status": "failed",
        "error_message": error_message,
        "log_status": "",
        "execution_command": execution_command,
        "repo_state": {},
        "restore_result": {},
        "runtime_prepare": runtime_prepare or {},
    }


def print_runtime_prepare_summary(runtime_prepare: object) -> None:
    if not isinstance(runtime_prepare, dict) or runtime_prepare.get("skipped"):
        return
    notes = [str(item) for item in runtime_prepare.get("notes") or []]
    warnings = [str(item) for item in runtime_prepare.get("warnings") or []]
    if notes:
        print(f"  native optional prepare: {'; '.join(notes)}")
    if warnings:
        print(f"  native optional prepare warnings: {'; '.join(warnings)}")


def read_git_text(repo_path: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_path), *args],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def merge_head_exists(repo_path: Path) -> bool:
    merge_head_path = read_git_text(repo_path, "rev-parse", "--git-path", "MERGE_HEAD")
    if not merge_head_path:
        return False
    path = Path(merge_head_path)
    if not path.is_absolute():
        path = repo_path / path
    return path.exists()


def parse_unmerged_files(status_short: str) -> list[str]:
    files: list[str] = []
    for line in status_short.splitlines():
        if len(line) < 4:
            continue
        code = line[:2]
        if "U" not in code and code not in {"AA", "DD"}:
            continue
        files.append(line[3:].strip())
    return files


def read_publish_repo_state(repo_path: Path) -> dict[str, object]:
    status_short = read_git_text(repo_path, "status", "--porcelain")
    branch = read_current_branch(repo_path)
    unmerged_files = parse_unmerged_files(status_short)
    return {
        "branch": branch,
        "status_short": status_short,
        "unmerged_files": unmerged_files,
        "merge_in_progress": merge_head_exists(repo_path),
    }


def repo_has_merge_conflict(repo_state: dict[str, object]) -> bool:
    unmerged_files = repo_state.get("unmerged_files")
    return bool(unmerged_files) or bool(repo_state.get("merge_in_progress"))


def restore_recorded_branch(repo_path: Path, recorded_branch: str) -> dict[str, object]:
    current_branch = read_current_branch(repo_path)
    status_short = read_git_text(repo_path, "status", "--porcelain")
    if status_short.strip():
        return {
            "ok": False,
            "branch": current_branch,
            "target_branch": recorded_branch,
            "reason": "working tree is not clean after publish",
            "status_short": status_short,
            "stdout": "",
            "stderr": "",
        }

    result = subprocess.run(
        ["git", "-C", str(repo_path), "checkout", recorded_branch],
        check=False,
        capture_output=True,
        text=True,
    )
    final_branch = read_current_branch(repo_path)
    ok = result.returncode == 0 and final_branch == recorded_branch
    return {
        "ok": ok,
        "branch": final_branch,
        "target_branch": recorded_branch,
        "reason": "" if ok else f"failed to restore branch {recorded_branch}",
        "status_short": read_git_text(repo_path, "status", "--porcelain"),
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def run_publish_job(job: dict[str, object]) -> dict[str, object]:
    command = list(job["command"])
    execution_command = build_publish_execution_command(command, str(job.get("node_version") or "") or None)
    repo_path = Path(str(job["repo_path"]))
    runtime_prepare: dict[str, object] = {}
    try:
        runtime_prepare = prepare_publish_runtime(job)
    except Exception as exc:
        return failed_publish_job_result(
            job,
            repo_path,
            execution_command,
            f"frontend native optional prepare failed before publish: {exc}",
            runtime_prepare,
        )
    if runtime_prepare and runtime_prepare.get("ok") is False:
        return failed_publish_job_result(
            job,
            repo_path,
            execution_command,
            "frontend native optional prepare failed before publish",
            runtime_prepare,
        )

    started_at_ms = int(time.time() * 1000)
    result = subprocess.run(execution_command, cwd=repo_path, text=True, capture_output=True)
    ended_at_ms = int(time.time() * 1000)
    log_entry = find_publish_cli_log_entry(repo_path, command, started_at_ms, ended_at_ms)
    status, error_message = classify_publish_result(command, result.returncode, result.stdout, result.stderr, log_entry)
    repo_state: dict[str, object] = {}
    if status != "success":
        repo_state = read_publish_repo_state(repo_path)
    if repo_state and repo_has_merge_conflict(repo_state):
        status = "conflict"
        branch = str(repo_state.get("branch") or "")
        error_message = (
            f"publish left a local merge conflict on branch {branch}; keep this branch, "
            "resolve the conflict here, then retry publish"
        )
    restore_result: dict[str, object] = {}
    if status == "success" and bool(job.get("restore_branch_after_success")):
        recorded_branch = str(job.get("recorded_branch") or "")
        restore_result = restore_recorded_branch(repo_path, recorded_branch)
        if not bool(restore_result.get("ok")):
            status = "restore_failed"
            error_message = str(restore_result.get("reason") or "failed to restore task branch after publish")
    return {
        "repo_key": job["repo_key"],
        "repo_path": str(repo_path),
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "status": status,
        "error_message": error_message,
        "log_status": str(log_entry.get("status") or "") if isinstance(log_entry, dict) else "",
        "execution_command": execution_command,
        "repo_state": repo_state,
        "restore_result": restore_result,
        "runtime_prepare": runtime_prepare,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish selected task repos with task-workflow defaults.")
    parser.add_argument("task_id", help="Task id such as 2026-06-03-部门转货")
    parser.add_argument("targets", nargs="*", help="Publish targets such as 后端 / 前端 / 手机前端 / PC前端")
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
        status_short = read_git_text(repo_path, "status", "--porcelain")
        publish_develop_retry = actual_branch == "develop"
        publish_conflict_retry = publish_develop_retry and (
            merge_head_exists(repo_path) or bool(parse_unmerged_files(status_short))
        )
        if recorded_branch and actual_branch != recorded_branch and not publish_develop_retry:
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
        if publish_conflict_retry:
            print("  mode: develop conflict retry")
        elif publish_develop_retry and recorded_branch and recorded_branch != actual_branch:
            print("  mode: develop publish retry")
        print(f"  command: {' '.join(command)}")
        if node_version:
            print(f"  node: {node_version}")
        if should_prepare_frontend_publish_runtime(repo_cfg, command):
            print("  native optional prepare: patch-node-frontend-environment")
        jobs.append(
            {
                "repo_key": repo_key,
                "repo_path": repo_path,
                "repo_cfg": repo_cfg,
                "command": command,
                "node_version": node_version,
                "recorded_branch": recorded_branch,
                "started_branch": actual_branch,
                "restore_branch_after_success": (
                    publish_develop_retry and bool(recorded_branch) and recorded_branch != actual_branch
                ),
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
            runtime_prepare = result.get("runtime_prepare")
            if status == "success":
                print(f"[OK] {repo_key}")
                print_runtime_prepare_summary(runtime_prepare)
                restore_result = result.get("restore_result")
                if isinstance(restore_result, dict) and restore_result.get("ok"):
                    print(f"  restored branch: {restore_result.get('target_branch')}")
            elif status == "conflict":
                print(f"[CONFLICT] {repo_key}")
                if error_message:
                    print(f"  reason: {error_message}")
                repo_state = result.get("repo_state")
                if isinstance(repo_state, dict):
                    branch = str(repo_state.get("branch") or "")
                    status_short = str(repo_state.get("status_short") or "")
                    unmerged_files = repo_state.get("unmerged_files")
                    if branch:
                        print(f"  branch: {branch}")
                    print("  next: keep this branch; do not merge --abort or checkout the task branch")
                    print("  next: resolve conflicts here, run minimal validation, then retry publish")
                    if isinstance(unmerged_files, list) and unmerged_files:
                        print("  unmerged files:")
                        for path in unmerged_files:
                            print(f"    - {path}")
                    if status_short.strip():
                        print("  git status --porcelain:")
                        print(status_short.rstrip())
                if stdout.strip():
                    print("  stdout:")
                    print(stdout.rstrip())
                if stderr.strip():
                    print("  stderr:")
                    print(stderr.rstrip())
            elif status == "restore_failed":
                print(f"[RESTORE_FAILED] {repo_key}")
                if error_message:
                    print(f"  reason: {error_message}")
                restore_result = result.get("restore_result")
                if isinstance(restore_result, dict):
                    branch = str(restore_result.get("branch") or "")
                    target_branch = str(restore_result.get("target_branch") or "")
                    status_short = str(restore_result.get("status_short") or "")
                    if branch:
                        print(f"  current branch: {branch}")
                    if target_branch:
                        print(f"  expected branch: {target_branch}")
                    if status_short.strip():
                        print("  git status --porcelain:")
                        print(status_short.rstrip())
                    restore_stdout = str(restore_result.get("stdout") or "")
                    restore_stderr = str(restore_result.get("stderr") or "")
                    if restore_stdout.strip():
                        print("  checkout stdout:")
                        print(restore_stdout.rstrip())
                    if restore_stderr.strip():
                        print("  checkout stderr:")
                        print(restore_stderr.rstrip())
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
                print_runtime_prepare_summary(runtime_prepare)
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
    conflicts = [item for item in results if str(item.get("status") or "") == "conflict"]
    restore_failed = [item for item in results if str(item.get("status") or "") == "restore_failed"]
    print(
        f"[SUMMARY] success={len(success)} failed={len(failed)} uncertain={len(uncertain)} "
        f"conflict={len(conflicts)} restore_failed={len(restore_failed)}"
    )
    return 1 if failed or uncertain or conflicts or restore_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
