#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

DEFAULT_LABEL = "com.senguo.task-dev-portal"
DEFAULT_INSTALL_DIR = "~/.task-workflow/portal"
DEFAULT_CONFIG_ROOT = Path("/Users/wuyongli/Documents/sg-project/_workspace/config")
DEFAULT_PLIST_PATH = "~/Library/LaunchAgents/com.senguo.task-dev-portal.plist"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765

COPY_SCRIPTS = (
    "serve_task_dev_portal.py",
    "render_task_dev_portal.py",
    "task_workflow_lib.py",
)


def write_file(path: Path, content: str, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if mode is not None:
        path.chmod(mode)


def resolve_python() -> str:
    found = shutil.which("python3")
    if found:
        return found
    return "/usr/bin/python3"


def render_wrapper(
    install_dir: Path,
    config_root: Path,
    host: str,
    port: int,
    python_path: str,
) -> str:
    server_script = install_dir / "serve_task_dev_portal.py"
    return f"""#!/usr/bin/env bash
set -euo pipefail
exec "{python_path}" "{server_script}" \\
  --config-root "{config_root}" \\
  --host "{host}" \\
  --port {port}
"""


def render_plist(
    label: str,
    wrapper_path: Path,
    stdout_path: Path,
    stderr_path: Path,
    throttle_interval: int,
) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <dict>
    <key>Label</key>
    <string>{label}</string>

    <key>ProgramArguments</key>
    <array>
      <string>{wrapper_path}</string>
    </array>

    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>ThrottleInterval</key>
    <integer>{throttle_interval}</integer>

    <key>EnvironmentVariables</key>
    <dict>
      <key>PATH</key>
      <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>

    <key>StandardOutPath</key>
    <string>{stdout_path}</string>
    <key>StandardErrorPath</key>
    <string>{stderr_path}</string>
  </dict>
</plist>
"""


def install(args: argparse.Namespace) -> int:
    install_dir = Path(os.path.expanduser(args.install_dir))
    plist_path = Path(os.path.expanduser(args.plist_path))
    label = args.label
    config_root = Path(args.config_root)
    host = args.host
    port = args.port
    python_path = args.python or resolve_python()

    install_dir.mkdir(parents=True, exist_ok=True)
    script_dir = Path(__file__).resolve().parent
    for name in COPY_SCRIPTS:
        source = script_dir / name
        if not source.exists():
            print(f"missing script: {source}", file=sys.stderr)
            return 2
        shutil.copy2(source, install_dir / name)

    wrapper_path = install_dir / "task-dev-portal.sh"
    write_file(wrapper_path, render_wrapper(install_dir, config_root, host, port, python_path), mode=0o755)

    stdout_path = Path(args.stdout_path)
    stderr_path = Path(args.stderr_path)
    plist_content = render_plist(label, wrapper_path, stdout_path, stderr_path, args.throttle_interval)
    write_file(plist_path, plist_content)

    print(f"installed portal server scripts: {install_dir}")
    print(f"installed wrapper: {wrapper_path}")
    print(f"installed launchd plist: {plist_path}")
    print(f"portal will listen on http://{host}:{port}/")

    if args.load:
        subprocess.run(["launchctl", "load", "-w", str(plist_path)], check=False)
        subprocess.run(["launchctl", "kickstart", "-k", f"gui/{os.getuid()}/{label}"], check=False)
        print("launchd agent loaded and kickstarted.")
    else:
        print("not loaded. Load it with:")
        print(f"  launchctl load -w {plist_path}")

    return 0


def uninstall(args: argparse.Namespace) -> int:
    plist_path = Path(os.path.expanduser(args.plist_path))
    install_dir = Path(os.path.expanduser(args.install_dir))

    if plist_path.exists():
        subprocess.run(["launchctl", "unload", "-w", str(plist_path)], check=False)
        plist_path.unlink(missing_ok=True)
        print(f"unloaded and removed: {plist_path}")
    else:
        print(f"no plist at {plist_path}")

    if args.remove_data and install_dir.exists():
        shutil.rmtree(install_dir)
        print(f"removed installed scripts: {install_dir}")

    return 0


def status(args: argparse.Namespace) -> int:
    plist_path = Path(os.path.expanduser(args.plist_path))
    label = args.label
    port = args.port
    print(f"plist: {plist_path}")
    print(f"plist exists: {plist_path.exists()}")
    print(f"label: {label}")

    try:
        result = subprocess.run(
            ["launchctl", "print", f"gui/{os.getuid()}/{label}"],
            capture_output=True,
            text=True,
            check=False,
        )
        loaded = result.returncode == 0
        print(f"launchd loaded: {loaded}")
        if not loaded and result.stderr.strip():
            print(f"launchd detail: {result.stderr.strip()}")
    except FileNotFoundError:
        print("launchctl not found; cannot check launchd state")

    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            print(f"http reachable: yes (port {port})")
    except OSError:
        print(f"http reachable: no (port {port})")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Install/uninstall the task dev portal as a keep-alive macOS LaunchAgent."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    install_parser = subparsers.add_parser("install", help="Install the keep-alive portal service")
    install_parser.add_argument("--label", default=DEFAULT_LABEL)
    install_parser.add_argument("--install-dir", default=DEFAULT_INSTALL_DIR)
    install_parser.add_argument("--plist-path", default=DEFAULT_PLIST_PATH)
    install_parser.add_argument("--config-root", type=Path, default=DEFAULT_CONFIG_ROOT)
    install_parser.add_argument("--host", default=DEFAULT_HOST)
    install_parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    install_parser.add_argument("--python", default="", help="Python interpreter used by launchd wrapper")
    install_parser.add_argument("--stdout-path", default="/tmp/task-dev-portal.out.log")
    install_parser.add_argument("--stderr-path", default="/tmp/task-dev-portal.err.log")
    install_parser.add_argument("--throttle-interval", type=int, default=10)
    install_parser.add_argument("--load", action="store_true", help="Load and kickstart the LaunchAgent after install")
    install_parser.set_defaults(func=install)

    uninstall_parser = subparsers.add_parser("uninstall", help="Uninstall the keep-alive portal service")
    uninstall_parser.add_argument("--label", default=DEFAULT_LABEL)
    uninstall_parser.add_argument("--install-dir", default=DEFAULT_INSTALL_DIR)
    uninstall_parser.add_argument("--plist-path", default=DEFAULT_PLIST_PATH)
    uninstall_parser.add_argument("--remove-data", action="store_true", help="Also remove installed scripts under --install-dir")
    uninstall_parser.set_defaults(func=uninstall)

    status_parser = subparsers.add_parser("status", help="Show portal service status")
    status_parser.add_argument("--label", default=DEFAULT_LABEL)
    status_parser.add_argument("--install-dir", default=DEFAULT_INSTALL_DIR)
    status_parser.add_argument("--plist-path", default=DEFAULT_PLIST_PATH)
    status_parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    status_parser.set_defaults(func=status)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
