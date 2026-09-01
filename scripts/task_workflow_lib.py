#!/usr/bin/env python3

from __future__ import annotations

import json
import re
import shutil
import socket
import subprocess
from pathlib import Path
from typing import Any

import yaml
from pypinyin import lazy_pinyin


PUBLISH_TARGET_ALIASES: dict[str, set[str]] = {
    "backend": {"后端", "backend"},
    "frontend": {"前端", "frontend"},
    "mobile_frontend": {"手机前端", "手机端", "移动端", "mobilefrontend"},
    "pc_frontend": {"pc前端", "pc端", "pcfrontend"},
}

PUBLISH_KIND_ORDER = {
    "backend": 0,
    "mobile_frontend": 1,
    "pc_frontend": 2,
}


def sanitize_task_segment(raw_name: str) -> str:
    name = raw_name.strip()
    name = re.sub(r"[\r\n\t]+", " ", name)
    name = re.sub(r"[/:]+", "-", name)
    name = re.sub(r"\s+", " ", name).strip()
    if not name:
        raise ValueError("task name is empty after sanitization")
    return name


def sanitize_branch_name(raw_name: str) -> str:
    name = raw_name.strip()
    name = re.sub(r"\s+", "-", name)
    name = name.replace("@{", "-")
    name = re.sub(r"[ /\\\\~^:?*\[\]\x00-\x20\x7f]+", "-", name)
    name = re.sub(r"-{2,}", "-", name)
    while ".." in name:
        name = name.replace("..", ".")
    name = name.strip("./-")
    if name.endswith(".lock"):
        name = name[:-5].rstrip("./-") + "-lock"
    if not name:
        raise ValueError("branch name is empty after sanitization")
    return name


def sanitize_compose_name(raw_name: str) -> str:
    name = raw_name.strip().lower()
    name = re.sub(r"[^a-z0-9_.-]+", "-", name)
    name = re.sub(r"-{2,}", "-", name)
    name = name.strip(".-")
    if not name:
        raise ValueError("compose project name is empty after sanitization")
    return name


def _extract_task_parts(task_id: str) -> tuple[str, str]:
    match = re.match(r"^(\d{4})-(\d{2})-(\d{2})-(.+)$", task_id.strip())
    if not match:
        raise ValueError(f"invalid task id for compose name: {task_id}")
    yyyy, mm, dd, raw_task_name = match.groups()
    return f"{yyyy}{mm}{dd}", raw_task_name


def _current_stage(task_meta: dict[str, Any]) -> dict[str, Any]:
    current_stage = task_meta.get("current_stage")
    return current_stage if isinstance(current_stage, dict) else {}


def current_task_title_name(task_meta: dict[str, Any]) -> str:
    current_stage = _current_stage(task_meta)
    for value in (
        current_stage.get("task_name"),
        task_meta.get("current_task_name"),
    ):
        if isinstance(value, str) and value.strip():
            return value.strip()

    task_id = str(task_meta.get("task_id") or "").strip()
    _, raw_task_name = _extract_task_parts(task_id)
    return raw_task_name.strip()


def build_pr_default_title(
    task_meta: dict[str, Any],
    target_repo_key: str,
    bound_repo_keys: list[str],
    repo_cfg_by_key: dict[str, dict[str, Any]],
) -> str:
    title = current_task_title_name(task_meta)

    repo_kinds: dict[str, str] = {}
    for repo_key in bound_repo_keys:
        repo_cfg = repo_cfg_by_key.get(repo_key)
        if repo_cfg is None:
            continue
        repo_kind = classify_repo_publish_kind(repo_cfg)
        if repo_kind:
            repo_kinds[repo_key] = repo_kind

    target_kind = repo_kinds.get(target_repo_key)
    has_backend = any(repo_kind == "backend" for repo_kind in repo_kinds.values())
    has_frontend = any(repo_kind in {"mobile_frontend", "pc_frontend"} for repo_kind in repo_kinds.values())
    suffix = ""
    if target_kind == "backend" and has_frontend:
        suffix = "（有前端）"
    elif target_kind in {"mobile_frontend", "pc_frontend"} and has_backend:
        suffix = "（有后端）"

    return title + suffix


def build_task_compose_name(task_id: str, repo_key: str) -> str:
    date_part, raw_task_name = _extract_task_parts(task_id)
    pinyin_parts = lazy_pinyin(raw_task_name, errors="ignore")
    task_pinyin = "".join(part.lower() for part in pinyin_parts if part.strip())
    if not task_pinyin:
        task_pinyin = "task"
    return sanitize_compose_name(f"{date_part}-{task_pinyin}-{repo_key}")


def build_repo_dir_name(repo_key: str, raw_task_name: str) -> str:
    return f"{repo_key}__{raw_task_name}"


def normalize_publish_target(raw_target: str) -> str:
    target = raw_target.strip().lower()
    target = re.sub(r"\s+", "", target)
    if not target:
        raise ValueError("publish target is empty")
    return target


def resolve_publish_target_kind(raw_target: str) -> str:
    normalized = normalize_publish_target(raw_target)
    for target_kind, aliases in PUBLISH_TARGET_ALIASES.items():
        normalized_aliases = {normalize_publish_target(alias) for alias in aliases}
        if normalized in normalized_aliases:
            return target_kind
    supported = "、".join(sorted(alias for aliases in PUBLISH_TARGET_ALIASES.values() for alias in aliases))
    raise ValueError(f"unknown publish target: {raw_target}. supported targets: {supported}")


def _repo_aliases(repo_key: str, repo_cfg: dict[str, Any]) -> list[str]:
    aliases = [repo_key]
    raw_aliases = repo_cfg.get("aliases")
    if isinstance(raw_aliases, list):
        aliases.extend(str(alias) for alias in raw_aliases if str(alias).strip())
    return aliases


def resolve_repo_alias_key(
    raw_target: str,
    bound_repo_keys: list[str],
    repo_cfg_by_key: dict[str, dict[str, Any]],
) -> str | None:
    normalized = normalize_publish_target(raw_target)
    matches: list[str] = []
    for repo_key in bound_repo_keys:
        repo_cfg = repo_cfg_by_key.get(repo_key)
        if repo_cfg is None:
            continue
        normalized_aliases = {normalize_publish_target(alias) for alias in _repo_aliases(repo_key, repo_cfg)}
        if normalized in normalized_aliases:
            matches.append(repo_key)

    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ValueError(f"repo alias target is ambiguous: {raw_target} -> {', '.join(matches)}")
    return None


def ordered_target_kinds(target_kinds: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for target_kind in target_kinds:
        if target_kind in seen:
            continue
        seen.add(target_kind)
        unique.append(target_kind)
    return sorted(unique, key=lambda item: (PUBLISH_KIND_ORDER.get(item, 99), item))


def normalize_requested_target_kinds(target_kinds: list[str]) -> list[str]:
    ordered = ordered_target_kinds(target_kinds)
    unique = set(ordered)
    if "frontend" in unique and {"mobile_frontend", "pc_frontend"}.issubset(unique):
        ordered = [item for item in ordered if item != "frontend"]
    return ordered


def resolve_requested_repo_keys(
    raw_targets: list[str],
    bound_repo_keys: list[str],
    repo_cfg_by_key: dict[str, dict[str, Any]],
) -> list[str]:
    if not raw_targets:
        return list(bound_repo_keys)

    resolved: list[str] = []
    seen: set[str] = set()
    alias_targets: list[str] = []
    for raw_target in raw_targets:
        repo_key = resolve_repo_alias_key(raw_target, bound_repo_keys, repo_cfg_by_key)
        if repo_key is None:
            alias_targets.append(raw_target)
            continue
        if repo_key not in seen:
            seen.add(repo_key)
            resolved.append(repo_key)

    target_kinds = normalize_requested_target_kinds([resolve_publish_target_kind(target) for target in alias_targets])
    for target_kind in target_kinds:
        repo_key = resolve_task_publish_repo_key(target_kind, bound_repo_keys, repo_cfg_by_key)
        if repo_key in seen:
            continue
        seen.add(repo_key)
        resolved.append(repo_key)
    return resolved


def resolve_requested_repo_keys_or_aliases(
    raw_targets: list[str],
    bound_repo_keys: list[str],
    repo_cfg_by_key: dict[str, dict[str, Any]],
) -> list[str]:
    if not raw_targets:
        return list(bound_repo_keys)

    resolved: list[str] = []
    alias_targets: list[str] = []
    seen: set[str] = set()
    bound_repo_key_set = set(bound_repo_keys)

    for raw_target in raw_targets:
        normalized = raw_target.strip()
        if normalized in bound_repo_key_set:
            if normalized not in seen:
                seen.add(normalized)
                resolved.append(normalized)
            continue
        repo_key = resolve_repo_alias_key(raw_target, bound_repo_keys, repo_cfg_by_key)
        if repo_key is not None:
            if repo_key not in seen:
                seen.add(repo_key)
                resolved.append(repo_key)
            continue
        alias_targets.append(raw_target)

    if alias_targets:
        for repo_key in resolve_requested_repo_keys(alias_targets, bound_repo_keys, repo_cfg_by_key):
            if repo_key in seen:
                continue
            seen.add(repo_key)
            resolved.append(repo_key)
    return resolved


def classify_repo_publish_kind(repo_cfg: dict[str, Any]) -> str | None:
    repo_key = str(repo_cfg.get("key") or "")
    repo_path = str(repo_cfg.get("path") or "")
    notes = str(repo_cfg.get("notes") or "")
    runtime = repo_cfg.get("runtime")
    runtime_mode = ""
    if isinstance(runtime, dict):
        runtime_mode = str(runtime.get("mode") or "")

    combined = " ".join([repo_key, repo_path, notes, runtime_mode]).lower()

    if runtime_mode == "shared-backend-app" or "后端" in notes or "backend" in combined:
        return "backend"

    if runtime_mode == "patch-node-frontend-environment":
        if "手机" in notes or "mobile" in combined or "mproducer" in combined:
            return "mobile_frontend"
        if "pc" in notes.lower() or "pc" in combined:
            return "pc_frontend"

    return None


def resolve_task_publish_repo_key(
    target_kind: str,
    bound_repo_keys: list[str],
    repo_cfg_by_key: dict[str, dict[str, Any]],
) -> str:
    if target_kind == "frontend":
        frontend_matches: list[str] = []
        for repo_key in bound_repo_keys:
            repo_cfg = repo_cfg_by_key.get(repo_key)
            if repo_cfg is None:
                continue
            if classify_repo_publish_kind(repo_cfg) in {"mobile_frontend", "pc_frontend"}:
                frontend_matches.append(repo_key)

        if len(frontend_matches) == 1:
            return frontend_matches[0]
        if not frontend_matches:
            raise ValueError("no bound repo matches generic frontend publish target")
        raise ValueError(
            "generic frontend target is ambiguous; please specify 手机前端 or PC前端"
        )

    matches: list[str] = []
    for repo_key in bound_repo_keys:
        repo_cfg = repo_cfg_by_key.get(repo_key)
        if repo_cfg is None:
            continue
        if classify_repo_publish_kind(repo_cfg) == target_kind:
            matches.append(repo_key)

    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise ValueError(f"no bound repo matches publish target kind: {target_kind}")
    raise ValueError(f"multiple bound repos match publish target kind {target_kind}: {', '.join(matches)}")


def resolve_publish_command(repo_cfg: dict[str, Any]) -> list[str]:
    repo_key = str(repo_cfg.get("key") or "")
    target_kind = classify_repo_publish_kind(repo_cfg)
    if target_kind == "backend":
        return ["sg", "publish", "jenkins"]
    if target_kind in {"mobile_frontend", "pc_frontend"}:
        return ["sg", "publish", "local"]

    raise ValueError(f"repo {repo_key or '<unknown>'} has no supported publish command mapping")


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"invalid yaml root in {path}")
    return data


def save_yaml(path: Path, data: dict[str, Any], dry_run: bool) -> None:
    print(f"write yaml: {path}")
    if not dry_run:
        path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def write_text(path: Path, content: str, dry_run: bool) -> None:
    print(f"write file: {path}")
    if not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content.rstrip() + "\n", encoding="utf-8")


def copy_file(src: Path, dest: Path, dry_run: bool) -> None:
    print(f"copy file: {src} -> {dest}")
    if dry_run:
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)


def should_prepare_local_file(target: Path, prepared_targets: set[Path]) -> bool:
    if target in prepared_targets:
        return False
    if not target.exists():
        return True
    return target.is_file() and target.stat().st_size == 0


def _ensure_local_git_excludes(repo_path: Path, rel_paths: list[str], dry_run: bool) -> None:
    exclude_path = repo_path / ".git/info/exclude"
    if not exclude_path.parent.is_dir():
        return

    existing_text = exclude_path.read_text(encoding="utf-8") if exclude_path.exists() else ""
    existing_lines = set(existing_text.splitlines())
    missing_paths = [rel_path for rel_path in rel_paths if rel_path not in existing_lines]
    if not missing_paths:
        return

    print(f"update local git excludes: {exclude_path}")
    if dry_run:
        return
    prefix = existing_text.rstrip("\n")
    updated_lines = [prefix] if prefix else []
    updated_lines.extend(missing_paths)
    exclude_path.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")


def run(cmd: list[str], dry_run: bool, capture: bool = False) -> str:
    print("$", " ".join(cmd))
    if dry_run:
        return ""
    result = subprocess.run(cmd, check=True, text=True, capture_output=capture)
    return result.stdout.strip() if capture else ""


def run_shell(command: str, dry_run: bool, cwd: Path | None = None) -> None:
    location = f" (cwd={cwd})" if cwd else ""
    print(f"$ {command}{location}")
    if dry_run:
        return
    subprocess.run(command, shell=True, check=True, text=True, cwd=str(cwd) if cwd else None)


def run_git(repo_path: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_path), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def resolve_default_branch(repo_path: Path, dry_run: bool) -> str:
    if dry_run:
        return "__origin_default__"
    try:
        ref = run(["git", "-C", str(repo_path), "symbolic-ref", "refs/remotes/origin/HEAD"], False, capture=True)
        if ref.startswith("refs/remotes/origin/"):
            return ref.removeprefix("refs/remotes/origin/")
    except subprocess.CalledProcessError:
        pass
    branch = run_git(repo_path, "branch", "--show-current")
    if branch:
        return branch
    raise ValueError(f"cannot determine default branch for repo: {repo_path}")


def ensure_repo_clone(repo_path: Path, remote: str, dry_run: bool) -> None:
    if repo_path.exists():
        return
    repo_path.parent.mkdir(parents=True, exist_ok=True)
    run(["git", "clone", remote, str(repo_path)], dry_run)


def prepare_repo_from_default(repo_path: Path, remote: str, branch_name: str, dry_run: bool) -> None:
    run(["git", "-C", str(repo_path), "remote", "set-url", "origin", remote], dry_run)
    run(["git", "-C", str(repo_path), "fetch", "origin", "--prune"], dry_run)
    base_branch = resolve_default_branch(repo_path, dry_run)
    run(["git", "-C", str(repo_path), "checkout", "-B", branch_name, f"origin/{base_branch}"], dry_run)
    # Use the remote default branch only as the latest starting point.
    # The task branch should not inherit upstream tracking from origin/<base_branch>.
    run(["git", "-C", str(repo_path), "branch", "--unset-upstream"], dry_run)


def require_task_status(task_meta: dict[str, Any], allowed_statuses: tuple[str, ...], action: str) -> str:
    current_status = str(task_meta.get("status") or "")
    if current_status not in allowed_statuses:
        allowed_text = ", ".join(allowed_statuses)
        raise ValueError(
            f"{action} requires task status in [{allowed_text}], current status: {current_status or '未知'}"
        )
    return current_status


def resolve_repo_path(tasks_root: Path, task_id: str, repo_meta: dict[str, Any]) -> Path:
    repo_dir = repo_meta.get("repo_dir")
    if repo_dir:
        return tasks_root / task_id / str(repo_dir)

    relative_path = repo_meta.get("relative_path")
    if relative_path:
        return tasks_root.parent / str(relative_path)

    absolute_path = repo_meta.get("path")
    if absolute_path:
        return Path(str(absolute_path))

    raise ValueError(f"repo path metadata is missing for task {task_id}")


def safe_remove_path(path: Path, dry_run: bool) -> None:
    if not path.exists() and not path.is_symlink():
        return
    print(f"remove: {path}")
    if dry_run:
        return
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def safe_remove_empty_dir(path: Path, dry_run: bool) -> None:
    if not path.exists():
        return
    if any(path.iterdir()):
        return
    print(f"rmdir: {path}")
    if not dry_run:
        path.rmdir()


def _as_string_list(values: Any) -> list[str]:
    if values is None:
        return []
    if not isinstance(values, list):
        raise ValueError("runtime config must use list values")
    items: list[str] = []
    for value in values:
        if not isinstance(value, str):
            raise ValueError("runtime config string list contains a non-string item")
        items.append(value)
    return items


def _as_mapping_list(values: Any) -> list[dict[str, str]]:
    if values is None:
        return []
    if not isinstance(values, list):
        raise ValueError("runtime config must use list values")
    items: list[dict[str, str]] = []
    for value in values:
        if not isinstance(value, dict):
            raise ValueError("runtime config mapping list contains a non-mapping item")
        normalized: dict[str, str] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not isinstance(item, str):
                raise ValueError("runtime config mappings must use string keys and values")
            normalized[key] = item
        items.append(normalized)
    return items


def _as_command_steps(values: Any) -> list[dict[str, str]]:
    if values is None:
        return []
    if not isinstance(values, list):
        raise ValueError("runtime config must use list values")

    normalized: list[dict[str, str]] = []
    for value in values:
        if not isinstance(value, dict):
            raise ValueError("runtime config mapping list contains a non-mapping item")

        command = value.get("command")
        cwd = value.get("cwd", "")
        allow_failure = value.get("allow_failure", False)
        if not isinstance(command, str) or not command:
            raise ValueError("auto start step requires command")
        if not isinstance(cwd, str):
            raise ValueError("auto start step cwd must be a string")
        if not isinstance(allow_failure, bool):
            raise ValueError("auto start step allow_failure must be a boolean")

        normalized.append(
            {
                "command": command,
                "cwd": cwd,
                "allow_failure": "true" if allow_failure else "false",
            }
        )
    return normalized


def _parse_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    data: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip()
    return data


def _find_task_repo_path(task_root: Path, repo_key: str) -> Path | None:
    matches = sorted(path for path in task_root.glob(f"{repo_key}__*") if path.is_dir())
    if not matches:
        return None
    return matches[0]


def _find_listening_pids(port: int) -> list[int]:
    result = subprocess.run(
        [f"lsof", f"-tiTCP:{port}", "-sTCP:LISTEN"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode not in (0, 1):
        raise subprocess.CalledProcessError(result.returncode, result.args, result.stdout, result.stderr)

    pids: list[int] = []
    for line in result.stdout.splitlines():
        pid_text = line.strip()
        if pid_text.isdigit():
            pids.append(int(pid_text))
    return pids


def _read_process_cwd(pid: int) -> str | None:
    result = subprocess.run(
        ["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode not in (0, 1):
        raise subprocess.CalledProcessError(result.returncode, result.args, result.stdout, result.stderr)

    for line in result.stdout.splitlines():
        if line.startswith("n") and line[1:].strip():
            return line[1:].strip()
    return None


def _find_listening_processes(port: int) -> list[dict[str, str | int | None]]:
    processes: list[dict[str, str | int | None]] = []
    for pid in _find_listening_pids(port):
        processes.append(
            {
                "pid": pid,
                "cwd": _read_process_cwd(pid),
            }
        )
    return processes


def _process_belongs_to_repo(process_cwd: str | None, repo_path: Path) -> bool:
    if not process_cwd:
        return False
    repo_root = repo_path.resolve()
    process_root = Path(process_cwd).resolve()
    return process_root == repo_root or process_root.is_relative_to(repo_root)


def _stop_node_frontend_runtime(
    repo_cfg: dict[str, Any],
    repo_path: Path,
    runtime_cfg: dict[str, Any],
    dry_run: bool,
) -> list[str]:
    env_rel_path = str(runtime_cfg.get("task_env_file", ".codex/task-runtime.env"))
    port_key = str(runtime_cfg.get("task_port_key", "TASK_WEB_PORT"))
    env_data = _parse_env_file(repo_path / env_rel_path)
    port_text = env_data.get(port_key, "").strip()
    if not port_text:
        return [f"{repo_cfg.get('key')}: no {port_key} found, skip runtime stop"]

    port = int(port_text)
    processes = _find_listening_processes(port)
    if not processes:
        return [f"{repo_cfg.get('key')}: no listener on port {port}"]

    messages: list[str] = []
    for process in processes:
        pid = int(process["pid"])
        process_cwd = process.get("cwd")
        if not _process_belongs_to_repo(process_cwd if isinstance(process_cwd, str) else None, repo_path):
            messages.append(
                f"{repo_cfg.get('key')}: skip pid {pid} on port {port} because it does not belong to current repo"
            )
            continue
        print(f"stop frontend runtime: pid={pid} port={port}")
        if not dry_run:
            subprocess.run(["kill", str(pid)], check=True, text=True)
        messages.append(f"{repo_cfg.get('key')}: stopped pid {pid} on port {port}")
    return messages


def _stop_shared_backend_runtime(
    repo_cfg: dict[str, Any],
    repo_path: Path,
    runtime_cfg: dict[str, Any],
    dry_run: bool,
) -> list[str]:
    env_rel_path = str(runtime_cfg.get("task_env_file", "docker/.task.env"))
    compose_rel_path = str(runtime_cfg.get("task_compose_file", "docker/docker-compose.task.yml"))
    env_path = repo_path / env_rel_path
    compose_path = repo_path / compose_rel_path
    if not env_path.exists() or not compose_path.exists():
        return [f"{repo_cfg.get('key')}: task docker files missing, skip runtime stop"]

    command = [
        "docker",
        "compose",
        "--env-file",
        env_path.name,
        "-f",
        compose_path.name,
        "stop",
        "app",
    ]
    cwd = compose_path.parent
    print("$", " ".join(command), f"(cwd={cwd})")
    if not dry_run:
        subprocess.run(command, check=True, text=True, cwd=str(cwd))
    return [f"{repo_cfg.get('key')}: stopped task app container"]


def _port_is_available(port: int) -> bool:
    for host in ("127.0.0.1", "0.0.0.0"):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind((host, port))
            except OSError:
                return False
    return True


def _collect_reserved_ports(
    tasks_root: Path,
    repo_key: str,
    env_rel_path: str,
    current_env_path: Path,
    port_key: str,
) -> set[int]:
    reserved: set[int] = set()
    for env_path in tasks_root.glob(f"*/{repo_key}__*/{env_rel_path}"):
        if env_path == current_env_path:
            continue
        env_data = _parse_env_file(env_path)
        port_str = env_data.get(port_key)
        if not port_str:
            continue
        try:
            reserved.add(int(port_str))
        except ValueError:
            continue
    return reserved


def _pick_task_port(
    tasks_root: Path,
    repo_key: str,
    env_path: Path,
    env_rel_path: str,
    port_key: str,
    start: int,
    end: int,
) -> int:
    existing_port = _parse_env_file(env_path).get(port_key)
    if existing_port:
        try:
            return int(existing_port)
        except ValueError:
            pass

    reserved = _collect_reserved_ports(tasks_root, repo_key, env_rel_path, env_path, port_key)
    for port in range(start, end + 1):
        if port in reserved:
            continue
        if _port_is_available(port):
            return port
    raise RuntimeError(f"no available app host port in range {start}-{end} for repo {repo_key}")


def _render_env_file(values: dict[str, str | int]) -> str:
    lines: list[str] = []
    for key, value in values.items():
        lines.append(f"{key}={value}")
    lines.append("")
    return "\n".join(lines)


def _render_shared_backend_task_env(compose_project_name: str, app_host_port: int) -> str:
    return _render_env_file(
        {
            "COMPOSE_PROJECT_NAME": compose_project_name,
            "TASK_APP_HOST_PORT": app_host_port,
        }
    )


def _docker_image_exists(image_ref: str) -> bool:
    result = subprocess.run(
        ["docker", "image", "inspect", image_ref],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def inspect_container_mount_source(container_name: str, mount_destination: str) -> str | None:
    result = subprocess.run(
        ["docker", "inspect", container_name, "--format", "{{json .Mounts}}"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    try:
        mounts = json.loads(result.stdout.strip() or "[]")
    except json.JSONDecodeError as exc:
        raise ValueError(f"failed to parse docker inspect mounts for {container_name}") from exc
    if not isinstance(mounts, list):
        raise ValueError(f"invalid docker inspect mounts for {container_name}")
    for mount in mounts:
        if not isinstance(mount, dict):
            continue
        if mount.get("Destination") == mount_destination:
            source = mount.get("Source")
            return str(source) if source else None
    return None


def _resolve_mysql_data_switch_config(repo_cfg: dict[str, Any]) -> dict[str, str]:
    runtime_cfg = repo_cfg.get("runtime") or {}
    if not isinstance(runtime_cfg, dict):
        raise ValueError(f"runtime config for repo {repo_cfg.get('key')} must be a mapping")

    raw_cfg = runtime_cfg.get("mysql_data_switch")
    if not isinstance(raw_cfg, dict):
        raise ValueError(f"repo {repo_cfg.get('key')} has no mysql_data_switch config")

    compose_dir_text = str(raw_cfg.get("compose_dir") or "").strip()
    if not compose_dir_text:
        raise ValueError(f"repo {repo_cfg.get('key')} mysql_data_switch requires compose_dir")

    compose_dir = Path(compose_dir_text)
    data_dir_text = str(raw_cfg.get("data_dir") or "").strip()
    data_dir = Path(data_dir_text) if data_dir_text else compose_dir / "data/mysql"
    container_name = str(raw_cfg.get("container_name") or "pf-mysql-1")
    mount_destination = str(raw_cfg.get("mount_destination") or "/var/lib/mysql")
    service = str(raw_cfg.get("service") or "mysql")

    return {
        "compose_dir": str(compose_dir),
        "data_dir": str(data_dir),
        "container_name": container_name,
        "mount_destination": mount_destination,
        "service": service,
    }


def switch_mysql_data_dir(repo_cfg: dict[str, Any], dry_run: bool) -> dict[str, str | None]:
    cfg = _resolve_mysql_data_switch_config(repo_cfg)
    current_data_dir = inspect_container_mount_source(cfg["container_name"], cfg["mount_destination"])
    target_data_dir = cfg["data_dir"]

    if current_data_dir == target_data_dir:
        return {
            "repo_key": str(repo_cfg.get("key") or ""),
            "status": "already",
            "container_name": cfg["container_name"],
            "previous_data_dir": current_data_dir,
            "target_data_dir": target_data_dir,
            "command": None,
        }

    command = ["docker", "compose", "up", "-d"]
    if current_data_dir:
        command.append("--force-recreate")
    command.append(cfg["service"])
    print("$", " ".join(command), f"(cwd={cfg['compose_dir']})")
    if not dry_run:
        subprocess.run(command, check=True, text=True, cwd=cfg["compose_dir"])

    return {
        "repo_key": str(repo_cfg.get("key") or ""),
        "status": "switched" if current_data_dir else "started",
        "container_name": cfg["container_name"],
        "previous_data_dir": current_data_dir,
        "target_data_dir": target_data_dir,
        "command": " ".join(command),
    }


def _render_shared_backend_compose(front_network: str, back_network: str, app_image: str | None) -> str:
    lines = [
        "services:",
        "  app:",
    ]
    if app_image:
        lines.append(f"    image: {app_image}")
    else:
        lines.extend(
            [
                "    platform: linux/amd64",
                "    build: ./conf/app",
            ]
        )
    lines.extend(
        [
            "    stdin_open: true",
            "    tty: true",
            "    ports:",
            "      - \"${TASK_APP_HOST_PORT}:8897\"",
            "    volumes:",
            "      - ../:/usr/src/pf.senguo.cc:rw",
            "    working_dir: /usr/src/pf.senguo.cc/pfsource",
            "    networks:",
            "      - front-tier",
            "      - back-tier",
            "    command: python ./app.py --debug=1",
            "",
            "networks:",
            "  front-tier:",
            "    external: true",
            f"    name: {front_network}",
            "  back-tier:",
            "    external: true",
            f"    name: {back_network}",
            "",
        ]
    )
    return "\n".join(lines)


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"invalid json root in {path}")
    return data


def _shell_escape_double_quotes(text: str) -> str:
    return text.replace("\\", "\\\\").replace("\"", "\\\"")


def _resolve_node_version(repo_path: Path, package_json: dict[str, Any]) -> str | None:
    nvmrc_path = repo_path / ".nvmrc"
    if nvmrc_path.exists():
        version = nvmrc_path.read_text(encoding="utf-8").strip()
        if version:
            return version

    volta = package_json.get("volta")
    if isinstance(volta, dict):
        node_version = volta.get("node")
        if isinstance(node_version, str) and node_version.strip():
            return node_version.strip()

    return None


def _node_platform_optional_dependency_check() -> str:
    return (
        "node -e '"
        "const fs=require(\"fs\");"
        "if(!fs.existsSync(\"package-lock.json\"))process.exit(0);"
        "const packages=JSON.parse(fs.readFileSync(\"package-lock.json\",\"utf8\")).packages||{};"
        "const supports=(values,current)=>!Array.isArray(values)||(!values.includes(\"!\"+current)&&(values.filter(value=>!value.startsWith(\"!\")).length===0||values.includes(current)));"
        "const missing=Object.entries(packages).some(([path,pkg])=>path.startsWith(\"node_modules/\")&&pkg&&pkg.optional&&(Array.isArray(pkg.os)||Array.isArray(pkg.cpu))&&supports(pkg.os,process.platform)&&supports(pkg.cpu,process.arch)&&!fs.existsSync(path));"
        "process.exit(missing?1:0);'"
    )


def _node_frontend_prefix_parts(node_version: str | None) -> list[str]:
    if not node_version:
        return []
    escaped_node_version = _shell_escape_double_quotes(node_version)
    return [
        'eval "$(fnm env --shell zsh)"',
        f'fnm use --install-if-missing {escaped_node_version} >/dev/null',
    ]


def _node_platform_tag(repo_path: Path, node_version: str | None) -> tuple[str, str]:
    command = " && ".join(_node_frontend_prefix_parts(node_version) + ['node -p "process.platform + \'-\' + process.arch"'])
    result = subprocess.run(
        ["zsh", "-lc", command],
        check=True,
        capture_output=True,
        text=True,
        cwd=str(repo_path),
    )
    platform_arch = result.stdout.strip()
    if "-" not in platform_arch:
        raise ValueError(f"unexpected node platform tag: {platform_arch}")
    platform, architecture = platform_arch.split("-", 1)
    return platform, architecture


def _node_optional_dependency_supports(values: Any, current: str) -> bool:
    if not isinstance(values, list):
        return True
    normalized = [str(value) for value in values]
    if f"!{current}" in normalized:
        return False
    allowed = [value for value in normalized if not value.startswith("!")]
    return not allowed or current in allowed


def _missing_node_platform_optional_dependencies(repo_path: Path, platform: str, architecture: str) -> list[str]:
    lock_path = repo_path / "package-lock.json"
    node_modules_path = repo_path / "node_modules"
    if not lock_path.exists() or not node_modules_path.is_dir():
        return []

    packages = _load_json(lock_path).get("packages") or {}
    if not isinstance(packages, dict):
        return []

    missing: list[str] = []
    for rel_path, package in packages.items():
        if not isinstance(rel_path, str) or not rel_path.startswith("node_modules/"):
            continue
        if not isinstance(package, dict) or not package.get("optional"):
            continue
        if not (isinstance(package.get("os"), list) or isinstance(package.get("cpu"), list)):
            continue
        if not _node_optional_dependency_supports(package.get("os"), platform):
            continue
        if not _node_optional_dependency_supports(package.get("cpu"), architecture):
            continue
        if not (repo_path / rel_path).exists():
            missing.append(rel_path)
    return missing


def resolve_node_version_for_repo(repo_path: Path) -> str | None:
    package_json_path = repo_path / "package.json"
    if not package_json_path.exists():
        return None
    return _resolve_node_version(repo_path, _load_json(package_json_path))


def _render_node_frontend_environment(
    environment_name: str,
    node_version: str | None,
    install_command: str,
    start_command: str,
    native_optional_repair_command: str | None = None,
) -> str:
    prefix_parts = _node_frontend_prefix_parts(node_version)
    platform_optional_dependency_check = _node_platform_optional_dependency_check()
    repair_command = native_optional_repair_command or "npm ci --include=optional"
    install_guard = (
        f"if [ ! -d node_modules ]; then {install_command}; "
        f"elif ! {platform_optional_dependency_check}; then {repair_command}; fi"
    )
    setup_command = " && ".join(prefix_parts + [install_guard]) if prefix_parts else install_guard
    start_with_guard = " && ".join(prefix_parts + [install_guard, start_command]) if prefix_parts else f"{install_guard} && {start_command}"

    return "\n".join(
        [
            "# THIS IS AUTOGENERATED. DO NOT EDIT MANUALLY",
            "version = 1",
            f'name = "{_shell_escape_double_quotes(environment_name)}"',
            "",
            "[setup]",
            f'script = "{_shell_escape_double_quotes(setup_command)}"',
            "",
            "[[actions]]",
            'name = "启动"',
            'icon = "run"',
            f'command = "{_shell_escape_double_quotes(start_with_guard)}"',
            "",
        ]
    )


def _ensure_node_frontend_native_optional_dependencies(
    runtime_cfg: dict[str, Any],
    repo_path: Path,
    node_version: str | None,
    dry_run: bool,
) -> dict[str, list[str]]:
    if runtime_cfg.get("repair_native_optional_dependencies") is False:
        return {"notes": [], "warnings": []}
    if not (repo_path / "node_modules").is_dir() or not (repo_path / "package-lock.json").exists():
        return {"notes": [], "warnings": []}

    try:
        platform, architecture = _node_platform_tag(repo_path, node_version)
    except (subprocess.CalledProcessError, ValueError) as exc:
        return {"notes": [], "warnings": [f"无法确认 Node 平台，跳过前端原生 optional 依赖修复：{exc}"]}

    missing = _missing_node_platform_optional_dependencies(repo_path, platform, architecture)
    if not missing:
        return {"notes": [], "warnings": []}

    repair_command = str(runtime_cfg.get("native_optional_repair_command") or "npm ci --include=optional")
    command = " && ".join(_node_frontend_prefix_parts(node_version) + [repair_command])
    run_shell(command, dry_run, repo_path)

    notes = [
        f"检测到当前 Node 平台 {platform}-{architecture} 缺失原生 optional 依赖，已按本地环境修复：{', '.join(missing)}"
    ]
    warnings: list[str] = []
    if not dry_run:
        still_missing = _missing_node_platform_optional_dependencies(repo_path, platform, architecture)
        if still_missing:
            warnings.append(f"前端原生 optional 依赖修复后仍缺失：{', '.join(still_missing)}")

        diff_result = subprocess.run(
            ["git", "-C", str(repo_path), "diff", "--name-only", "--", "package.json", "package-lock.json"],
            check=True,
            capture_output=True,
            text=True,
        )
        changed = [line for line in diff_result.stdout.splitlines() if line.strip()]
        if changed:
            warnings.append(
                "本地依赖修复后 package.json/package-lock.json 出现变更，必须视为异常处理，不要作为业务代码提交："
                + ", ".join(changed)
            )

    return {"notes": notes, "warnings": warnings}


def _rewrite_frontend_start_command(
    package_json: dict[str, Any],
    start_command: str,
    assigned_port: int | None,
) -> str:
    if assigned_port is None:
        return start_command

    match = re.fullmatch(r"\s*npm run ([^ ]+)\s*", start_command)
    if not match:
        return f"PORT={assigned_port} {start_command}"

    script_name = match.group(1)
    scripts = package_json.get("scripts")
    script_body = scripts.get(script_name) if isinstance(scripts, dict) else None
    if not isinstance(script_body, str):
        return f"PORT={assigned_port} {start_command}"

    if "vite" in script_body:
        return f"{start_command} -- --port {assigned_port} --strictPort"

    return f"PORT={assigned_port} {start_command}"


def _prepare_node_frontend_runtime(
    repo_cfg: dict[str, Any],
    runtime_cfg: dict[str, Any],
    repo_path: Path,
    dry_run: bool,
) -> dict[str, Any]:
    env_rel_path = str(runtime_cfg.get("task_env_file", ".codex/task-runtime.env"))
    port_key = str(runtime_cfg.get("task_port_key", "TASK_WEB_PORT"))
    port_start_value = runtime_cfg.get("app_port_start")
    port_end_value = runtime_cfg.get("app_port_end")
    if port_start_value is None or port_end_value is None:
        return {"generated_files": [], "notes": [], "warnings": [], "assigned_port": None}

    task_root = repo_path.parent
    tasks_root = task_root.parent
    repo_key = str(repo_cfg["key"])
    env_path = repo_path / env_rel_path
    assigned_port = _pick_task_port(
        tasks_root,
        repo_key,
        env_path,
        env_rel_path,
        port_key,
        int(port_start_value),
        int(port_end_value),
    )
    write_text(env_path, _render_env_file({port_key: assigned_port}), dry_run)
    return {
        "generated_files": [env_rel_path],
        "notes": [f"任务前端固定端口：{assigned_port}"],
        "warnings": [],
        "assigned_port": assigned_port,
    }


def _rewrite_node_frontend_environment(
    repo_cfg: dict[str, Any],
    runtime_cfg: dict[str, Any],
    repo_path: Path,
    assigned_port: int | None,
    dry_run: bool,
) -> dict[str, list[str]]:
    package_json_path = repo_path / "package.json"
    if not package_json_path.exists():
        source_package_json_path = Path(str(repo_cfg.get("path") or "")) / "package.json"
        if dry_run and source_package_json_path.exists():
            package_json_path = source_package_json_path
        else:
            raise ValueError(f"missing package.json for repo {repo_cfg.get('key')}: {repo_path}")

    package_json = _load_json(package_json_path)
    install_commands = _as_string_list(runtime_cfg.get("install_commands"))
    start_commands = _as_string_list(runtime_cfg.get("start_commands"))
    if not install_commands or not start_commands:
        raise ValueError(f"node frontend runtime requires install_commands and start_commands: {repo_cfg.get('key')}")

    node_version = _resolve_node_version(package_json_path.parent, package_json)
    environment_name = str(package_json.get("name") or repo_cfg["key"])
    environment_rel_path = str(runtime_cfg.get("environment_toml", ".codex/environments/environment.toml"))
    environment_path = repo_path / environment_rel_path

    effective_start_command = _rewrite_frontend_start_command(package_json, start_commands[0], assigned_port)
    native_optional_repair_command = str(runtime_cfg.get("native_optional_repair_command") or "npm ci --include=optional")

    write_text(
        environment_path,
        _render_node_frontend_environment(
            environment_name,
            node_version,
            install_commands[0],
            effective_start_command,
            native_optional_repair_command,
        ),
        dry_run,
    )

    notes: list[str] = []
    if node_version:
        notes.append(f"Codex 启动前会切换 Node.js {node_version}")
    notes.append("Codex 启动动作会在缺失 node_modules 时安装依赖；当前平台原生 optional 依赖缺失时按本地环境修复")
    if assigned_port is not None:
        notes.append(f"Codex 启动动作会固定使用端口 {assigned_port}；端口冲突时直接失败，不再自动跳号")

    return {
        "generated_files": [environment_rel_path],
        "notes": notes,
    }


def _patch_local_producer_proxy_target(
    runtime_cfg: dict[str, Any],
    repo_path: Path,
    dry_run: bool,
) -> dict[str, list[str]]:
    task_root = repo_path.parent
    backend_repo_key = str(runtime_cfg.get("local_backend_repo_key", "producer-backend"))
    backend_repo_path = _find_task_repo_path(task_root, backend_repo_key)
    if backend_repo_path is None:
        return {
            "generated_files": [],
            "notes": [f"未找到同任务后端仓库 {backend_repo_key}，跳过 vite.proxy.config.mjs 端口修正"],
        }

    backend_env_rel = str(runtime_cfg.get("backend_task_env_file", "docker/.task.env"))
    backend_env = _parse_env_file(backend_repo_path / backend_env_rel)
    port = backend_env.get("TASK_APP_HOST_PORT")
    if not port:
        return {
            "generated_files": [],
            "notes": [f"未找到后端任务端口配置 {backend_env_rel}，跳过 vite.proxy.config.mjs 端口修正"],
        }

    proxy_rel_path = str(runtime_cfg.get("producer_proxy_config_file", "vite.proxy.config.mjs"))
    proxy_path = repo_path / proxy_rel_path
    if not proxy_path.exists():
        return {
            "generated_files": [],
            "notes": [f"未找到 {proxy_rel_path}，跳过本地产地代理端口修正"],
        }

    text = proxy_path.read_text(encoding="utf-8")
    updated = re.sub(
        r"(const\s+LOCAL_PRODUCER_PROXY_TARGET_ADDRESS\s*=\s*['\"]http://[^:'\"]+:)(\d+)(['\"])",
        rf"\g<1>{port}\g<3>",
        text,
        count=1,
    )
    if updated == text:
        return {
            "generated_files": [],
            "notes": [f"{proxy_rel_path} 中未匹配到 LOCAL_PRODUCER_PROXY_TARGET_ADDRESS，跳过端口修正"],
        }

    write_text(proxy_path, updated, dry_run)
    return {
        "generated_files": [proxy_rel_path],
        "notes": [f"{proxy_rel_path} 已对齐本地后端端口：{port}"],
    }


def _resolve_local_backend_port(
    runtime_cfg: dict[str, Any],
    repo_path: Path,
    target_rel_path: str,
) -> tuple[str | None, list[str]]:
    task_root = repo_path.parent
    backend_repo_key = str(runtime_cfg.get("local_backend_repo_key", "producer-backend"))
    backend_repo_path = _find_task_repo_path(task_root, backend_repo_key)
    if backend_repo_path is None:
        return None, [f"未找到同任务后端仓库 {backend_repo_key}，跳过 {target_rel_path} 本地后端修正"]

    backend_env_rel = str(runtime_cfg.get("backend_task_env_file", "docker/.task.env"))
    backend_env = _parse_env_file(backend_repo_path / backend_env_rel)
    port = backend_env.get("TASK_APP_HOST_PORT")
    if not port:
        return None, [f"未找到后端任务端口配置 {backend_env_rel}，跳过 {target_rel_path} 本地后端修正"]
    return port, []


def _patch_frontend_local_backend_env(
    runtime_cfg: dict[str, Any],
    repo_path: Path,
    dry_run: bool,
) -> dict[str, list[str]]:
    env_rel_path = str(runtime_cfg.get("local_backend_env_file") or "").strip()
    if not env_rel_path:
        return {"generated_files": [], "notes": []}

    port, notes = _resolve_local_backend_port(runtime_cfg, repo_path, env_rel_path)
    if not port:
        return {"generated_files": [], "notes": notes}

    env_path = repo_path / env_rel_path
    if not env_path.exists():
        return {
            "generated_files": [],
            "notes": [f"未找到 {env_rel_path}，跳过本地后端修正"],
        }

    proxy_host = str(runtime_cfg.get("local_backend_proxy_host", "localhost"))
    api_host = str(runtime_cfg.get("local_backend_api_host", "pfzone.senguo.cc"))
    proxy_target = f"http://{proxy_host}:{port}"
    api_target = f"http://{api_host}:{port}"

    text = env_path.read_text(encoding="utf-8")
    updated = re.sub(
        r'(^VITE_DEV_PROXY_TARGET\s*=\s*")[^"]*(".*$)',
        rf'\g<1>{proxy_target}\g<2>',
        text,
        count=1,
        flags=re.MULTILINE,
    )
    updated = re.sub(
        r'(^VITE_PF_API_URL\s*=\s*")[^"]*(".*$)',
        rf'\g<1>{api_target}\g<2>',
        updated,
        count=1,
        flags=re.MULTILINE,
    )
    if updated == text:
        return {
            "generated_files": [],
            "notes": [f"{env_rel_path} 中未匹配到本地后端相关字段，跳过修正"],
        }

    write_text(env_path, updated, dry_run)
    return {
        "generated_files": [env_rel_path],
        "notes": [f"{env_rel_path} 已对齐本地后端地址：{proxy_target} / {api_target}"],
    }


def _patch_frontend_local_backend_json(
    runtime_cfg: dict[str, Any],
    repo_path: Path,
    dry_run: bool,
) -> dict[str, list[str]]:
    json_rel_path = str(runtime_cfg.get("local_backend_json_file") or "").strip()
    if not json_rel_path:
        return {"generated_files": [], "notes": []}

    port, notes = _resolve_local_backend_port(runtime_cfg, repo_path, json_rel_path)
    if not port:
        return {"generated_files": [], "notes": notes}

    json_path = repo_path / json_rel_path
    if not json_path.exists():
        return {
            "generated_files": [],
            "notes": [f"未找到 {json_rel_path}，跳过本地后端修正"],
        }

    target_fields = _as_string_list(runtime_cfg.get("local_backend_json_fields")) or ["PROXY_TARGET_ADDRESS"]
    proxy_host = str(runtime_cfg.get("local_backend_proxy_host", "localhost"))
    proxy_target = f"http://{proxy_host}:{port}"

    data = _load_json(json_path)
    updated = False
    for field in target_fields:
        if field in data and data[field] != proxy_target:
            data[field] = proxy_target
            updated = True

    if not updated:
        return {
            "generated_files": [],
            "notes": [f"{json_rel_path} 中未匹配到本地后端相关字段，跳过修正"],
        }

    write_text(json_path, json.dumps(data, ensure_ascii=False, indent="\t") + "\n", dry_run)
    return {
        "generated_files": [json_rel_path],
        "notes": [f"{json_rel_path} 已对齐本地后端地址：{proxy_target}"],
    }


def _patch_frontend_local_backend_proxy_js(
    runtime_cfg: dict[str, Any],
    repo_path: Path,
    dry_run: bool,
) -> dict[str, list[str]]:
    proxy_rel_path = str(runtime_cfg.get("local_backend_proxy_js_file") or "").strip()
    if not proxy_rel_path:
        return {"generated_files": [], "notes": []}

    port, notes = _resolve_local_backend_port(runtime_cfg, repo_path, proxy_rel_path)
    if not port:
        return {"generated_files": [], "notes": notes}

    proxy_path = repo_path / proxy_rel_path
    if not proxy_path.exists():
        return {
            "generated_files": [],
            "notes": [f"未找到 {proxy_rel_path}，跳过本地后端修正"],
        }

    proxy_host = str(runtime_cfg.get("local_backend_proxy_host", "localhost"))
    proxy_target = f"http://{proxy_host}:{port}"
    ws_target = f"ws://{proxy_host}:{port}"
    http_constants = _as_string_list(runtime_cfg.get("local_backend_proxy_js_http_constants")) or ["PROXY_TARGET_ADDRESS"]
    ws_constants = _as_string_list(runtime_cfg.get("local_backend_proxy_js_ws_constants"))

    text = proxy_path.read_text(encoding="utf-8")
    updated = text
    changed_constants: list[str] = []
    for constant in http_constants:
        pattern = rf"(const\s+{re.escape(constant)}\s*=\s*['\"])[^'\"]*(['\"])"
        next_updated = re.sub(pattern, rf"\g<1>{proxy_target}\g<2>", updated, count=1)
        if next_updated != updated:
            changed_constants.append(constant)
            updated = next_updated
    for constant in ws_constants:
        pattern = rf"(const\s+{re.escape(constant)}\s*=\s*['\"])[^'\"]*(['\"])"
        next_updated = re.sub(pattern, rf"\g<1>{ws_target}\g<2>", updated, count=1)
        if next_updated != updated:
            changed_constants.append(constant)
            updated = next_updated

    if updated == text:
        return {
            "generated_files": [],
            "notes": [f"{proxy_rel_path} 中未匹配到本地后端相关常量，跳过修正"],
        }

    write_text(proxy_path, updated, dry_run)
    constants_text = ", ".join(changed_constants)
    return {
        "generated_files": [proxy_rel_path],
        "notes": [f"{proxy_rel_path} 已对齐本地后端地址：{proxy_target} ({constants_text})"],
    }


def start_repo_runtime(repo_cfg: dict[str, Any], repo_path: Path, dry_run: bool) -> dict[str, list[str]]:
    runtime_cfg = repo_cfg.get("runtime") or {}
    if not isinstance(runtime_cfg, dict):
        raise ValueError(f"runtime config for repo {repo_cfg.get('key')} must be a mapping")
    if not bool(runtime_cfg.get("auto_start_on_prepare")):
        return {"executed": [], "warnings": []}

    executed: list[str] = []
    warnings: list[str] = []
    for step in _as_command_steps(runtime_cfg.get("auto_start_steps")):
        cwd_text = step.get("cwd", "")
        if cwd_text == "__TASK_REPO_DIR__":
            cwd = repo_path
        elif cwd_text == "__TASK_DOCKER_DIR__":
            cwd = repo_path / "docker"
        else:
            cwd = Path(cwd_text) if cwd_text else repo_path
        allow_failure = step.get("allow_failure") == "true"
        try:
            run_shell(step["command"], dry_run, cwd)
            executed.append(f"{step['command']} @ {cwd}")
        except subprocess.CalledProcessError as exc:
            if not allow_failure:
                raise
            warnings.append(f"{step['command']} @ {cwd}: {exc}")
    if str(runtime_cfg.get("mode") or "").strip() == "shared-backend-app":
        summary = _ensure_shared_backend_test_tools(repo_cfg, runtime_cfg, repo_path, dry_run)
        executed.extend(summary["executed"])
        warnings.extend(summary["warnings"])
    return {"executed": executed, "warnings": warnings}


def _ensure_shared_backend_test_tools(
    repo_cfg: dict[str, Any],
    runtime_cfg: dict[str, Any],
    repo_path: Path,
    dry_run: bool,
) -> dict[str, list[str]]:
    if runtime_cfg.get("ensure_pytest") is False:
        return {"executed": [], "warnings": []}

    env_rel_path = str(runtime_cfg.get("task_env_file", "docker/.task.env"))
    compose_rel_path = str(runtime_cfg.get("task_compose_file", "docker/docker-compose.task.yml"))
    env_path = repo_path / env_rel_path
    compose_path = repo_path / compose_rel_path
    if not env_path.exists() or not compose_path.exists():
        return {
            "executed": [],
            "warnings": [f"{repo_cfg.get('key')}: task docker files missing, skip pytest check"],
        }

    docker_dir = compose_path.parent
    compose_name = compose_path.name
    env_name = env_path.name
    pytest_version = str(runtime_cfg.get("pytest_version") or "7.4.4")
    install_index = str(runtime_cfg.get("pip_index_url") or "https://mirrors.aliyun.com/pypi/simple/")
    command = (
        f"docker compose --env-file {env_name} -f {compose_name} exec -T app sh -lc "
        f"'python -m pytest --version >/dev/null 2>&1 || "
        f"python -m pip install -i {install_index} pytest=={pytest_version}'"
    )
    try:
        run_shell(command, dry_run, docker_dir)
        return {"executed": [f"{command} @ {docker_dir}"], "warnings": []}
    except subprocess.CalledProcessError as exc:
        return {
            "executed": [],
            "warnings": [f"{repo_cfg.get('key')}: pytest check/install failed: {exc}"],
        }


def stop_task_runtime(repo_cfg: dict[str, Any], repo_path: Path, dry_run: bool) -> list[str]:
    runtime_cfg = repo_cfg.get("runtime") or {}
    if not isinstance(runtime_cfg, dict):
        raise ValueError(f"runtime config for repo {repo_cfg.get('key')} must be a mapping")

    runtime_mode = str(runtime_cfg.get("mode") or "").strip()
    if runtime_mode == "patch-node-frontend-environment":
        return _stop_node_frontend_runtime(repo_cfg, repo_path, runtime_cfg, dry_run)
    if runtime_mode == "shared-backend-app":
        return _stop_shared_backend_runtime(repo_cfg, repo_path, runtime_cfg, dry_run)
    return [f"{repo_cfg.get('key')}: no managed runtime stop action"]


def _prepare_shared_backend_runtime(
    repo_cfg: dict[str, Any],
    runtime_cfg: dict[str, Any],
    repo_path: Path,
    task_id: str,
    dry_run: bool,
) -> dict[str, list[str]]:
    repo_key = str(repo_cfg["key"])
    tasks_root = repo_path.parents[1]
    env_rel_path = str(runtime_cfg.get("task_env_file", "docker/.task.env"))
    compose_rel_path = str(runtime_cfg.get("task_compose_file", "docker/docker-compose.task.yml"))
    front_network = str(runtime_cfg.get("shared_front_network", "pf_front-tier"))
    back_network = str(runtime_cfg.get("shared_back_network", "pf_back-tier"))
    port_start = int(runtime_cfg.get("app_port_start", 18897))
    port_end = int(runtime_cfg.get("app_port_end", 18996))
    task_app_image = str(runtime_cfg.get("task_app_image") or "").strip()

    env_path = repo_path / env_rel_path
    compose_path = repo_path / compose_rel_path
    app_host_port = _pick_task_port(
        tasks_root,
        repo_key,
        env_path,
        env_rel_path,
        "TASK_APP_HOST_PORT",
        port_start,
        port_end,
    )
    compose_project_name = build_task_compose_name(task_id, repo_key)
    resolved_app_image = task_app_image if task_app_image and _docker_image_exists(task_app_image) else None

    generated_files = [env_rel_path, compose_rel_path]
    write_text(env_path, _render_shared_backend_task_env(compose_project_name, app_host_port), dry_run)
    write_text(compose_path, _render_shared_backend_compose(front_network, back_network, resolved_app_image), dry_run)
    _ensure_local_git_excludes(repo_path, generated_files, dry_run)

    warnings: list[str] = []
    notes = [
        f"任务 app 宿主机端口：{app_host_port}",
        f"使用共享 Docker 网络：{front_network}, {back_network}",
    ]
    if resolved_app_image:
        notes.append(f"任务 app 复用主仓本地镜像：{resolved_app_image}")
    elif task_app_image:
        warnings.append(f"未找到本地镜像 {task_app_image}，任务 app 将回退为当前任务仓库自行构建")

    return {
        "generated_files": generated_files,
        "notes": notes,
        "warnings": warnings,
    }


def prepare_repo_runtime(repo_cfg: dict[str, Any], repo_path: Path, dry_run: bool) -> dict[str, Any]:
    task_id = repo_path.parent.name
    runtime_cfg = repo_cfg.get("runtime") or {}
    if not isinstance(runtime_cfg, dict):
        raise ValueError(f"runtime config for repo {repo_cfg.get('key')} must be a mapping")

    source_repo = Path(str(repo_cfg["path"]))
    copied_from_main: list[str] = []
    copied_from_template: list[str] = []
    warnings: list[str] = []
    prepared_targets: set[Path] = set()

    for rel_path in _as_string_list(runtime_cfg.get("copy_missing_from_main")):
        target = repo_path / rel_path
        if not should_prepare_local_file(target, prepared_targets):
            continue
        source = source_repo / rel_path
        if not source.exists():
            warnings.append(f"missing main repo file: {rel_path}")
            continue
        copy_file(source, target, dry_run)
        copied_from_main.append(rel_path)
        prepared_targets.add(target)

    for item in _as_mapping_list(runtime_cfg.get("copy_missing_from_template")):
        source_rel = item.get("source")
        target_rel = item.get("target")
        if not source_rel or not target_rel:
            raise ValueError("runtime template copy items require source and target")
        target = repo_path / target_rel
        if not should_prepare_local_file(target, prepared_targets):
            continue
        source = repo_path / source_rel
        if not source.exists():
            warnings.append(f"missing template file in task repo: {source_rel}")
            continue
        copy_file(source, target, dry_run)
        copied_from_template.append(f"{source_rel} -> {target_rel}")
        prepared_targets.add(target)

    generated_files: list[str] = []
    generated_notes: list[str] = []
    runtime_mode = str(runtime_cfg.get("mode") or "").strip()
    if runtime_mode == "shared-backend-app":
        generated = _prepare_shared_backend_runtime(repo_cfg, runtime_cfg, repo_path, task_id, dry_run)
        generated_files.extend(generated["generated_files"])
        generated_notes.extend(generated["notes"])
        warnings.extend(generated.get("warnings", []))
    elif runtime_mode == "patch-node-frontend-environment":
        frontend_runtime = _prepare_node_frontend_runtime(repo_cfg, runtime_cfg, repo_path, dry_run)
        generated_files.extend(frontend_runtime["generated_files"])
        generated_notes.extend(frontend_runtime["notes"])
        warnings.extend(frontend_runtime.get("warnings", []))

        node_version = resolve_node_version_for_repo(repo_path)
        native_repair = _ensure_node_frontend_native_optional_dependencies(runtime_cfg, repo_path, node_version, dry_run)
        generated_notes.extend(native_repair["notes"])
        warnings.extend(native_repair["warnings"])

        generated = _rewrite_node_frontend_environment(
            repo_cfg,
            runtime_cfg,
            repo_path,
            frontend_runtime.get("assigned_port"),
            dry_run,
        )
        generated_files.extend(generated["generated_files"])
        generated_notes.extend(generated["notes"])
        if runtime_cfg.get("producer_proxy_config_file"):
            proxy_patch = _patch_local_producer_proxy_target(runtime_cfg, repo_path, dry_run)
            generated_files.extend(proxy_patch["generated_files"])
            generated_notes.extend(proxy_patch["notes"])
        env_patch = _patch_frontend_local_backend_env(runtime_cfg, repo_path, dry_run)
        generated_files.extend(env_patch["generated_files"])
        generated_notes.extend(env_patch["notes"])
        json_patch = _patch_frontend_local_backend_json(runtime_cfg, repo_path, dry_run)
        generated_files.extend(json_patch["generated_files"])
        generated_notes.extend(json_patch["notes"])
        proxy_js_patch = _patch_frontend_local_backend_proxy_js(runtime_cfg, repo_path, dry_run)
        generated_files.extend(proxy_js_patch["generated_files"])
        generated_notes.extend(proxy_js_patch["notes"])

    return {
        "copied_from_main": copied_from_main,
        "copied_from_template": copied_from_template,
        "generated_files": generated_files,
        "install_commands": _as_string_list(runtime_cfg.get("install_commands")),
        "start_commands": _as_string_list(runtime_cfg.get("start_commands")),
        "notes": _as_string_list(runtime_cfg.get("notes")) + generated_notes,
        "warnings": warnings,
    }


def validate_repo_state(repo_path: Path, require_remote_sync: bool, expected_branch: str | None = None) -> list[str]:
    issues: list[str] = []
    if not repo_path.exists():
        issues.append("repo path is missing")
        return issues
    git_dir = repo_path / ".git"
    if not git_dir.exists():
        issues.append("repo path is not a git repository")
        return issues

    status = run_git(repo_path, "status", "--short")
    if status:
        issues.append("has uncommitted changes")

    branch = run_git(repo_path, "branch", "--show-current")
    if not branch:
        issues.append("is not on a local branch")
        return issues

    if expected_branch and branch != expected_branch:
        issues.append(f"current branch is {branch}, expected {expected_branch}")

    try:
        upstream = run_git(repo_path, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    except subprocess.CalledProcessError:
        if require_remote_sync:
            issues.append("has no upstream branch")
        return issues

    if require_remote_sync:
        counts = run_git(repo_path, "rev-list", "--left-right", "--count", f"{upstream}...HEAD")
        _behind_str, ahead_str = counts.split()
        ahead = int(ahead_str)
        if ahead > 0:
            issues.append(f"has {ahead} local commit(s) not pushed to {upstream}")

    return issues


def read_current_branch(repo_path: Path) -> str:
    if not repo_path.exists():
        return "missing"
    if not (repo_path / ".git").exists():
        return "not-a-git-repo"
    branch = run_git(repo_path, "branch", "--show-current")
    return branch or "detached"


def read_status_short(repo_path: Path) -> str:
    if not repo_path.exists() or not (repo_path / ".git").exists():
        return ""
    return run_git(repo_path, "status", "--short")


def resolve_origin_default_branch(repo_path: Path) -> str:
    try:
        ref = run_git(repo_path, "symbolic-ref", "refs/remotes/origin/HEAD")
        if ref.startswith("refs/remotes/origin/"):
            return ref.removeprefix("refs/remotes/origin/")
    except subprocess.CalledProcessError:
        pass

    for candidate in ("master", "main"):
        try:
            run_git(repo_path, "rev-parse", "--verify", f"origin/{candidate}")
            return candidate
        except subprocess.CalledProcessError:
            continue

    raise ValueError(f"cannot determine origin default branch for repo: {repo_path}")


def update_index_status(index_path: Path, new_status: str, dry_run: bool) -> None:
    if not index_path.exists():
        return
    text = index_path.read_text(encoding="utf-8")
    updated = re.sub(r"^- 当前状态：.*$", f"- 当前状态：{new_status}", text, flags=re.MULTILINE)
    if updated == text:
        return
    print(f"update index status: {index_path} -> {new_status}")
    if not dry_run:
        index_path.write_text(updated, encoding="utf-8")


def load_task_meta(docs_root: Path, task_id: str) -> tuple[Path, dict[str, Any]]:
    meta_path = docs_root / task_id / "meta.yaml"
    meta = load_yaml(meta_path)
    return meta_path, meta
