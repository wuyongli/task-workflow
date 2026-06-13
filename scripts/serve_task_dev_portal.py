#!/usr/bin/env python3

from __future__ import annotations

import argparse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from render_task_dev_portal import DEFAULT_CONFIG_ROOT, DEFAULT_OUTPUT_NAME, build_portal_html
from task_workflow_lib import load_yaml


def make_handler(config_root: Path, default_output_path: Path):
    class PortalHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path not in {"/", "/task-dev-portal", "/task-dev-portal.html"}:
                self.send_error(HTTPStatus.NOT_FOUND, "Not Found")
                return

            query = parse_qs(parsed.query)
            include_completed = query.get("all", ["0"])[0] in {"1", "true", "yes"}
            content, _task_count = build_portal_html(
                config_root=config_root,
                output_path=default_output_path,
                include_completed=include_completed,
            )
            body = content.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args) -> None:  # noqa: A003
            return

    return PortalHandler


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve the task dev portal with live data on each refresh.")
    parser.add_argument("--config-root", type=Path, default=DEFAULT_CONFIG_ROOT)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    workspace_cfg = load_yaml(args.config_root / "workspace.yaml")
    workspace_root = Path(workspace_cfg["workspace_root"])
    output_path = workspace_root / DEFAULT_OUTPUT_NAME

    server = ThreadingHTTPServer((args.host, args.port), make_handler(args.config_root, output_path))
    print(f"serving task dev portal at http://{args.host}:{args.port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
