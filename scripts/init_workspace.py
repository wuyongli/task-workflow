#!/usr/bin/env python3

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


DEFAULT_WORKSPACE_ROOT = Path("/Users/wuyongli/Documents/sg-project/_workspace")


def copy_if_missing(src: Path, dest: Path, dry_run: bool) -> None:
    if dest.exists():
        print(f"skip existing: {dest}")
        return
    print(f"create file: {dest}")
    if not dry_run:
        shutil.copy2(src, dest)


def main() -> int:
    parser = argparse.ArgumentParser(description="Initialize task-workflow workspace directories and config files.")
    parser.add_argument("--workspace-root", type=Path, default=DEFAULT_WORKSPACE_ROOT)
    parser.add_argument("--skill-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    workspace_root = args.workspace_root
    config_root = workspace_root / "config"
    tasks_root = workspace_root / "_tasks"
    docs_root = workspace_root / "_docs"
    references_root = args.skill_root / "references"

    for path in (workspace_root, config_root, tasks_root, docs_root):
        print(f"ensure dir: {path}")
        if not args.dry_run:
            path.mkdir(parents=True, exist_ok=True)

    copy_if_missing(references_root / "repositories.yaml.example", config_root / "repositories.yaml", args.dry_run)
    copy_if_missing(references_root / "workspace.yaml.example", config_root / "workspace.yaml", args.dry_run)

    print("workspace init complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
