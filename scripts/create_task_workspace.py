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


def render_index(task_name: str) -> str:
    lines = [
        f"# {task_name}",
        "",
        "> 使用原则：",
        "> - 本文件只保留当前快照，不记录多轮状态演进过程",
        '> - 更新时直接重写“任务摘要”，不要在下方追加新的状态说明或临时结论',
        "> - 如果摘要内容已被新进展替代，应删除旧表述，保持当前有效版本",
        "> - 如果任务已拆出模块子方案或附录，只导航当前仍有效的扩展文档",
        "",
        "## 任务摘要",
        "- 当前状态：方案中",
        f"- 一句话目标：{task_name}",
        "- 当前结论：待补充",
        "- 当前阻塞：无",
        "- 下一步：补充计划并等待明确开发指令",
        "",
        "## 文档导航",
        "- 事实文件：./meta.yaml",
        "- 计划文档：./plan.md",
        "- 进度文档：./progress.md",
        "",
        "## 扩展文档（如有）",
        "- 决策附录：",
        "- 模块子方案：",
        "- 附录：",
        "",
    ]
    return "\n".join(lines)


def render_plan(task_name: str, repo_keys: list[str]) -> str:
    repo_text = ", ".join(repo_keys)
    return f"""# {task_name} 任务计划

> 使用原则：
> - 当前处于任务初始阶段时，默认使用种子版结构，只写已经明确的内容
> - 方案真正展开后，再扩展为正式版结构；不要一开始铺满完整大模板
> - 本文件只保留当前有效方案，不保留多轮讨论过程
> - 当前有效的取舍结论和原因写在本文件；执行过程写到 `progress.md`
> - 候选方案和历史推导太长时，才额外拆 `decision-log.md`
> - 更新时优先重写当前章节并删除旧口径，不在原文后持续追加碎片

## 当前阶段收口
- 当前阶段：方案中
- 当前主路径：先完成需求分析和方案收口，不直接进入代码开发
- 当前明确纳入：
- 当前明确不纳入：

## 当前目标
- 背景：
- 目标：
- 当前阶段：方案中
- 当前结论：待补充

## 当前初步判断
- 需求是否成立：
- 当前推荐方向：
- 涉及仓库：{repo_text}
- 影响范围：
- 当前不确定点：

## 核心决策与原因
- 当前决策：
- 决策原因：
- 不采用的路径：
- 对范围/开发/上线的影响：

## 开发准入确认
- 说明：本节记录判断依据，最终机器状态以 `meta.yaml` 为准
- 方案是否已确认：未确认
- 开发方案是否已补齐：未补齐
- 是否允许开始代码工作：未允许
- 用户明确指令：
- 开工前仍需满足的条件：
- 未获允许前 AI 可执行范围：分析需求、读取代码、评估现状、补方案、更新文档
- 未获允许前 AI 禁止事项：修改代码、修改配置、执行迁移、安装依赖、启动正式实现

## 待确认事项
- 事项 1：
- 事项 2：
- 是否影响需求成立性、方案取舍或主改仓判断：

## 参考信息
- 需求来源：
- 当前相关仓库：{repo_text}
- 相关说明：如果任务进入深入方案阶段，再把本文件扩展为正式版结构；只有当取舍过程明显过长时，再额外拆出 `decision-log.md`
"""


def render_decision_log(task_name: str) -> str:
    return f"""# {task_name} 决策记录

> 使用原则：
> - 本文件记录关键讨论、候选方案、取舍原因和口径变化
> - 不写聊天流水；只沉淀会影响方案、范围、开发或上线判断的讨论结果
> - 默认不主动创建；只有当候选方案和历史推导已经影响 `plan.md` 阅读时，再拆成独立附录
> - 已形成当前结论的内容，应同步回写到 `plan.md`

## 当前使用方式
- 当前阶段：方案中
- 主任务计划：./plan.md
- 使用场景：当任务还在讨论中，且“为什么这么定”不能丢失时，记录到这里

## 关键决策记录
- {dt.date.today().isoformat()}
  - 讨论点：创建任务工作区，待补充本任务的关键分歧与判断
  - 候选方案：
  - 当前结论：
  - 决策原因：
  - 对范围/开发/上线的影响：
"""


def render_progress(task_name: str) -> str:
    return f"""# {task_name} 任务进度

> 使用原则：
> - “当前进展”“实际改动”“自测记录”“问题与阻塞”保持当前版本
> - 只有“变更记录”按时间追加
> - 当前有效方案、核心决策原因和上线口径写到 `plan.md`
> - 更新时优先归并和去重，不要把新的结论直接叠加在旧结论后面

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

        write_text(task_docs_root / index_name, render_index(raw_task_name), args.dry_run)
        write_text(task_docs_root / plan_name, render_plan(raw_task_name, args.repos), args.dry_run)
        write_text(task_docs_root / progress_name, render_progress(raw_task_name), args.dry_run)

        meta = {
            "task_id": task_id,
            "status": "方案中",
            "resume_status": "方案中",
            "coding_allowed": False,
            "phase": 1,
            "current_task_name": raw_task_name,
            "active_plan": plan_name,
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
