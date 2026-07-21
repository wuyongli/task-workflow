#!/usr/bin/env python3

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from task_workflow_lib import (
    classify_repo_publish_kind,
    load_yaml,
    resolve_requested_repo_keys_or_aliases,
    switch_mysql_data_dir,
)


DEFAULT_CONFIG_ROOT = Path("/Users/wuyongli/Documents/sg-project/_workspace/config")


def resolve_mysql_switch_target(
    raw_target: str,
    repo_cfg_by_key: dict[str, dict[str, Any]],
) -> tuple[str, dict[str, Any]]:
    repo_keys = resolve_requested_repo_keys_or_aliases([raw_target], list(repo_cfg_by_key), repo_cfg_by_key)
    if len(repo_keys) != 1:
        raise ValueError(f"mysql target must resolve to exactly one repo: {raw_target}")

    repo_key = repo_keys[0]
    repo_cfg = repo_cfg_by_key[repo_key]
    if classify_repo_publish_kind(repo_cfg) != "backend":
        raise ValueError(f"mysql target must be a backend repo: {raw_target} -> {repo_key}")

    runtime_cfg = repo_cfg.get("runtime") or {}
    if not isinstance(runtime_cfg, dict) or not isinstance(runtime_cfg.get("mysql_data_switch"), dict):
        raise ValueError(f"repo {repo_key} has no mysql_data_switch config")

    return repo_key, repo_cfg


def main() -> int:
    parser = argparse.ArgumentParser(description="Switch the local shared MySQL data directory for backend development.")
    parser.add_argument("target", help="Backend target such as 产地后端 / 批发后端 / producer-backend / pf-backend")
    parser.add_argument("--config-root", type=Path, default=DEFAULT_CONFIG_ROOT)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    repositories_cfg = load_yaml(args.config_root / "repositories.yaml")
    repo_cfg_by_key = {str(repo["key"]): repo for repo in repositories_cfg.get("repositories", []) if isinstance(repo, dict)}

    repo_key, repo_cfg = resolve_mysql_switch_target(args.target, repo_cfg_by_key)
    result = switch_mysql_data_dir(repo_cfg, args.dry_run)

    print(f"[{repo_key}] mysql {result['status']}")
    print(f"  container: {result['container_name']}")
    print(f"  previous data dir: {result['previous_data_dir'] or '<none>'}")
    print(f"  target data dir: {result['target_data_dir']}")
    if result.get("command"):
        print(f"  command: {result['command']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
