#!/usr/bin/env python3

from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from task_workflow_lib import load_task_meta, load_yaml, save_yaml


DEFAULT_CONFIG_ROOT = Path("/Users/wuyongli/Documents/sg-project/_workspace/config")


def _legacy_stage(meta: dict[str, Any], documents: dict[str, Any]) -> dict[str, Any]:
    stage = {
        "phase": meta.get("phase", 1),
        "task_name": meta.get("current_task_name") or re.sub(r"^\d{4}-\d{2}-\d{2}-", "", meta["task_id"]),
        "status": meta.get("status"),
        "resume_status": meta.get("resume_status", meta.get("status")),
        "plan": meta.get("active_plan") or documents.get("plan", "plan.md"),
        "repos": [
            {"key": repo["key"], "branch": repo.get("branch", "")}
            for repo in meta.get("repos", []) if isinstance(repo, dict) and repo.get("key")
        ],
    }
    if meta.get("bbs_id"):
        stage["bbs_id"] = meta["bbs_id"]
    if meta.get("active_decision_log"):
        stage["decision_log"] = meta["active_decision_log"]
    return stage


def main() -> int:
    parser = argparse.ArgumentParser(description="Record a verified publication for one task stage without changing task authorization.")
    parser.add_argument("task_id")
    parser.add_argument("--phase", type=int, required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--node-id", required=True)
    parser.add_argument("--kind", choices=("proposal", "result"), required=True)
    parser.add_argument("--generated-at", help="ISO 8601 timestamp with timezone; defaults to current Beijing time.")
    parser.add_argument("--config-root", type=Path, default=DEFAULT_CONFIG_ROOT)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    title, url, node_id = (value.strip() for value in (args.title, args.url, args.node_id))
    if args.phase < 1 or not title or not node_id:
        raise ValueError("phase must be positive; title and node-id must not be empty")
    parsed_url = urlsplit(url)
    if parsed_url.scheme != "https" or not parsed_url.hostname or parsed_url.username or parsed_url.password:
        raise ValueError("url must be an HTTPS document link without credentials")
    generated_at = args.generated_at or dt.datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")
    timestamp = dt.datetime.fromisoformat(generated_at)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("generated-at must include a timezone")

    workspace = load_yaml(args.config_root / "workspace.yaml")
    docs_root = Path(workspace["docs_root"])
    if (docs_root / args.task_id).resolve().parent != docs_root.resolve():
        raise ValueError("task_id must identify one task directly under docs_root")
    meta_path, meta = load_task_meta(docs_root, args.task_id)
    current = meta.get("current_stage")
    if current is not None and not isinstance(current, dict):
        raise ValueError("invalid current_stage: expected a mapping")
    legacy = current is None
    if legacy:
        current = _legacy_stage(meta, workspace.get("documents", {}))
    history = meta.get("previous_phases", [])
    if not isinstance(history, list) or any(not isinstance(stage, dict) for stage in history):
        raise ValueError("invalid previous_phases: expected a list of stages")
    stages = [current, *history]
    matches = [stage for stage in stages if str(stage.get("phase")) == str(args.phase)]
    if len(matches) != 1:
        raise ValueError(f"phase {args.phase} must match exactly one recorded stage")
    target = matches[0]
    entry = {"title": title, "node_id": node_id, "url": url, "kind": args.kind, "generated_at": generated_at}
    for stage in stages:
        publications = stage.get("publications", [])
        if not isinstance(publications, list) or any(not isinstance(item, dict) for item in publications):
            raise ValueError("invalid publications: expected a list of records")
        for item in publications:
            if item.get("node_id") != node_id:
                continue
            if stage is not target or any(item.get(key) != entry[key] for key in ("title", "url", "kind")):
                raise ValueError("node-id is already recorded with different stage or document details; verify before changing it")
            print(f"publication already recorded for phase {args.phase}; no changes")
            return 0
    target.setdefault("publications", []).append(entry)
    if legacy and target is current:
        meta["current_stage"] = current
    save_yaml(meta_path, meta, args.dry_run)
    print(f"publication recorded for phase {args.phase}" if not args.dry_run else f"would record publication for phase {args.phase}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2)
