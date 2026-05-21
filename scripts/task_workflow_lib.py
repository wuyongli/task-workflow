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


def build_task_compose_name(task_id: str) -> str:
    date_part, raw_task_name = _extract_task_parts(task_id)
    pinyin_parts = lazy_pinyin(raw_task_name, errors="ignore")
    task_pinyin = "".join(part.lower() for part in pinyin_parts if part.strip())
    if not task_pinyin:
        task_pinyin = "task"
    return sanitize_compose_name(f"{date_part}-{task_pinyin}")


def build_repo_dir_name(repo_key: str, raw_task_name: str) -> str:
    return f"{repo_key}__{raw_task_name}"


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


def _render_node_frontend_environment(
    environment_name: str,
    node_version: str | None,
    install_command: str,
    start_command: str,
) -> str:
    prefix_parts: list[str] = []
    if node_version:
        escaped_node_version = _shell_escape_double_quotes(node_version)
        prefix_parts.append('eval "$(fnm env --shell zsh)"')
        prefix_parts.append(f'fnm use --install-if-missing {escaped_node_version} >/dev/null')

    install_guard = f'if [ ! -d node_modules ]; then {install_command}; fi'
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
        raise ValueError(f"missing package.json for repo {repo_cfg.get('key')}: {repo_path}")

    package_json = _load_json(package_json_path)
    install_commands = _as_string_list(runtime_cfg.get("install_commands"))
    start_commands = _as_string_list(runtime_cfg.get("start_commands"))
    if not install_commands or not start_commands:
        raise ValueError(f"node frontend runtime requires install_commands and start_commands: {repo_cfg.get('key')}")

    node_version = _resolve_node_version(repo_path, package_json)
    environment_name = str(package_json.get("name") or repo_cfg["key"])
    environment_rel_path = str(runtime_cfg.get("environment_toml", ".codex/environments/environment.toml"))
    environment_path = repo_path / environment_rel_path

    if not environment_path.exists():
        return {
            "generated_files": [],
            "notes": [f"未找到 {environment_rel_path}，跳过任务仓库启动文件修正"],
        }

    effective_start_command = _rewrite_frontend_start_command(package_json, start_commands[0], assigned_port)

    write_text(
        environment_path,
        _render_node_frontend_environment(environment_name, node_version, install_commands[0], effective_start_command),
        dry_run,
    )

    notes: list[str] = []
    if node_version:
        notes.append(f"Codex 启动前会切换 Node.js {node_version}")
    notes.append("Codex 启动动作会在缺失 node_modules 时自动执行依赖安装")
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
    return {"executed": executed, "warnings": warnings}


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
    compose_project_name = build_task_compose_name(task_id)
    resolved_app_image = task_app_image if task_app_image and _docker_image_exists(task_app_image) else None

    write_text(env_path, _render_shared_backend_task_env(compose_project_name, app_host_port), dry_run)
    write_text(compose_path, _render_shared_backend_compose(front_network, back_network, resolved_app_image), dry_run)

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
        "generated_files": [env_rel_path, compose_rel_path],
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
        if target.exists() or target in prepared_targets:
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
        if target.exists() or target in prepared_targets:
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

        generated = _rewrite_node_frontend_environment(
            repo_cfg,
            runtime_cfg,
            repo_path,
            frontend_runtime.get("assigned_port"),
            dry_run,
        )
        generated_files.extend(generated["generated_files"])
        generated_notes.extend(generated["notes"])
        proxy_patch = _patch_local_producer_proxy_target(runtime_cfg, repo_path, dry_run)
        generated_files.extend(proxy_patch["generated_files"])
        generated_notes.extend(proxy_patch["notes"])

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
