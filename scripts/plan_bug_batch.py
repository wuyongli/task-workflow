#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


VERDICTS = {"real", "unclear", "not_bug", "blocked"}


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("expected a list")
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            raise ValueError(f"expected list items to be strings, got {type(item).__name__}: {item!r}")
        text = item.strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _bool(value: Any) -> bool:
    return value is True


def _reason_with_note(reason: str, note: str) -> str:
    return f"{reason}; {note}" if note else reason


def _collect_tester_ids(bugs: list[dict[str, Any]]) -> dict[str, set[str]]:
    name_to_ids: dict[str, set[str]] = {}
    for bug in bugs:
        tester = str(bug.get("tester") or "").strip()
        tester_id = str(bug.get("tester_id") or "").strip()
        if tester and tester_id:
            name_to_ids.setdefault(tester, set()).add(tester_id)
    return name_to_ids


def _resolve_tester_id(
    bug_key: str,
    tester: str,
    tester_id: str,
    name_to_ids: dict[str, set[str]],
    warnings: list[str],
) -> str:
    if not tester or tester_id:
        return tester_id
    ids = name_to_ids.get(tester, set())
    if len(ids) == 1:
        resolved = next(iter(ids))
        warnings.append(f"{bug_key}: tester_id missing for {tester}; inferred {resolved} from batch")
        return resolved
    if len(ids) > 1:
        warnings.append(
            f"{bug_key}: tester_id missing for {tester}; ambiguous ids in batch: {', '.join(sorted(ids))}"
        )
        return ""
    warnings.append(f"{bug_key}: tester_id missing for {tester}")
    return ""


def build_plan(payload: dict[str, Any]) -> dict[str, Any]:
    bugs = payload.get("bugs")
    if not isinstance(bugs, list) or not bugs:
        raise ValueError("bugs must be a non-empty list")

    name_to_ids = _collect_tester_ids([bug for bug in bugs if isinstance(bug, dict)])
    warnings: list[str] = []
    for tester_name, tester_ids in sorted(name_to_ids.items()):
        if len(tester_ids) > 1:
            warnings.append(
                f"tester {tester_name} has multiple tester_id values: {', '.join(sorted(tester_ids))}"
            )

    publish_by_repo: dict[str, list[str]] = {}
    pending_verify: list[str] = []
    hold: list[dict[str, str]] = []
    notify: dict[str, dict[str, Any]] = {}
    unassigned: list[str] = []
    seen_keys: set[str] = set()

    for raw in bugs:
        if not isinstance(raw, dict):
            raise ValueError("each bug must be an object")
        key = str(raw.get("key") or "").strip()
        verdict = str(raw.get("verdict") or "").strip().lower()
        if not key:
            raise ValueError("bug.key is required")
        if key in seen_keys:
            raise ValueError(f"duplicate bug key: {key}")
        seen_keys.add(key)
        if verdict not in VERDICTS:
            raise ValueError(f"{key}: verdict must be one of {sorted(VERDICTS)}")
        if verdict == "real":
            for field in ("verified", "pushed"):
                if not isinstance(raw.get(field), bool):
                    raise ValueError(f"{key}: {field} must be a JSON boolean")

        tester = str(raw.get("tester") or "").strip()
        tester_id = _resolve_tester_id(
            key,
            tester,
            str(raw.get("tester_id") or "").strip(),
            name_to_ids,
            warnings,
        )
        note = str(raw.get("note") or "").strip()
        repos = _as_list(raw.get("repos"))
        published_repos = _as_list(raw.get("published_repos"))
        unknown_published = [repo for repo in published_repos if repo not in repos]
        if unknown_published:
            raise ValueError(f"{key}: published_repos not in repos: {', '.join(unknown_published)}")

        recipient = f"name:{tester}" if tester else ""
        if recipient:
            bucket = notify.setdefault(
                recipient,
                {
                    "tester": tester,
                    "tester_id": tester_id,
                    "pending_verify": [],
                    "waiting_publish": [],
                    "hold": [],
                },
            )
            if tester_id and not bucket["tester_id"]:
                bucket["tester_id"] = tester_id

        if verdict != "real":
            reason = f"verdict={verdict}"
            if note:
                reason = f"{reason}; {note}"
            hold.append({"key": key, "reason": reason})
            if recipient:
                notify[recipient]["hold"].append({"key": key, "reason": reason})
            else:
                unassigned.append(key)
            continue

        if not repos:
            reason = _reason_with_note("verdict=real but repos is empty", note)
            hold.append({"key": key, "reason": reason})
            if recipient:
                notify[recipient]["hold"].append({"key": key, "reason": reason})
            else:
                unassigned.append(key)
            continue

        if not _bool(raw.get("verified")):
            reason = _reason_with_note("verified=false", note)
            hold.append({"key": key, "reason": reason})
            if recipient:
                notify[recipient]["hold"].append({"key": key, "reason": reason})
            else:
                unassigned.append(key)
            continue

        if not _bool(raw.get("pushed")):
            reason = _reason_with_note("pushed=false", note)
            hold.append({"key": key, "reason": reason})
            if recipient:
                notify[recipient]["hold"].append({"key": key, "reason": reason})
            else:
                unassigned.append(key)
            continue

        pending_repos = [repo for repo in repos if repo not in published_repos]
        if pending_repos:
            for repo in pending_repos:
                publish_by_repo.setdefault(repo, []).append(key)
            if recipient:
                notify[recipient].setdefault("waiting_publish", []).append(key)
            else:
                unassigned.append(key)
            continue

        pending_verify.append(key)
        if recipient:
            notify[recipient]["pending_verify"].append(key)
        else:
            unassigned.append(key)

    return {
        "batch": str(payload.get("batch") or "").strip(),
        "publish_repos": list(publish_by_repo),
        "publish_by_repo": publish_by_repo,
        "pending_verify": pending_verify,
        "hold": hold,
        "notify": list(notify.values()),
        "unassigned": unassigned,
        "warnings": warnings,
    }


def render_text(plan: dict[str, Any]) -> str:
    lines = [f"publish_repos: {', '.join(plan['publish_repos']) or '-'}"]
    for repo, keys in plan["publish_by_repo"].items():
        lines.append(f"  {repo}: {', '.join(keys)}")
    lines.append(f"pending_verify: {', '.join(plan['pending_verify']) or '-'}")
    lines.append("hold:")
    if plan["hold"]:
        for item in plan["hold"]:
            lines.append(f"  {item['key']}: {item['reason']}")
    else:
        lines.append("  -")
    lines.append("notify:")
    if plan["notify"]:
        for bucket in plan["notify"]:
            name = bucket["tester"] or "(missing tester)"
            tester_id = bucket["tester_id"] or "-"
            lines.append(f"  {name} [{tester_id}]")
            if bucket["pending_verify"]:
                lines.append(f"    pending_verify: {', '.join(bucket['pending_verify'])}")
            if bucket.get("waiting_publish"):
                lines.append(f"    waiting_publish: {', '.join(bucket['waiting_publish'])}")
            if bucket["hold"]:
                hold_text = ", ".join(f"{item['key']} ({item['reason']})" for item in bucket["hold"])
                lines.append(f"    hold: {hold_text}")
    else:
        lines.append("  -")
    lines.append(f"unassigned: {', '.join(plan['unassigned']) or '-'}")
    lines.append("warnings:")
    if plan["warnings"]:
        for warning in plan["warnings"]:
            lines.append(f"  {warning}")
    else:
        lines.append("  -")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Plan a Test Hub bug batch: publish repos, pending-verify items, and testers to notify."
    )
    parser.add_argument("--input", type=Path, required=True, help="Batch JSON file")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args()

    try:
        payload = json.loads(args.input.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("top-level JSON must be an object")
        plan = build_plan(payload)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"plan_bug_batch: {exc}", file=sys.stderr)
        return 2

    if args.format == "json":
        print(json.dumps(plan, ensure_ascii=False, indent=2))
    else:
        print(render_text(plan))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
