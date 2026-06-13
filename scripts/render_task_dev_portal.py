#!/usr/bin/env python3

from __future__ import annotations

import argparse
import html
import socket
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from task_workflow_lib import (
    _parse_env_file,
    classify_repo_publish_kind,
    load_task_meta,
    load_yaml,
    resolve_repo_path,
)


DEFAULT_CONFIG_ROOT = Path("/Users/wuyongli/Documents/sg-project/_workspace/config")
DEFAULT_OUTPUT_NAME = "task-dev-portal.html"
DEFAULT_WEB_HOST = "pfzone.senguo.me"
ACTIVE_STATUSES = {"方案中", "开发中", "测试中", "暂停中"}
STATUS_ORDER = {
    "开发中": 0,
    "测试中": 1,
    "方案中": 2,
    "暂停中": 3,
    "已完成": 9,
}


def build_frontend_url(target_kind: str, port: str) -> str:
    base_path = "/"
    if target_kind == "mobile_frontend":
        base_path = "/mproducer/"
    elif target_kind == "pc_frontend":
        base_path = "/producer/"
    return f"http://{DEFAULT_WEB_HOST}:{port}{base_path}"


def build_repo_cfg_by_key(config_root: Path) -> dict[str, dict[str, object]]:
    repositories_cfg = load_yaml(config_root / "repositories.yaml")
    return {
        str(row.get("key") or ""): row
        for row in repositories_cfg.get("repositories", [])
        if isinstance(row, dict) and row.get("key")
    }


def render_status_badge(status: str) -> str:
    tone = {
        "开发中": "live",
        "测试中": "test",
        "方案中": "plan",
        "暂停中": "pause",
        "已完成": "done",
    }.get(status, "default")
    return f'<span class="badge badge-{tone}">{html.escape(status)}</span>'


def is_tcp_port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.25) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def build_favicon_href() -> str:
    svg = """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <rect width="64" height="64" rx="14" fill="#0b1117"/>
  <rect x="6" y="6" width="52" height="52" rx="12" fill="#101923" stroke="#56f1d6" stroke-width="2"/>
  <path d="M19 22l-7 10 7 10" fill="none" stroke="#56f1d6" stroke-linecap="round" stroke-linejoin="round" stroke-width="4"/>
  <path d="M28 42h17" fill="none" stroke="#87ffca" stroke-linecap="round" stroke-width="4"/>
  <circle cx="46" cy="20" r="4" fill="#56f1d6"/>
</svg>
""".strip()
    return f"data:image/svg+xml,{quote(svg)}"


def render_repo_link(label: str, url: str, subtitle: str, runtime_status: str) -> str:
    safe_url = html.escape(url, quote=True)
    safe_label = html.escape(label)
    safe_runtime_status = html.escape(runtime_status)
    status_class = "is-up" if runtime_status == "运行中" else "is-down"
    return (
        '<div class="repo-link-card">'
        '<a class="repo-link" href="{url}" target="_blank" rel="noreferrer">'
        '<span class="repo-link-head">'
        '<span class="repo-link-title">{label}<span class="runtime-dot {status_class}" '
        'title="{runtime_status}" aria-label="{runtime_status}"></span></span>'
        "</span>"
        '<span class="repo-link-url">{url}</span>'
        "</a>"
        '<button class="copy-btn" type="button" data-url="{url}" aria-label="复制地址" title="复制地址">'
        '<span class="copy-icon" aria-hidden="true"></span>'
        "</button>"
        "</div>"
    ).format(
        url=safe_url,
        label=safe_label,
        runtime_status=safe_runtime_status,
        status_class=status_class,
    )


def collect_task_cards(docs_root: Path, tasks_root: Path, repo_cfg_by_key: dict[str, dict[str, object]], include_completed: bool) -> list[dict[str, object]]:
    task_cards: list[dict[str, object]] = []
    for task_dir in sorted(path for path in docs_root.iterdir() if path.is_dir() and not path.name.startswith(".")):
        meta_path = task_dir / "meta.yaml"
        if not meta_path.exists():
            continue
        _meta_path, meta = load_task_meta(docs_root, task_dir.name)
        status = str(meta.get("status") or "未知")
        if not include_completed and status not in ACTIVE_STATUSES:
            continue

        repos = meta.get("repos", [])
        if not isinstance(repos, list):
            continue

        frontend_links: list[str] = []
        for repo_meta in repos:
            if not isinstance(repo_meta, dict):
                continue
            repo_key = str(repo_meta.get("key") or "")
            repo_cfg = repo_cfg_by_key.get(repo_key)
            if repo_cfg is None:
                continue

            target_kind = classify_repo_publish_kind(repo_cfg)
            if target_kind in {"mobile_frontend", "pc_frontend"}:
                repo_path = resolve_repo_path(tasks_root, task_dir.name, repo_meta)
                env_data = _parse_env_file(repo_path / ".codex/task-runtime.env")
                port = env_data.get("TASK_WEB_PORT", "")
                if port:
                    label = "手机端" if target_kind == "mobile_frontend" else "PC 端"
                    runtime_status = "运行中" if is_tcp_port_open(int(port)) else "未启动"
                    frontend_links.append(
                        render_repo_link(label, build_frontend_url(target_kind, port), repo_key, runtime_status)
                    )

        if not frontend_links:
            continue

        task_cards.append(
            {
                "task_id": task_dir.name,
                "status": status,
                "sort_key": (STATUS_ORDER.get(status, 99), task_dir.name),
                "card_html": """
<section class="task-card" data-status="{status}">
  <div class="task-head">
    <div class="task-title-row">
      <div class="task-title">{task_id}</div>
      <div class="task-meta">{status_badge}</div>
    </div>
  </div>
  <div class="task-links">{frontend_links}</div>
</section>
""".format(
                    task_id=html.escape(task_dir.name),
                    status_badge=render_status_badge(status),
                    frontend_links="".join(frontend_links) or '<div class="empty-links">当前没有可直接打开的前端地址</div>',
                    status=html.escape(status),
                ),
            }
        )

    task_cards.sort(key=lambda item: item["sort_key"])
    return task_cards


def render_html(task_cards: list[dict[str, object]], output_path: Path) -> str:
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    card_html = "".join(str(item["card_html"]) for item in task_cards)
    total = len(task_cards)
    favicon_href = build_favicon_href()
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>任务开发地址导航</title>
  <link rel="icon" href="{favicon_href}" type="image/svg+xml" />
  <style>
    :root {{
      --bg: #0b1117;
      --bg-soft: #101923;
      --panel: rgba(16, 25, 35, 0.92);
      --panel-soft: rgba(13, 21, 30, 0.94);
      --ink: #e6f3ff;
      --muted: #8fa6b8;
      --line: rgba(101, 140, 164, 0.28);
      --accent: #56f1d6;
      --accent-strong: #87ffca;
      --accent-soft: rgba(86, 241, 214, 0.12);
      --plan: rgba(255, 214, 102, 0.2);
      --live: rgba(135, 255, 202, 0.22);
      --test: rgba(117, 196, 255, 0.22);
      --pause: rgba(167, 139, 250, 0.2);
      --done: rgba(148, 163, 184, 0.18);
      --shadow: 0 16px 40px rgba(0, 0, 0, 0.34);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "JetBrains Mono", "SFMono-Regular", "Cascadia Code", "IBM Plex Mono", "Menlo", "PingFang SC", monospace;
      color: var(--ink);
      background:
        linear-gradient(rgba(86, 241, 214, 0.08) 1px, transparent 1px),
        linear-gradient(90deg, rgba(86, 241, 214, 0.08) 1px, transparent 1px),
        radial-gradient(circle at top, rgba(86, 241, 214, 0.12), transparent 30%),
        radial-gradient(circle at bottom right, rgba(117, 196, 255, 0.12), transparent 24%),
        var(--bg);
      background-size: 28px 28px, 28px 28px, auto, auto, auto;
    }}
    .page {{
      max-width: 1160px;
      margin: 0 auto;
      padding: 24px 20px 44px;
    }}
    .hero {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 22px;
      box-shadow: var(--shadow);
      padding: 22px 24px;
      margin-bottom: 18px;
      position: relative;
      overflow: hidden;
    }}
    .hero::after {{
      content: "";
      position: absolute;
      inset: 0;
      background: linear-gradient(135deg, rgba(86, 241, 214, 0.08), transparent 45%, rgba(117, 196, 255, 0.06));
      pointer-events: none;
    }}
    .eyebrow {{
      font-size: 11px;
      letter-spacing: 0.16em;
      text-transform: uppercase;
      color: var(--accent);
      margin-bottom: 8px;
      position: relative;
      z-index: 1;
    }}
    h1 {{
      margin: 0;
      font-size: 28px;
      line-height: 1.12;
      letter-spacing: -0.03em;
      position: relative;
      z-index: 1;
    }}
    .hero-meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 14px;
      color: var(--muted);
      font-size: 13px;
      position: relative;
      z-index: 1;
    }}
    .meta-pill {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 7px 10px;
      border-radius: 999px;
      background: var(--panel-soft);
      border: 1px solid var(--line);
    }}
    .list-head {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin: 6px 0 14px;
      padding: 0 2px;
    }}
    .list-title {{
      font-size: 15px;
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      color: var(--accent);
    }}
    .task-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(340px, 1fr));
      gap: 14px;
    }}
    .task-card {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 20px;
      padding: 16px;
      box-shadow: var(--shadow);
      position: relative;
      overflow: hidden;
    }}
    .task-card::before {{
      content: "";
      position: absolute;
      inset: 0 auto 0 0;
      width: 3px;
      background: linear-gradient(180deg, var(--accent), rgba(135, 255, 202, 0.18));
      opacity: 0.95;
    }}
    .task-head {{
      position: relative;
      z-index: 1;
    }}
    .task-title-row {{
      display: flex;
      align-items: flex-start;
      gap: 10px;
      flex-wrap: wrap;
    }}
    .task-title {{
      font-size: 20px;
      line-height: 1.2;
      font-weight: 700;
      letter-spacing: -0.02em;
      word-break: break-word;
      flex: 1 1 220px;
    }}
    .task-meta {{
      flex: 0 0 auto;
      padding-top: 2px;
    }}
    .badge {{
      display: inline-flex;
      align-items: center;
      border-radius: 999px;
      padding: 5px 9px;
      font-size: 11px;
      font-weight: 700;
      border: 1px solid rgba(255, 255, 255, 0.06);
    }}
    .badge-live {{ background: var(--live); }}
    .badge-test {{ background: var(--test); }}
    .badge-plan {{ background: var(--plan); }}
    .badge-pause {{ background: var(--pause); }}
    .badge-done {{ background: var(--done); }}
    .badge-default {{ background: #ece7de; }}
    .task-links {{
      display: grid;
      gap: 10px;
      margin-top: 16px;
      position: relative;
      z-index: 1;
    }}
    .repo-link-card {{
      position: relative;
    }}
    .repo-link {{
      display: block;
      text-decoration: none;
      color: inherit;
      padding: 13px 50px 13px 14px;
      border-radius: 16px;
      border: 1px solid var(--line);
      background: var(--panel-soft);
      transition: transform 120ms ease, border-color 120ms ease, box-shadow 120ms ease, background 120ms ease;
    }}
    .repo-link:hover {{
      transform: translateY(-1px);
      border-color: var(--accent);
      box-shadow: 0 12px 28px rgba(86, 241, 214, 0.12);
      background: rgba(17, 30, 42, 0.98);
    }}
    .repo-link-head {{
      display: flex;
      align-items: center;
      gap: 10px;
    }}
    .copy-btn {{
      position: absolute;
      top: 12px;
      right: 12px;
      width: 24px;
      height: 24px;
      padding: 0;
      border: 1px solid rgba(86, 241, 214, 0.1);
      border-radius: 8px;
      background: rgba(10, 20, 28, 0.38);
      cursor: pointer;
      transition: transform 120ms ease, border-color 120ms ease, background 120ms ease, opacity 120ms ease, box-shadow 120ms ease;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      opacity: 0.58;
    }}
    .copy-btn:hover {{
      transform: translateY(-1px);
      border-color: rgba(86, 241, 214, 0.24);
      background: rgba(17, 30, 42, 0.72);
      opacity: 0.92;
    }}
    .copy-btn.is-copied {{
      border-color: rgba(135, 255, 202, 0.6);
      background: rgba(86, 241, 214, 0.14);
      box-shadow: 0 0 0 1px rgba(135, 255, 202, 0.08), 0 0 12px rgba(86, 241, 214, 0.2);
      opacity: 1;
    }}
    .copy-icon {{
      position: relative;
      display: inline-block;
      width: 12px;
      height: 12px;
    }}
    .copy-icon::before,
    .copy-icon::after {{
      content: "";
      position: absolute;
      width: 8px;
      height: 8px;
      border: 1.25px solid rgba(86, 241, 214, 0.72);
      border-radius: 2px;
      background: transparent;
    }}
    .copy-icon::before {{
      top: 2px;
      left: 0;
      opacity: 0.72;
    }}
    .copy-icon::after {{
      top: 0;
      left: 3px;
    }}
    .copy-btn.is-copied .copy-icon::before,
    .copy-btn.is-copied .copy-icon::after {{
      border-color: var(--accent-strong);
    }}
    .copy-btn.is-copied .copy-icon::before {{
      width: 4px;
      height: 8px;
      top: 1px;
      left: 4px;
      opacity: 1;
      border: 0;
      border-right: 2px solid var(--accent-strong);
      border-bottom: 2px solid var(--accent-strong);
      border-radius: 0;
      transform: rotate(40deg);
      box-shadow: none;
    }}
    .copy-btn.is-copied .copy-icon::after {{
      opacity: 0;
    }}
    .repo-link-title {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      font-size: 16px;
      font-weight: 700;
    }}
    .runtime-dot {{
      width: 8px;
      height: 8px;
      border-radius: 999px;
      display: inline-block;
      flex: 0 0 auto;
      box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.06);
    }}
    .runtime-dot.is-up {{
      background: var(--accent);
      box-shadow: 0 0 0 1px rgba(86, 241, 214, 0.18), 0 0 10px rgba(86, 241, 214, 0.45);
    }}
    .runtime-dot.is-down {{
      background: #ff5f6d;
      box-shadow: 0 0 0 1px rgba(255, 95, 109, 0.18), 0 0 10px rgba(255, 95, 109, 0.38);
    }}
    .repo-link-url {{
      display: block;
      margin-top: 8px;
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 12px;
      color: var(--accent-strong);
      word-break: break-all;
    }}
    .empty-links {{
      color: var(--muted);
      font-size: 14px;
      padding: 10px 0;
    }}
    .footer {{
      margin-top: 18px;
      color: var(--muted);
      font-size: 12px;
      padding: 0 2px;
    }}
    @media (max-width: 720px) {{
      .page {{ padding: 16px 14px 30px; }}
      .hero {{ padding: 18px; }}
      h1 {{ font-size: 24px; }}
      .task-title {{ font-size: 19px; }}
      .list-head {{
        align-items: flex-start;
        flex-direction: column;
      }}
    }}
  </style>
</head>
<body>
  <div class="page">
    <section class="hero">
      <div class="eyebrow">Task Workflow Portal</div>
      <h1>本地任务开发地址导航</h1>
      <div class="hero-meta">
        <span class="meta-pill">共 {total} 个任务</span>
        <span class="meta-pill">更新于 {html.escape(generated_at)}</span>
      </div>
    </section>

    <div class="list-head">
      <div class="list-title">任务列表</div>
    </div>

    <section id="task-grid" class="task-grid">
      {card_html or '<section class="task-card"><div class="task-title">当前没有可展示的任务地址</div></section>'}
    </section>

    <div class="footer">
      说明：页面数据来自 `_docs/*/meta.yaml` 与前端 `.codex/task-runtime.env`。实时地址刷新即可更新；静态文件需重新生成。
    </div>
  </div>
  <script>
    document.addEventListener("click", async (event) => {{
      const button = event.target.closest(".copy-btn");
      if (!button) return;
      const url = button.dataset.url || "";
      if (!url) return;
      try {{
        await navigator.clipboard.writeText(url);
        button.title = "已复制";
        button.setAttribute("aria-label", "已复制");
        button.classList.add("is-copied");
      }} catch (_error) {{
        button.title = "复制失败";
        button.setAttribute("aria-label", "复制失败");
      }}
      window.setTimeout(() => {{
        button.title = "复制地址";
        button.setAttribute("aria-label", "复制地址");
        button.classList.remove("is-copied");
      }}, 1400);
    }});
  </script>
</body>
</html>"""


def build_portal_html(config_root: Path, output_path: Path, include_completed: bool) -> tuple[str, int]:
    workspace_cfg = load_yaml(config_root / "workspace.yaml")
    docs_root = Path(workspace_cfg["docs_root"])
    tasks_root = Path(workspace_cfg["tasks_root"])
    repo_cfg_by_key = build_repo_cfg_by_key(config_root)
    task_cards = collect_task_cards(docs_root, tasks_root, repo_cfg_by_key, include_completed=include_completed)
    return render_html(task_cards, output_path), len(task_cards)


def main() -> int:
    parser = argparse.ArgumentParser(description="Render a local HTML portal for active task frontend URLs.")
    parser.add_argument("--config-root", type=Path, default=DEFAULT_CONFIG_ROOT)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--all", action="store_true", help="Include completed tasks")
    args = parser.parse_args()

    workspace_cfg = load_yaml(args.config_root / "workspace.yaml")
    workspace_root = Path(workspace_cfg["workspace_root"])
    output_path = args.output or (workspace_root / DEFAULT_OUTPUT_NAME)
    content, task_count = build_portal_html(args.config_root, output_path, include_completed=args.all)
    output_path.write_text(content, encoding="utf-8")
    print(f"generated: {output_path}")
    print(f"tasks: {task_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
