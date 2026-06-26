#!/usr/bin/env python3

from __future__ import annotations

import argparse
import datetime as dt
import re
from pathlib import Path
from typing import Any

from task_workflow_lib import (
    load_task_meta,
    load_yaml,
    require_task_status,
    resolve_requested_repo_keys_or_aliases,
    resolve_repo_path,
    run,
    sanitize_branch_name,
    sanitize_task_segment,
    save_yaml,
    validate_repo_state,
    write_text,
)


DEFAULT_CONFIG_ROOT = Path("/Users/wuyongli/Documents/sg-project/_workspace/config")
NEXT_BASE_BRANCH = "master"


def _task_theme_name(task_id: str) -> str:
    match = re.match(r"^\d{4}-\d{2}-\d{2}-(.+)$", task_id.strip())
    if not match:
        raise ValueError(f"invalid task id: {task_id}")
    return match.group(1)


def _coerce_phase(value: Any) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return 1


def _phase_document_name(base_name: str, task_name: str) -> str:
    path = Path(base_name)
    suffix = path.suffix or ".md"
    return f"{path.stem}-{task_name}{suffix}"


def render_next_phase_plan(task_name: str, repo_keys: list[str], previous_task_name: str, previous_plan: str) -> str:
    repo_text = ", ".join(repo_keys)
    return f"""# {task_name}

> 使用原则：
> - 下一阶段默认从种子版计划开始，只写已确认的阶段目标、初步方案和待确认项
> - 本文件只保留当前阶段有效方案；执行过程写到 `progress.md`
> - 当前有效的取舍结论和原因写在本文件，历史推导过长时再拆 `decision-log`
> - 当前阶段真正展开后，再扩展为正式版结构

## 阶段说明
- 当前阶段任务：{task_name}
- 前置阶段任务：{previous_task_name}
- 历史阶段方案：./{previous_plan}
- 当前阶段状态：方案中

## 当前目标
- 背景：基于上一阶段已完成能力，继续推进本阶段任务
- 目标：待补充
- 当前结论：待补充

## 当前初步判断
- 当前推荐方向：待补充
- 涉及仓库：{repo_text}
- 影响范围：待补充
- 当前不确定点：待补充

## 核心决策与原因
- 当前决策：待补充
- 决策原因：待补充
- 不采用的路径：待补充
- 对范围/开发/上线的影响：待补充

## 开发准入确认
- 方案是否已确认：未确认
- 开发方案是否已补齐：未补齐
- 是否允许开始代码工作：未允许
- 用户明确指令：待补充
- 开工前仍需满足的条件：待补充

## 待确认事项
- 事项 1：
- 事项 2：
"""


def render_next_index(
    workspace_title: str,
    next_task_name: str,
    previous_task_name: str,
    next_status: str,
    next_plan_name: str,
    previous_plan_name: str,
    phase: int,
) -> str:
    return "\n".join(
        [
            f"# {workspace_title}",
            "",
            "## 任务摘要",
            f"- 当前状态：{next_status}",
            f"- 一句话目标：{next_task_name}",
            "- 当前结论：已开启下一阶段，待补充本阶段正式方案。",
            "- 当前阻塞：无",
            "- 下一步：补充当前阶段 plan，并等待明确开发指令。",
            "",
            "## 阶段关系",
            f"- 当前阶段：第 {phase} 阶段",
            f"- 当前阶段任务：{next_task_name}",
            f"- 前置阶段任务：{previous_task_name}",
            "- 关系说明：当前阶段基于前置阶段已上线/已完成能力继续推进。",
            "",
            "## 文档导航",
            "- 事实文件：./meta.yaml",
            f"- 当前阶段计划：./{next_plan_name}",
            f"- 历史阶段计划：./{previous_plan_name}",
            "- 进度文档：./progress.md",
            "",
        ]
    )


def update_progress_for_next_phase(
    progress_path: Path,
    next_task_name: str,
    next_branch_name: str,
    next_plan_name: str,
    dry_run: bool,
) -> None:
    if not progress_path.exists():
        return
    text = progress_path.read_text(encoding="utf-8")

    current_progress = "\n".join(
        [
            "## 当前进展",
            "- 已完成：上一阶段已完成，本阶段已开启。",
            f"- 进行中：整理“{next_task_name}”的当前阶段方案与范围。",
            "- 下一步：补充当前阶段 plan，并等待明确开发指令。",
        ]
    )
    actual_changes = "\n".join(
        [
            "## 实际改动",
            "- 仓库：任务工作区",
            f"  - 改动内容：在原工作空间开启新阶段任务“{next_task_name}”，切换记录分支并新建阶段 plan。",
            f"  - 备注：当前阶段计划文件为 `{next_plan_name}`，记录分支为 `{next_branch_name}`。",
        ]
    )

    updated = re.sub(r"## 当前进展.*?(?=\n## |\Z)", current_progress + "\n\n", text, flags=re.S)
    if "## 当前进展" not in text:
        updated = updated.rstrip() + "\n\n" + current_progress + "\n"

    updated = re.sub(r"## 实际改动.*?(?=\n## |\Z)", actual_changes + "\n\n", updated, flags=re.S)
    if "## 实际改动" not in text:
        insert_at = updated.find("## 变更记录")
        if insert_at >= 0:
            updated = updated[:insert_at].rstrip() + "\n\n" + actual_changes + "\n\n" + updated[insert_at:]
        else:
            updated = updated.rstrip() + "\n\n" + actual_changes + "\n"

    marker = "## 变更记录"
    record = "\n".join(
        [
            f"- {dt.date.today().isoformat()}",
            f"  - 做了什么：下一阶段开启，当前任务为“{next_task_name}”",
            f"  - 结果：基于远程 {NEXT_BASE_BRANCH} 创建记录分支 `{next_branch_name}`，新阶段状态重置为方案中",
        ]
    )
    if marker in updated:
        updated = updated.replace(marker, marker + "\n" + record, 1)
    else:
        updated = updated.rstrip() + "\n\n" + marker + "\n" + record + "\n"

    print(f"update progress: {progress_path}")
    if not dry_run:
        progress_path.write_text(updated, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Start the next stage task in the current task workspace.")
    parser.add_argument("task_id", help="Full task id, e.g. YYYY-MM-DD-原始任务名")
    parser.add_argument("next_task_name", help="New stage task name.")
    parser.add_argument("--repo", action="append", dest="repos", help="Repo key to switch for the next stage. Repeatable.")
    parser.add_argument("--config-root", type=Path, default=DEFAULT_CONFIG_ROOT)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    workspace_cfg = load_yaml(args.config_root / "workspace.yaml")
    repositories_cfg_path = args.config_root / "repositories.yaml"
    repositories_cfg = load_yaml(repositories_cfg_path) if repositories_cfg_path.exists() else {}
    docs_root = Path(workspace_cfg["docs_root"])
    tasks_root = Path(workspace_cfg["tasks_root"])
    documents = workspace_cfg.get("documents", {})
    repo_cfg_by_key = {
        str(repo["key"]): repo
        for repo in repositories_cfg.get("repositories", [])
        if isinstance(repo, dict) and repo.get("key")
    }

    meta_path, meta = load_task_meta(docs_root, args.task_id)
    require_task_status(meta, ("已完成",), "next")

    next_task_name = sanitize_task_segment(args.next_task_name)
    next_branch_name = sanitize_branch_name(next_task_name)
    next_plan_name = _phase_document_name(str(documents.get("plan", "plan.md")), next_task_name)
    docs_task_root = docs_root / args.task_id
    next_plan_path = docs_task_root / next_plan_name
    if next_plan_path.exists():
        raise FileExistsError(f"next phase plan already exists: {next_plan_path}")

    repos = meta.get("repos", [])
    if not isinstance(repos, list):
        raise ValueError(f"invalid repos in task meta: {meta_path}")

    bound_repo_meta_by_key: dict[str, dict[str, Any]] = {}
    for repo_meta in repos:
        if not isinstance(repo_meta, dict):
            continue
        repo_key = str(repo_meta.get("key") or "").strip()
        if repo_key:
            bound_repo_meta_by_key[repo_key] = repo_meta

    try:
        selected_repo_keys = resolve_requested_repo_keys_or_aliases(
            args.repos or [],
            list(bound_repo_meta_by_key.keys()),
            repo_cfg_by_key,
        )
    except ValueError as exc:
        raise ValueError(f"invalid next repo target: {exc}") from exc

    selected_repos = [bound_repo_meta_by_key[repo_key] for repo_key in selected_repo_keys]

    failed = False
    repo_keys: list[str] = []
    for repo_meta in selected_repos:
        repo_key = str(repo_meta.get("key") or "unknown")
        repo_keys.append(repo_key)
        repo_path = resolve_repo_path(tasks_root, args.task_id, repo_meta)
        expected_branch = str(repo_meta.get("branch") or "")
        # `next` only needs a clean workspace and the recorded local branch.
        # The previous phase branch may already have been deleted from origin after release.
        issues = validate_repo_state(repo_path, False, expected_branch or None)
        if issues:
            failed = True
            print(f"[FAIL] {repo_key} -> {repo_path}")
            for issue in issues:
                print(f"  - {issue}")
        else:
            print(f"[OK] {repo_key} -> {repo_path}")

    if failed:
        print("next blocked")
        return 2

    for repo_meta in selected_repos:
        repo_path = resolve_repo_path(tasks_root, args.task_id, repo_meta)
        run(["git", "-C", str(repo_path), "fetch", "origin", "--prune"], args.dry_run)
        run(
            ["git", "-C", str(repo_path), "checkout", "-B", next_branch_name, f"origin/{NEXT_BASE_BRANCH}"],
            args.dry_run,
        )
        run(["git", "-C", str(repo_path), "branch", "--unset-upstream"], args.dry_run)
        repo_meta["branch"] = next_branch_name

    previous_task_name = str(meta.get("current_task_name") or _task_theme_name(args.task_id))
    previous_plan_name = str(meta.get("active_plan") or documents.get("plan", "plan.md"))
    previous_decision_log_name = str(meta.get("active_decision_log") or "").strip()
    if not previous_decision_log_name:
        default_decision_log_name = str(documents.get("decision_log", "") or "").strip()
        if default_decision_log_name and (docs_task_root / default_decision_log_name).exists():
            previous_decision_log_name = default_decision_log_name
    current_phase = _coerce_phase(meta.get("phase"))
    previous_phases = meta.get("previous_phases")
    if not isinstance(previous_phases, list):
        previous_phases = []
    previous_phase = {
        "phase": current_phase,
        "task_name": previous_task_name,
        "status": str(meta.get("status") or "已完成"),
        "plan": previous_plan_name,
    }
    if previous_decision_log_name:
        previous_phase["decision_log"] = previous_decision_log_name
    previous_phases.append(previous_phase)

    meta["status"] = "方案中"
    meta["resume_status"] = "方案中"
    meta["coding_allowed"] = False
    meta["phase"] = current_phase + 1
    meta["current_task_name"] = next_task_name
    meta["active_plan"] = next_plan_name
    meta.pop("active_decision_log", None)
    meta["previous_phases"] = previous_phases
    save_yaml(meta_path, meta, args.dry_run)

    workspace_title = _task_theme_name(args.task_id)
    index_path = docs_task_root / documents.get("index", "index.md")
    progress_path = docs_task_root / documents.get("progress", "progress.md")
    write_text(next_plan_path, render_next_phase_plan(next_task_name, repo_keys, previous_task_name, previous_plan_name), args.dry_run)
    write_text(
        index_path,
        render_next_index(
            workspace_title=workspace_title,
            next_task_name=next_task_name,
            previous_task_name=previous_task_name,
            next_status="方案中",
            next_plan_name=next_plan_name,
            previous_plan_name=previous_plan_name,
            phase=current_phase + 1,
        ),
        args.dry_run,
    )
    update_progress_for_next_phase(
        progress_path,
        next_task_name,
        next_branch_name,
        next_plan_name,
        args.dry_run,
    )
    print("task next phase ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
