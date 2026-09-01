#!/usr/bin/env python3

from __future__ import annotations

import argparse
import datetime as dt
import re
import subprocess
from pathlib import Path
from typing import Any

from task_workflow_lib import (
    load_task_meta,
    load_yaml,
    resolve_repo_path,
    run,
    save_yaml,
    validate_repo_state,
    write_text,
)


DEFAULT_CONFIG_ROOT = Path("/Users/wuyongli/Documents/sg-project/_workspace/config")


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


def _repo_branches(repos: list[Any]) -> list[dict[str, str]]:
    branches: list[dict[str, str]] = []
    for repo_meta in repos:
        if not isinstance(repo_meta, dict):
            continue
        repo_key = str(repo_meta.get("key") or "").strip()
        branch = str(repo_meta.get("branch") or "").strip()
        if repo_key:
            branches.append({"key": repo_key, "branch": branch})
    return branches


def _snapshot_current_stage(meta: dict[str, Any], documents: dict[str, Any]) -> dict[str, Any]:
    current_stage = meta.get("current_stage")
    if isinstance(current_stage, dict):
        snapshot = dict(current_stage)
    else:
        snapshot = {
            "phase": _coerce_phase(meta.get("phase")),
            "task_name": str(meta.get("current_task_name") or _task_theme_name(str(meta.get("task_id") or ""))),
            "status": str(meta.get("status") or ""),
            "resume_status": str(meta.get("resume_status") or meta.get("status") or ""),
            "plan": str(meta.get("active_plan") or documents.get("plan", "plan.md")),
        }
        bbs_id = str(meta.get("bbs_id") or "").strip()
        if bbs_id:
            snapshot["bbs_id"] = bbs_id
    decision_log = str(snapshot.get("decision_log") or meta.get("active_decision_log") or "").strip()
    if decision_log:
        snapshot["decision_log"] = decision_log
    snapshot["repos"] = _repo_branches(meta.get("repos", []) if isinstance(meta.get("repos"), list) else [])
    return snapshot


def _find_stage(meta: dict[str, Any], documents: dict[str, Any], target: str) -> dict[str, Any] | None:
    normalized = target.strip()
    current = _snapshot_current_stage(meta, documents)
    stages: list[dict[str, Any]] = [current]
    previous_phases = meta.get("previous_phases")
    if isinstance(previous_phases, list):
        stages.extend(stage for stage in previous_phases if isinstance(stage, dict))

    for stage in stages:
        phase = str(stage.get("phase") or "").strip()
        task_name = str(stage.get("task_name") or "").strip()
        if normalized == phase or normalized == task_name:
            return dict(stage)
    return None


def _local_branch_exists(repo_path: Path, branch: str) -> bool:
    result = subprocess.run(
        ["git", "-C", str(repo_path), "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
        text=True,
        capture_output=True,
    )
    return result.returncode == 0


def _stage_repo_branch_map(stage: dict[str, Any]) -> dict[str, str]:
    repos = stage.get("repos")
    if not isinstance(repos, list):
        return {}
    branches: dict[str, str] = {}
    for repo in repos:
        if not isinstance(repo, dict):
            continue
        repo_key = str(repo.get("key") or "").strip()
        branch = str(repo.get("branch") or "").strip()
        if repo_key and branch:
            branches[repo_key] = branch
    return branches


def _coding_allowed_for_status(status: str) -> bool:
    return status in {"开发中", "测试中"}


def render_stage_index(
    workspace_title: str,
    target_stage: dict[str, Any],
    current_plan_name: str,
    previous_phases: list[dict[str, Any]],
) -> str:
    bbs_id = str(target_stage.get("bbs_id") or "").strip()
    bbs_lines = [f"- 需求编号：#{bbs_id.lstrip('#')}"] if bbs_id else []
    previous_lines = [
        f"- 第 {stage.get('phase')} 阶段：{stage.get('task_name')}（{stage.get('status', '未知')}） -> ./{stage.get('plan')}"
        for stage in previous_phases
        if stage.get("phase") and stage.get("task_name") and stage.get("plan")
    ]
    if not previous_lines:
        previous_lines = ["- 无"]

    return "\n".join(
        [
            f"# {workspace_title}",
            "",
            "## 任务摘要",
            f"- 当前状态：{target_stage.get('status', '未知')}",
            *bbs_lines,
            f"- 当前主线：已切换到“{target_stage.get('task_name')}”阶段。",
            "- 当前阻塞：无",
            "- 下一步：按当前阶段 plan 继续推进。",
            "",
            "## 阶段关系",
            f"- 当前阶段：第 {target_stage.get('phase')} 阶段",
            f"- 当前阶段任务：{target_stage.get('task_name')}",
            "",
            "## 当前入口",
            "- 事实：./meta.yaml",
            f"- 当前方案：./{current_plan_name}",
            "- 进度：./progress.md",
            "",
            "## 历史阶段",
            *previous_lines,
            "",
        ]
    )


def append_progress_stage_switch(progress_path: Path, target_stage: dict[str, Any], dry_run: bool) -> None:
    if not progress_path.exists():
        return
    text = progress_path.read_text(encoding="utf-8")
    marker = "## 变更记录"
    record = "\n".join(
        [
            f"- {dt.date.today().isoformat()}",
            f"  - 做了什么：切换当前工作阶段到“{target_stage.get('task_name')}”",
            f"  - 结果：已切换到第 {target_stage.get('phase')} 阶段，当前方案为 `{target_stage.get('plan')}`",
        ]
    )
    if marker in text:
        updated = text.replace(marker, marker + "\n" + record, 1)
    else:
        updated = text.rstrip() + "\n\n" + marker + "\n" + record + "\n"
    print(f"update progress: {progress_path}")
    if not dry_run:
        progress_path.write_text(updated, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Switch the current stage inside an existing task workspace.")
    parser.add_argument("task_id", help="Full task id, e.g. YYYY-MM-DD-原始任务名")
    parser.add_argument("target_stage", help="Target phase number or stage task name.")
    parser.add_argument("--config-root", type=Path, default=DEFAULT_CONFIG_ROOT)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    workspace_cfg = load_yaml(args.config_root / "workspace.yaml")
    docs_root = Path(workspace_cfg["docs_root"])
    tasks_root = Path(workspace_cfg["tasks_root"])
    documents = workspace_cfg.get("documents", {})
    if not isinstance(documents, dict):
        documents = {}

    meta_path, meta = load_task_meta(docs_root, args.task_id)
    repos = meta.get("repos")
    if not isinstance(repos, list):
        raise ValueError(f"invalid repos in task meta: {meta_path}")

    current_stage = _snapshot_current_stage(meta, documents)
    target_stage = _find_stage(meta, documents, args.target_stage)
    if target_stage is None:
        print(f"stage switch blocked: target stage not found: {args.target_stage}")
        return 2

    if str(target_stage.get("phase")) == str(current_stage.get("phase")):
        print(f"stage already current: {target_stage.get('task_name')}")
        return 0

    target_branch_by_key = _stage_repo_branch_map(target_stage)
    if not target_branch_by_key:
        print("stage switch blocked: target stage has no recorded repo branches")
        return 2

    repo_meta_by_key = {
        str(repo.get("key") or "").strip(): repo
        for repo in repos
        if isinstance(repo, dict) and str(repo.get("key") or "").strip()
    }
    bound_repo_keys = set(repo_meta_by_key)
    target_repo_keys = set(target_branch_by_key)
    missing_target_repo_keys = sorted(bound_repo_keys - target_repo_keys)
    extra_target_repo_keys = sorted(target_repo_keys - bound_repo_keys)
    if missing_target_repo_keys or extra_target_repo_keys:
        if missing_target_repo_keys:
            print(f"stage switch blocked: target stage missing repo branches: {', '.join(missing_target_repo_keys)}")
        if extra_target_repo_keys:
            print(f"stage switch blocked: target stage contains unbound repos: {', '.join(extra_target_repo_keys)}")
        return 2

    failed = False
    for repo_key, branch in target_branch_by_key.items():
        repo_meta = repo_meta_by_key.get(repo_key)
        if repo_meta is None:
            failed = True
            print(f"[FAIL] {repo_key} -> repo is not bound in current task")
            continue
        repo_path = resolve_repo_path(tasks_root, args.task_id, repo_meta)
        current_branch = str(repo_meta.get("branch") or "")
        issues = validate_repo_state(repo_path, False, current_branch or None)
        if issues:
            failed = True
            print(f"[FAIL] {repo_key} -> {repo_path}")
            for issue in issues:
                print(f"  - {issue}")
            continue
        if not _local_branch_exists(repo_path, branch):
            failed = True
            print(f"[FAIL] {repo_key} -> local branch does not exist: {branch}")
            continue
        print(f"[OK] {repo_key} -> {branch}")

    if failed:
        print("stage switch blocked")
        return 2

    switched_repo_keys: list[str] = []
    for repo_key, branch in target_branch_by_key.items():
        repo_meta = repo_meta_by_key[repo_key]
        repo_path = resolve_repo_path(tasks_root, args.task_id, repo_meta)
        try:
            run(["git", "-C", str(repo_path), "checkout", branch], args.dry_run)
        except subprocess.CalledProcessError as exc:
            print(f"[FAIL] {repo_key} -> checkout failed: {branch}")
            print(f"  command: {' '.join(str(part) for part in exc.cmd)}")
            print("stage switch interrupted before meta.yaml update")
            if switched_repo_keys:
                print(f"  switched repos: {', '.join(switched_repo_keys)}")
                unswitched_repo_keys = [key for key in target_branch_by_key if key not in switched_repo_keys and key != repo_key]
                if unswitched_repo_keys:
                    print(f"  not switched repos: {', '.join(unswitched_repo_keys)}")
                print("  next: repo branches may be inconsistent; inspect git branches before retrying")
            return 3
        repo_meta["branch"] = branch
        switched_repo_keys.append(repo_key)

    previous_phases = meta.get("previous_phases")
    if not isinstance(previous_phases, list):
        previous_phases = []
    next_previous_phases = [
        dict(stage)
        for stage in previous_phases
        if isinstance(stage, dict) and str(stage.get("phase")) != str(target_stage.get("phase"))
    ]
    next_previous_phases.append(current_stage)
    next_previous_phases.sort(key=lambda stage: _coerce_phase(stage.get("phase")))

    target_status = str(target_stage.get("status") or "方案中")
    target_resume_status = str(target_stage.get("resume_status") or target_status)
    target_plan = str(target_stage.get("plan") or documents.get("plan", "plan.md"))
    target_task_name = str(target_stage.get("task_name") or _task_theme_name(args.task_id))
    target_bbs_id = str(target_stage.get("bbs_id") or "").strip()
    target_decision_log = str(target_stage.get("decision_log") or "").strip()

    meta["status"] = target_status
    meta["resume_status"] = target_resume_status
    meta["coding_allowed"] = _coding_allowed_for_status(target_status)
    meta["phase"] = _coerce_phase(target_stage.get("phase"))
    meta["current_task_name"] = target_task_name
    meta["active_plan"] = target_plan
    if target_decision_log:
        meta["active_decision_log"] = target_decision_log
    else:
        meta.pop("active_decision_log", None)
    if target_bbs_id:
        meta["bbs_id"] = target_bbs_id
    else:
        meta.pop("bbs_id", None)
    meta["current_stage"] = {
        "phase": _coerce_phase(target_stage.get("phase")),
        "task_name": target_task_name,
        "status": target_status,
        "resume_status": target_resume_status,
        "plan": target_plan,
        "repos": _repo_branches(repos),
    }
    if target_bbs_id:
        meta["current_stage"]["bbs_id"] = target_bbs_id
    if target_decision_log:
        meta["current_stage"]["decision_log"] = target_decision_log
    meta["previous_phases"] = next_previous_phases
    save_yaml(meta_path, meta, args.dry_run)

    docs_task_root = docs_root / args.task_id
    write_text(
        docs_task_root / str(documents.get("index", "index.md")),
        render_stage_index(_task_theme_name(args.task_id), meta["current_stage"], target_plan, next_previous_phases),
        args.dry_run,
    )
    append_progress_stage_switch(
        docs_task_root / str(documents.get("progress", "progress.md")),
        meta["current_stage"],
        args.dry_run,
    )
    print("task stage switched")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
