#!/usr/bin/env python3
"""Persistent serial dispatch ledger. External actions remain with the Codex coordinator.

No timer, Docker operation, thread creation, message send, or task-meta mutation occurs here.
All mutations use a process lock and atomic replacement of one JSON file.
"""
from __future__ import annotations

import argparse
import copy
import fcntl
import json
import os
import tempfile
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml


def require_text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be nonempty text")
    return value


def minute_of_day(value):
    if (not isinstance(value, str) or len(value) != 5 or value[2] != ":"
            or not value[:2].isdigit() or not value[3:].isdigit()):
        raise ValueError("schedule time must be HH:MM")
    hour, minute = map(int, value.split(":"))
    if hour > 23 or minute > 59:
        raise ValueError("invalid schedule time")
    return hour * 60 + minute


def work_window(state):
    window = state["plan"].get("work_hours", {"start": "08:00", "last_start": "18:00", "end": "18:00"})
    return tuple(minute_of_day(window[key]) for key in ("start", "last_start", "end"))


def validate_plan(plan):
    if not isinstance(plan, dict) or plan.get("timezone") != "Asia/Shanghai":
        raise ValueError("plan timezone must be Asia/Shanghai")
    start, end = date.fromisoformat(plan["start_date"]), date.fromisoformat(plan["end_date"])
    if start > end or not isinstance(plan.get("tasks"), list) or not plan["tasks"]:
        raise ValueError("invalid date window or empty task plan")
    if "work_hours" in plan:
        window = plan["work_hours"]
        if not isinstance(window, dict) or set(window) != {"start", "last_start", "end"}:
            raise ValueError("work_hours must contain start, last_start and end")
        opening, last_start, closing = (minute_of_day(window[key]) for key in ("start", "last_start", "end"))
        if not opening < last_start <= closing:
            raise ValueError("invalid work_hours window")
    keys, paths = set(), set()
    for task in plan["tasks"]:
        key = require_text(task.get("key"), "task key")
        require_text(task.get("name"), "task name")
        if key in keys or not start <= date.fromisoformat(task["day"]) <= end:
            raise ValueError("duplicate task key or task date outside plan")
        keys.add(key)
        if type(task.get("phase")) is not int or task["phase"] < 1:
            raise ValueError("task phase must be a positive integer")
        if task.get("docs"):
            path = Path(task["docs"])
            if not path.is_absolute() or str(path.resolve()) in paths:
                raise ValueError("docs must be absolute and unique per task workspace")
            paths.add(str(path.resolve()))


@contextmanager
def locked(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(path.suffix + ".lock").open("a", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def atomic_write(path, data):
    fd, name = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def initialize(path, plan):
    path = Path(path)
    validate_plan(plan)
    with locked(path):
        if path.exists():
            raise ValueError("state already exists; initialization never overwrites it")
        state = {"version": 1, "queue_id": str(uuid.uuid4()), "enabled": False,
                 "plan": copy.deepcopy(plan), "active": None, "runs": [],
                 "days": {}, "commands": {}, "outbox": {}, "overtime": {}, "excluded": {},
                 "tasks": {t["key"]: {"thread_id": None, "hold": None,
                            "not_before": t["day"], "checkpoint": None}
                           for t in plan["tasks"]}}
        atomic_write(path, state)
        return state


def read_state(path):
    state = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(state, dict) or state.get("version") != 1 or type(state.get("enabled")) is not bool:
        raise ValueError("invalid dispatch state version or enabled flag")
    for field in ("plan", "tasks", "days", "commands", "outbox", "overtime"):
        if not isinstance(state.get(field), dict):
            raise ValueError("invalid dispatch state field: " + field)
    excluded = state.get("excluded")
    if excluded is not None and not isinstance(excluded, dict):
        raise ValueError("invalid dispatch state field: excluded")
    if not isinstance(state.get("runs"), list) or "active" not in state:
        raise ValueError("missing run history or active reservation")
    validate_plan(state["plan"])
    if set(state["tasks"]) != {t["key"] for t in state["plan"]["tasks"]}:
        raise ValueError("queue task records do not match plan")
    active = state["active"]
    run_ids = set()
    unfinished = []
    for run in state["runs"]:
        if (not isinstance(run, dict) or not run.get("id") or run["id"] in run_ids
                or run.get("key") not in state["tasks"]
                or run.get("state") not in ("reserved", "running", "cleanup_required", "finished")):
            raise ValueError("invalid or duplicate run history")
        run_ids.add(run["id"])
        if run["state"] != "finished":
            unfinished.append(run)
    if (active is not None and not isinstance(active, dict)) or unfinished != ([] if active is None else [active]):
        raise ValueError("active reservation must exactly match the sole unfinished run")
    return state


def entry(state, key):
    return next(t for t in state["plan"]["tasks"] if t["key"] == key)


def gate(task):
    """Return only eligibility facts; scope/plan/Git verification is the worker's job."""
    if not task.get("docs"):
        return "prepare", "workspace not bound"
    path = Path(task["docs"]) / "meta.yaml"
    if not path.exists():
        return "prepare", "workspace metadata missing"
    try:
        meta = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(meta, dict):
            raise ValueError("metadata must be a mapping")
        if meta.get("task_id") != path.parent.name:
            raise ValueError("task_id differs from bound docs directory")
        mode = meta.get("execution_mode", "manual")
        if mode not in ("manual", "auto"):
            raise ValueError("invalid execution_mode")
        stage = meta.get("current_stage") or {}
        if not isinstance(stage, dict):
            raise ValueError("invalid current_stage")
        if meta.get("phase") != task["phase"] or stage.get("phase", meta.get("phase")) != task["phase"]:
            raise ValueError("phase changed; reconcile plan before dispatch")
        status = meta.get("status")
        if stage.get("status", status) != status:
            raise ValueError("task/stage status mismatch")
        if status in ("暂停中", "已完成"):
            return "skip", status
        if status not in ("方案中", "开发中", "测试中"):
            raise ValueError("invalid task status")
        if task.get("bbs_id") and str(stage.get("bbs_id", meta.get("bbs_id"))) != str(task["bbs_id"]):
            raise ValueError("BBS binding mismatch")
        if mode == "manual" or status == "方案中" or (status == "开发中" and meta.get("coding_allowed") is not True):
            return "prepare", "analysis/admission only; code is not yet admitted"
        return "dispatch", "worker must recheck scope, plan, branch and evidence"
    except (OSError, ValueError, TypeError, yaml.YAMLError) as exc:
        return "skip", str(exc)


def in_dates(state, today):
    return state["plan"]["start_date"] <= today <= state["plan"]["end_date"]


def daily_scope(state, today):
    if today not in state["days"]:
        previous = {}
        for day, keys in sorted(state["days"].items()):
            if day < today:
                for key in keys:
                    previous.setdefault(key, day)
        ordered = sorted(state["plan"]["tasks"], key=lambda task: min(task["day"], previous.get(task["key"], task["day"])))
        original = [t for t in ordered if t["day"] == today]
        # Early work is deducted; overdue work occupies, rather than adds to, today's slots.
        slots = sum(state["tasks"][t["key"]]["hold"] not in ("verified", "human") for t in original)
        if not original:
            # A date emptied by rescheduling remains available for overdue work.
            earlier_days = [t["day"] for t in ordered if t["day"] < today]
            if earlier_days:
                slots = sum(t["day"] == max(earlier_days) for t in ordered)
        candidates, excluded = [], {}
        for task in ordered:
            key = task["key"]
            runtime = state["tasks"][key]
            if (task["day"] > today and key not in previous) or runtime["not_before"] > today:
                continue
            if runtime["hold"] in ("verified", "human"):
                continue
            kind, reason = gate(task)
            if kind == "skip":
                excluded[key] = reason
                continue
            candidates.append(key)
        state.setdefault("excluded", {})[today] = excluded
        state["days"][today] = candidates[:slots]
    return state["days"][today]


def decision(state, clock):
    today = clock.date().isoformat()
    active = state["active"]
    opening, last_start, closing = work_window(state)
    minute = clock.hour * 60 + clock.minute
    inside = in_dates(state, today) and opening <= minute < closing
    can_start = inside and minute < last_start
    overtime = state["overtime"].get(today, []) if in_dates(state, today) and minute >= last_start else []
    if active:
        if active["state"] == "cleanup_required":
            return {"action": "cleanup_required", "run": active}
        kind, reason = gate(entry(state, active["key"]))
        revoked = kind == "skip" or (active["kind"] == "dispatch" and kind != "dispatch")
        if not state["enabled"] or (not inside and active["key"] not in overtime) or revoked:
            return {"action": "stop_requested", "run": active,
                    "reason": reason if revoked else "disabled or outside dispatch window"}
        if not can_start and active["key"] not in overtime:
            return {"action": "wind_down", "run": active,
                    "reason": "no new tasks or long steps; save a safe checkpoint and release task resources"}
        return {"action": "reconcile" if active["state"] == "reserved" else "observe", "run": active}
    if not state["enabled"]:
        return {"action": "disabled"}
    if not inside and not overtime:
        return {"action": "outside_window"}
    if not can_start and not overtime:
        return {"action": "wind_down", "reason": "daily new-task cutoff reached"}
    scope = daily_scope(state, today)
    skipped = dict(state.get("excluded", {}).get(today, {}))
    for key in scope:
        runtime = state["tasks"][key]
        if not can_start and key not in overtime:
            continue
        if runtime["hold"] in ("verified", "human") or runtime["not_before"] > today:
            skipped[key] = runtime["hold"] or "checkpoint deferred"
            continue
        task = entry(state, key)
        kind, reason = gate(task)
        if kind == "skip":
            skipped[key] = reason
            continue
        return {"action": kind, "key": key, "task": task, "reason": reason, "skipped": skipped}
    return {"action": "day_done", "skipped": skipped,
            "message": "当日可执行范围已处理完；不自动补入后续日期任务"}


def active_run(state, run_id):
    run = state["active"]
    if not run or run["id"] != run_id:
        raise ValueError("run is not the current reserved execution")
    return run


def update_run(state, run):
    for index, previous in enumerate(state["runs"]):
        if previous["id"] == run["id"]:
            state["runs"][index] = copy.deepcopy(run)
            return
    raise ValueError("run missing from history")


def finish_run(state, request, clock, recovering=False):
    run = active_run(state, request.get("run_id"))
    if recovering:
        if request.get("executor_ended") is not True:
            raise ValueError("recovery requires confirmed ended executor, not a timeout")
        outcome = "blocked"
    else:
        if run["state"] == "reserved":
            raise ValueError("unknown delivery must be reconciled before accepting handoff")
        outcome = request.get("outcome")
    if outcome not in ("verified", "blocked", "checkpoint", "ready"):
        raise ValueError("invalid handoff outcome")
    checkpoint = require_text(request.get("checkpoint"), "checkpoint/evidence reference")
    resources = request.get("resources", {})
    if not isinstance(resources, dict) or type(resources.get("released")) is not bool:
        raise ValueError("resources.released must be an explicit boolean")
    require_text(resources.get("evidence"), "resource verification evidence")
    if outcome == "verified":
        if run["kind"] != "dispatch":
            raise ValueError("preparation alone cannot prove full verification")
        evidence = request.get("evidence", {})
        for field in ("checks", "real_flow", "review", "remote"):
            require_text(evidence.get(field), "verification evidence: " + field)
    if outcome == "ready" and gate(entry(state, run["key"]))[0] != "dispatch":
        raise ValueError("workspace must satisfy metadata gate before ready handoff")
    run["handoff"] = {"outcome": outcome, "checkpoint": checkpoint, "resources": resources,
                      "evidence": request.get("evidence", {})}
    if not resources["released"]:
        run["state"] = "cleanup_required"
        update_run(state, run)
        return {"action": "cleanup_required", "run": run}
    runtime = state["tasks"][run["key"]]
    runtime["checkpoint"] = checkpoint
    runtime["hold"] = {"verified": "verified", "blocked": "human", "checkpoint": None, "ready": None}[outcome]
    if outcome == "checkpoint":
        runtime["not_before"] = (clock.date() + timedelta(days=1)).isoformat()
    run["state"] = "finished"
    run["finished_at"] = clock.isoformat()
    update_run(state, run)
    state["active"] = None
    return {"action": "handed_off", "run": run}


def add_tasks(state, request, clock):
    command_id = require_text(request.get("command_id"), "user command id")
    require_text(request.get("instruction"), "user instruction")
    if command_id in state["commands"]:
        old = state["commands"][command_id]
        if old["request"] != request:
            raise ValueError("command id already used for different instruction")
        return old["result"]
    today = clock.date().isoformat()
    opening, last_start, _ = work_window(state)
    minute = clock.hour * 60 + clock.minute
    if not state["enabled"] or not in_dates(state, today) or minute < opening:
        raise ValueError("queue disabled or outside holiday window")
    if minute >= last_start and request.get("after_hours") is not True:
        raise ValueError("after daily cutoff requires explicit out-of-hours instruction")
    if request.get("after_hours") is True and not request.get("key"):
        raise ValueError("out-of-hours continuation must identify a specific task")
    count = request.get("count", 1)
    if type(count) is not int or count < 1:
        raise ValueError("extra count must be a positive integer")
    scope = daily_scope(state, today)
    choices = [t for t in sorted(state["plan"]["tasks"], key=lambda t: t["day"])
               if (t["key"] not in scope or (request.get("after_hours") is True and request.get("key") == t["key"]))
               and state["tasks"][t["key"]]["hold"] is None
               and gate(t)[0] != "skip"]
    if request.get("key"):
        choices = [t for t in choices if t["key"] == request["key"]]
    added = [t["key"] for t in choices[:count]]
    for key in added:
        if key not in scope:
            scope.append(key)
        state["tasks"][key]["not_before"] = today
    if request.get("after_hours") is True:
        state["overtime"].setdefault(today, []).extend(added)
    result = {"added": added, "date": today}
    state["commands"][command_id] = {"request": copy.deepcopy(request), "result": result}
    return result


def move_tasks(state, request, clock):
    command_id = require_text(request.get("command_id"), "user command id")
    require_text(request.get("instruction"), "reschedule instruction")
    if command_id in state["commands"]:
        old = state["commands"][command_id]
        if old["request"] != request:
            raise ValueError("command id already used for different instruction")
        return old["result"]
    keys = request.get("keys")
    if (not isinstance(keys, list) or not keys
            or any(not isinstance(key, str) or key not in state["tasks"] for key in keys)
            or len(set(keys)) != len(keys)):
        raise ValueError("move requires unique existing task keys")
    day = require_text(request.get("day"), "target day")
    if (date.fromisoformat(day).isoformat() != day or day <= clock.date().isoformat()
            or not in_dates(state, day) or day in state["days"]):
        raise ValueError("target must be an unmaterialized future holiday date")
    for key in keys:
        task = entry(state, key)
        if (task["day"] <= clock.date().isoformat()
                or task["day"] in state["days"]
                or any(key in scope for scope in state["days"].values())
                or any(run["key"] == key for run in state["runs"])):
            raise ValueError("cannot move started tasks or materialized daily scopes")
    moved = []
    for key in keys:
        task = entry(state, key)
        moved.append({"key": key, "from": task["day"], "to": day})
        task["day"] = day
        state["tasks"][key]["not_before"] = day
    result = {"moved": moved}
    state["commands"][command_id] = {"request": copy.deepcopy(request), "result": result}
    return result


def operate(state, request, clock):
    command = request.get("command")
    if command == "status":
        return state
    if command == "move":
        return move_tasks(state, request, clock)
    if command == "schedule":
        instruction = require_text(request.get("instruction"), "schedule change instruction")
        window = {key: require_text(request.get(key), key)
                  for key in ("start", "last_start", "end")}
        plan = copy.deepcopy(state["plan"])
        plan["work_hours"] = window
        validate_plan(plan)
        state["plan"] = plan
        state["last_instruction"] = instruction
        return {"work_hours": plan["work_hours"]}
    if command == "replan":
        instruction = require_text(request.get("instruction"), "schedule change instruction")
        if state["enabled"] or state["active"] or state["runs"] or state["days"] or state["commands"]:
            raise ValueError("replan only before the queue has ever started; preserve running history")
        plan = request.get("plan")
        validate_plan(plan)
        identities = lambda tasks: {t["key"]: {k: v for k, v in t.items() if k != "day"} for t in tasks}
        if identities(plan["tasks"]) != identities(state["plan"]["tasks"]):
            raise ValueError("replan may change dates only, not task scope or workspace identity")
        state["plan"] = copy.deepcopy(plan)
        state["last_instruction"] = instruction
        for task in plan["tasks"]:
            state["tasks"][task["key"]]["not_before"] = task["day"]
        return {"rescheduled": True, "enabled": False}
    if command in ("enable", "disable"):
        state["last_instruction"] = require_text(request.get("instruction"), "user instruction")
        state["enabled"] = command == "enable"
        return {"enabled": state["enabled"], "active": state["active"]}
    if command in ("tick", "claim"):
        result = decision(state, clock)
        if command == "claim" and result["action"] in ("prepare", "dispatch"):
            key = result["key"]
            run = {"id": str(uuid.uuid4()), "key": key, "kind": result["action"], "state": "reserved",
                   "phase": entry(state, key)["phase"], "created_at": clock.isoformat(),
                   "thread_id": state["tasks"][key]["thread_id"]}
            state["active"] = run
            state["runs"].append(copy.deepcopy(run))
            result["run"] = run
        return result
    if command in ("creating", "attach", "ack"):
        run = active_run(state, request.get("run_id"))
        if command == "creating":
            client_id = require_text(request.get("client_thread_id"), "pending creation id")
            if run.get("client_thread_id") and run["client_thread_id"] != client_id:
                raise ValueError("pending thread creation already recorded")
            run["client_thread_id"] = client_id
        elif command == "attach":
            thread_id = require_text(request.get("thread_id"), "thread id")
            if run["thread_id"] and run["thread_id"] != thread_id:
                raise ValueError("execution already bound to a different thread")
            if any(key != run["key"] and t["thread_id"] == thread_id for key, t in state["tasks"].items()):
                raise ValueError("thread already belongs to another task")
            run["thread_id"] = thread_id
            state["tasks"][run["key"]]["thread_id"] = thread_id
        else:
            if not run["thread_id"]:
                raise ValueError("bind confirmed thread before acknowledging delivery")
            if run["state"] != "reserved":
                return {"run": run}
            run["state"] = "running"
        update_run(state, run)
        return {"run": run}
    if command == "bind":
        run = active_run(state, request.get("run_id"))
        if run["kind"] != "prepare":
            raise ValueError("workspace binding only allowed during preparation")
        task = entry(state, run["key"])
        docs = str(Path(require_text(request.get("docs"), "docs path")).resolve())
        if task.get("docs") and str(Path(task["docs"]).resolve()) != docs:
            raise ValueError("cannot replace existing workspace binding")
        task["docs"] = docs
        validate_plan(state["plan"])
        return {"task": task, "gate": gate(task)}
    if command == "prebind":
        key = require_text(request.get("key"), "task key")
        if key not in state["tasks"]:
            raise ValueError("unknown task key")
        if state.get("active"):
            raise ValueError("cannot prebind while an execution is active")
        task = entry(state, key)
        docs = str(Path(require_text(request.get("docs"), "docs path")).resolve())
        if task.get("docs") and str(Path(task["docs"]).resolve()) != docs:
            raise ValueError("cannot replace existing workspace binding")
        meta = Path(docs) / "meta.yaml"
        if not meta.is_file():
            raise ValueError("docs path must contain meta.yaml")
        task["docs"] = docs
        validate_plan(state["plan"])
        return {"task": task, "gate": gate(task), "prebound": True}
    if command in ("handoff", "recover"):
        return finish_run(state, request, clock, recovering=command == "recover")
    if command == "add":
        return add_tasks(state, request, clock)
    if command == "resume":
        require_text(request.get("instruction"), "explicit task resume instruction")
        key = request.get("key")
        if key not in state["tasks"] or gate(entry(state, key))[0] == "skip":
            raise ValueError("reconcile task metadata before resuming dispatch")
        if state["tasks"][key]["hold"] != "human":
            raise ValueError("task has no dispatcher human hold")
        state["tasks"][key]["hold"] = None
        state["tasks"][key]["not_before"] = clock.date().isoformat()
        return {"resumed": key}
    if command == "notify":
        event_id = require_text(request.get("event_id"), "event id")
        text = require_text(request.get("text"), "notification text")
        old = state["outbox"].get(event_id)
        if old and old["text"] != text:
            raise ValueError("event id already used with different notification text")
        if not old:
            state["outbox"][event_id] = {"text": text, "status": "pending", "receipt": None,
                "uuid": str(uuid.uuid5(uuid.UUID(state["queue_id"]), event_id))}
        return state["outbox"][event_id]
    if command == "notification_result":
        item = state["outbox"][request["event_id"]]
        status = request.get("status")
        if status not in ("pending", "unknown", "failed", "sent"):
            raise ValueError("invalid notification status")
        if item["status"] == "sent" and status != "sent":
            raise ValueError("confirmed notification cannot be downgraded")
        if status == "sent":
            require_text(request.get("receipt"), "confirmed delivery receipt")
        item["status"] = status
        item["receipt"] = request.get("receipt", item["receipt"])
        return item
    raise ValueError("unknown command: " + str(command))


def execute(path, request, now=None):
    path = Path(path)
    clock = datetime.fromisoformat(now) if now else datetime.now(ZoneInfo("Asia/Shanghai"))
    if clock.tzinfo is None:
        raise ValueError("clock must include timezone")
    clock = clock.astimezone(ZoneInfo("Asia/Shanghai"))
    with locked(path):
        state = read_state(path)
        before = copy.deepcopy(state)
        result = operate(state, request, clock)
        if state != before:
            atomic_write(path, state)
        return copy.deepcopy(result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", required=True, type=Path)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--init", type=Path, metavar="PLAN_JSON", help="initialize disabled queue")
    group.add_argument("--request", type=Path, metavar="REQUEST_JSON", help="execute a ledger command")
    parser.add_argument("--now", help="ISO timestamp with offset, for isolated rehearsal only")
    args = parser.parse_args()
    try:
        if args.init:
            result = initialize(args.state, json.loads(args.init.read_text(encoding="utf-8")))
        else:
            result = execute(args.state, json.loads(args.request.read_text(encoding="utf-8")), args.now)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, KeyError, TypeError, OSError, StopIteration) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
