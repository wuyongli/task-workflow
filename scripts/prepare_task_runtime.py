#!/usr/bin/env python3

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from task_workflow_lib import load_task_meta, load_yaml, prepare_repo_runtime, resolve_repo_path, start_repo_runtime


DEFAULT_CONFIG_ROOT = Path("/Users/wuyongli/Documents/sg-project/_workspace/config")


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare runtime config for an existing task workspace.")
    parser.add_argument("task_id", help="Task id such as 2026-05-12-demo-task")
    parser.add_argument("--repo", action="append", dest="repos", help="Only prepare the selected repo key. Repeatable.")
    parser.add_argument("--config-root", type=Path, default=DEFAULT_CONFIG_ROOT)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    repositories_cfg = load_yaml(args.config_root / "repositories.yaml")
    workspace_cfg = load_yaml(args.config_root / "workspace.yaml")
    docs_root = Path(workspace_cfg["docs_root"])
    tasks_root = Path(workspace_cfg["tasks_root"])

    _meta_path, task_meta = load_task_meta(docs_root, args.task_id)
    repo_map = {repo["key"]: repo for repo in repositories_cfg.get("repositories", [])}

    selected = set(args.repos or [])
    if selected:
        missing = sorted(selected.difference(repo_map))
        if missing:
            raise ValueError(f"unknown repo keys: {', '.join(missing)}")

    for repo_meta in task_meta.get("repos", []):
        repo_key = str(repo_meta["key"])
        if selected and repo_key not in selected:
            continue

        repo_cfg = repo_map.get(repo_key)
        if repo_cfg is None:
            raise ValueError(f"repo {repo_key} is not configured in repositories.yaml")

        repo_path = resolve_repo_path(tasks_root, args.task_id, repo_meta)
        runtime_summary = prepare_repo_runtime(repo_cfg, repo_path, args.dry_run)
        started_steps: list[str] = []
        started_warnings: list[str] = []
        auto_start_error: str | None = None
        try:
            start_summary = start_repo_runtime(repo_cfg, repo_path, args.dry_run)
            started_steps = start_summary["executed"]
            started_warnings = start_summary["warnings"]
        except subprocess.CalledProcessError as exc:
            auto_start_error = str(exc)

        print(f"[{repo_key}] {repo_path}")
        if runtime_summary["copied_from_main"]:
            print(f"  copied from main: {', '.join(runtime_summary['copied_from_main'])}")
        if runtime_summary["copied_from_template"]:
            print(f"  copied from template: {', '.join(runtime_summary['copied_from_template'])}")
        if runtime_summary["generated_files"]:
            print(f"  generated: {', '.join(runtime_summary['generated_files'])}")
        if runtime_summary["install_commands"]:
            print(f"  install: {' ; '.join(runtime_summary['install_commands'])}")
        if runtime_summary["start_commands"]:
            print(f"  start: {' ; '.join(runtime_summary['start_commands'])}")
        if started_steps:
            print(f"  auto-started: {' ; '.join(started_steps)}")
        for warning in started_warnings:
            print(f"  auto-start-warning: {warning}")
        if auto_start_error:
            print(f"  auto-start-failed: {auto_start_error}")
        for note in runtime_summary["notes"]:
            print(f"  note: {note}")
        for warning in runtime_summary["warnings"]:
            print(f"  warning: {warning}")

    print("runtime prepare complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
