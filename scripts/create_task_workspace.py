#!/usr/bin/env python3

from __future__ import annotations

import argparse
import datetime as dt
import subprocess
from pathlib import Path

from task_workflow_lib import (
    build_repo_dir_name,
    ensure_repo_clone,
    load_yaml,
    prepare_repo_runtime,
    prepare_repo_from_default,
    safe_remove_path,
    sanitize_branch_name,
    sanitize_task_segment,
    save_yaml,
    start_repo_runtime,
    write_text,
)


DEFAULT_CONFIG_ROOT = Path("/Users/wuyongli/Documents/sg-project/_workspace/config")


def render_index(task_name: str, repo_rows: list[tuple[str, str, str]]) -> str:
    lines = [
        f"# {task_name}",
        "",
        "## 任务摘要",
        "- 当前状态：方案中",
        f"- 一句话目标：{task_name}",
        "- 当前结论：待补充",
        "- 当前阻塞：无",
        "- 下一步：补充计划并开始执行",
        "",
        "## 仓库上下文",
    ]
    for repo_key, rel_path, branch_name in repo_rows:
        lines.extend(
            [
                f"- {repo_key}",
                f"  - 路径：{rel_path}",
                f"  - 分支：{branch_name}",
            ]
        )
    lines.extend(
        [
            "",
            "## 文档导航",
            "- 计划文档：./plan.md",
            "- 进度文档：./progress.md",
            "",
        ]
    )
    return "\n".join(lines)


def render_plan(task_name: str, repo_keys: list[str]) -> str:
    repo_text = ", ".join(repo_keys)
    return f"""# {task_name} 任务计划

## 任务目标
- 背景：
- 目标：
- 验收标准：

## 范围
- 本次包含：
- 本次不包含：

## 方案结论
- 核心思路：
- 关键改动点：
- 涉及仓库：{repo_text}
- 影响范围：

## 执行计划
- 步骤 1：
- 步骤 2：
- 步骤 3：

## 风险与注意事项
- 风险点：
- 注意事项：

## 参考信息
- 需求来源：
- 接口文档：
- 相关说明：
"""


def render_progress(task_name: str) -> str:
    return f"""# {task_name} 任务进度

## 当前进展
- 已完成：
- 进行中：
- 下一步：

## 实际改动
- 仓库：
  - 改动内容：
  - 备注：

## 自测记录
- 已验证：
- 验证结果：
- 未验证项：

## 问题与阻塞
- 当前问题：
- 处理情况：

## 变更记录
- {dt.date.today().isoformat()}
  - 做了什么：创建任务工作区
  - 结果：待补充
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a multi-repo task workspace with real task-scoped clones.")
    parser.add_argument("task_name", help="Raw task name, without date prefix.")
    parser.add_argument("--repo", action="append", dest="repos", required=True, help="Repo key to include. Repeatable.")
    parser.add_argument("--config-root", type=Path, default=DEFAULT_CONFIG_ROOT)
    parser.add_argument("--date", default=dt.date.today().isoformat(), help="Task date prefix in YYYY-MM-DD.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    repositories_cfg = load_yaml(args.config_root / "repositories.yaml")
    workspace_cfg = load_yaml(args.config_root / "workspace.yaml")

    tasks_root = Path(workspace_cfg["tasks_root"])
    docs_root = Path(workspace_cfg["docs_root"])
    documents = workspace_cfg.get("documents", {})

    raw_task_name = sanitize_task_segment(args.task_name)
    task_id = f"{args.date}-{raw_task_name}"
    branch_name = sanitize_branch_name(raw_task_name)
    task_code_root = tasks_root / task_id
    task_docs_root = docs_root / task_id

    repo_map = {repo["key"]: repo for repo in repositories_cfg.get("repositories", [])}
    missing = [repo_key for repo_key in args.repos if repo_key not in repo_map]
    if missing:
        raise ValueError(f"unknown repo keys: {', '.join(missing)}")

    if task_code_root.exists() or task_docs_root.exists():
        raise FileExistsError(f"task code or docs already exist: {task_id}")

    print(f"task code dir: {task_code_root}")
    print(f"docs dir: {task_docs_root}")
    print(f"default branch: {branch_name}")
    print(f"repos: {', '.join(args.repos)}")

    created_paths: list[Path] = []
    try:
        if not args.dry_run:
            task_code_root.mkdir(parents=True, exist_ok=False)
            task_docs_root.mkdir(parents=True, exist_ok=False)
            created_paths.extend([task_code_root, task_docs_root])

        repo_rows: list[tuple[str, str, str]] = []
        repo_meta_rows: list[dict[str, str]] = []
        for repo_key in args.repos:
            repo_cfg = repo_map[repo_key]
            remote = str(repo_cfg["remote"])
            repo_dir_name = build_repo_dir_name(repo_key, raw_task_name)
            repo_path = task_code_root / repo_dir_name

            ensure_repo_clone(repo_path, remote, args.dry_run)
            prepare_repo_from_default(repo_path, remote, branch_name, args.dry_run)
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

            rel_task_path = Path("..") / ".." / "_tasks" / task_id / repo_dir_name
            repo_rows.append((repo_key, str(rel_task_path), branch_name))
            repo_meta_rows.append(
                {
                    "key": repo_key,
                    "repo_dir": repo_dir_name,
                    "branch": branch_name,
                }
            )

            print(f"[{repo_key}] runtime prepare complete")
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

        index_name = documents.get("index", "index.md")
        plan_name = documents.get("plan", "plan.md")
        progress_name = documents.get("progress", "progress.md")

        write_text(task_docs_root / index_name, render_index(raw_task_name, repo_rows), args.dry_run)
        write_text(task_docs_root / plan_name, render_plan(raw_task_name, args.repos), args.dry_run)
        write_text(task_docs_root / progress_name, render_progress(raw_task_name), args.dry_run)

        meta = {
            "task_id": task_id,
            "status": "方案中",
            "repos": repo_meta_rows,
        }
        save_yaml(task_docs_root / "meta.yaml", meta, args.dry_run)

        print("task workspace create complete")
        return 0
    except Exception:
        for path in reversed(created_paths):
            safe_remove_path(path, args.dry_run)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
