from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml

try:
    import task_dispatch as dispatch
except ModuleNotFoundError:
    dispatch = None


class DispatchTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(dispatch, "persistent dispatcher has not been implemented")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "state.json"
        self.docs = {}
        tasks = []
        for key, day in (("a", "01"), ("b", "01"), ("c", "02"), ("d", "02"), ("e", "03")):
            docs = self.root / key
            docs.mkdir()
            self.docs[key] = docs
            self.meta(key)
            (docs / "progress.md").write_text("test evidence", encoding="utf-8")
            tasks.append({"key": key, "name": "任务" + key, "day": "2026-10-" + day,
                          "docs": str(docs), "phase": 1})
        self.plan = {"start_date": "2026-10-01", "end_date": "2026-10-03",
                     "timezone": "Asia/Shanghai", "tasks": tasks}
        dispatch.initialize(self.path, self.plan)
        self.now = "2026-10-01T08:00:00+08:00"

    def meta(self, key, **changes):
        meta = {"task_id": key, "phase": 1, "execution_mode": "auto",
                "status": "开发中", "coding_allowed": True,
                "current_stage": {"phase": 1, "status": "开发中", "task_name": "任务" + key}}
        meta.update(changes)
        (self.docs[key] / "meta.yaml").write_text(yaml.safe_dump(meta), encoding="utf-8")

    def call(self, command, **values):
        return dispatch.execute(self.path, {"command": command, **values}, now=self.now)

    def start(self):
        self.call("enable", instruction="用户启用临时测试队列")
        run = self.call("claim")["run"]
        self.call("attach", run_id=run["id"], thread_id="thread-" + run["key"])
        self.call("ack", run_id=run["id"])
        return run

    def finish(self, run, outcome="verified", released=True, **extra):
        return self.call("handoff", run_id=run["id"], outcome=outcome,
                         checkpoint="progress.md：本次检查点",
                         resources={"released": released, "evidence": "已核验无本任务运行资源"},
                         evidence={"checks": "55 tests", "real_flow": "page/api/db assertions",
                                   "review": "review passed", "remote": "SHA matched"}, **extra)

    def test_default_disabled_and_outside_hours(self):
        self.assertEqual(self.call("tick")["action"], "disabled")
        self.call("enable", instruction="启用")
        for now in ("2026-10-01T07:59:59+08:00", "2026-10-01T18:00:00+08:00",
                    "2026-10-04T08:00:00+08:00"):
            self.now = now
            self.assertEqual(self.call("claim")["action"], "outside_window")

    def test_move_future_tasks_preserves_running_history_and_is_idempotent(self):
        run = self.start()
        self.finish(run, outcome="checkpoint")
        before = self.call("status")
        request = dict(command_id="move-e", instruction="第3天任务挪到第2天",
                       keys=["e"], day="2026-10-02")
        result = self.call("move", **request)
        self.assertEqual(self.call("move", **request), result)
        after = self.call("status")
        for field in ("enabled", "active", "runs", "days", "outbox"):
            self.assertEqual(after[field], before[field])
        self.assertEqual(dispatch.entry(after, "e")["day"], "2026-10-02")
        self.assertEqual(after["tasks"]["e"]["not_before"], "2026-10-02")
        self.now = "2026-10-02T08:00:00+08:00"
        self.call("tick")
        self.assertEqual(self.call("status")["days"]["2026-10-02"], ["a", "b", "c"])

    def test_move_rejects_started_tasks_materialized_days_and_bad_requests(self):
        self.start()
        for values in ({"keys": ["a"], "day": "2026-10-02"},
                       {"keys": ["b"], "day": "2026-10-02"},
                       {"keys": ["e"], "day": "2026-10-01"},
                       {"keys": ["c", "unknown"], "day": "2026-10-03"},
                       {"keys": ["e", "e"], "day": "2026-10-02"},
                       {"keys": [], "day": "2026-10-02"},
                       {"keys": ["e"], "day": "2026-10-04"}):
            before = self.path.read_bytes()
            with self.subTest(values=values), self.assertRaises(ValueError):
                self.call("move", command_id="bad", instruction="改期", **values)
            self.assertEqual(self.path.read_bytes(), before)

    def test_move_does_not_clear_pause_or_allow_command_reuse_with_new_payload(self):
        self.meta("e", status="暂停中", current_stage={"phase": 1, "status": "暂停中"})
        self.call("move", command_id="move-e", instruction="改期", keys=["e"], day="2026-10-02")
        self.assertEqual(dispatch.gate(dispatch.entry(self.call("status"), "e")), ("skip", "暂停中"))
        before = self.path.read_bytes()
        with self.assertRaises(ValueError):
            self.call("move", command_id="move-e", instruction="改期", keys=["e"], day="2026-10-03")
        self.assertEqual(self.path.read_bytes(), before)

    def test_day_emptied_by_move_still_accepts_overdue_work(self):
        self.call("move", command_id="move-e", instruction="提前e", keys=["e"], day="2026-10-02")
        self.call("enable", instruction="启用")
        self.now = "2026-10-03T08:00:00+08:00"
        self.assertEqual(self.call("tick")["key"], "a")
        self.assertEqual(self.call("status")["days"]["2026-10-03"], ["a", "b", "c"])

    def test_paused_today_tasks_do_not_displace_moved_or_overdue_work(self):
        for key in ("c", "d"):
            self.meta(key, status="暂停中", current_stage={"phase": 1, "status": "暂停中"})
        self.call("move", command_id="move-e", instruction="提前e", keys=["e"], day="2026-10-02")
        self.call("enable", instruction="启用")
        self.now = "2026-10-02T08:00:00+08:00"
        self.assertEqual(self.call("tick")["skipped"], {"c": "暂停中", "d": "暂停中"})
        self.assertEqual(self.call("status")["days"]["2026-10-02"], ["a", "b", "e"])

    def test_serial_reservation_survives_restart_and_unknown_send(self):
        self.call("enable", instruction="启用")
        first = self.call("claim")["run"]
        self.assertEqual(self.call("claim")["action"], "reconcile")
        self.assertEqual(self.call("status")["active"]["id"], first["id"])
        with self.assertRaises(ValueError):
            self.call("attach", run_id="wrong", thread_id="thread-a")
        self.call("attach", run_id=first["id"], thread_id="thread-a")
        with self.assertRaises(ValueError):
            self.call("attach", run_id=first["id"], thread_id="another")

    def test_two_simultaneous_claims_reserve_only_one(self):
        self.call("enable", instruction="启用")
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.call("claim"), range(2)))
        self.assertEqual(sorted(r["action"] for r in results), ["dispatch", "reconcile"])
        self.assertEqual(len(self.call("status")["runs"]), 1)

    def test_day_done_does_not_pull_tomorrow(self):
        a = self.start()
        self.finish(a)
        b = self.call("claim")["run"]
        self.call("attach", run_id=b["id"], thread_id="thread-b")
        self.call("ack", run_id=b["id"])
        self.finish(b)
        self.assertEqual(self.call("claim")["action"], "day_done")

    def test_extra_is_idempotent_and_blocked_extra_does_not_refill(self):
        a = self.start()
        self.finish(a)
        b = self.call("claim")["run"]
        self.call("attach", run_id=b["id"], thread_id="thread-b")
        self.call("ack", run_id=b["id"])
        self.finish(b)
        request = {"command_id": "user-message-1", "instruction": "继续处理后面的任务"}
        extra = self.call("add", **request)
        self.assertEqual(extra["added"], ["c"])
        self.assertEqual(self.call("add", **request), extra)
        c = self.call("claim")["run"]
        self.call("attach", run_id=c["id"], thread_id="thread-c")
        self.call("ack", run_id=c["id"])
        self.finish(c, outcome="blocked")
        self.assertEqual(self.call("claim")["action"], "day_done")
        self.now = "2026-10-02T08:00:00+08:00"
        self.assertEqual(self.call("tick")["key"], "d")

    def test_early_completion_removed_from_original_day(self):
        self.call("enable", instruction="启用")
        self.call("add", command_id="extra", instruction="先处理c", key="c")
        # Run today's two tasks, then the explicitly added task.
        for key in ("a", "b", "c"):
            run = self.call("claim")["run"]
            self.assertEqual(run["key"], key)
            self.call("attach", run_id=run["id"], thread_id="thread-" + key)
            self.call("ack", run_id=run["id"])
            self.finish(run)
        self.now = "2026-10-02T08:00:00+08:00"
        self.call("tick")
        self.assertEqual(self.call("status")["days"]["2026-10-02"], ["d"])

    def test_carryover_displaces_next_days_work(self):
        a = self.start()
        self.now = "2026-10-01T18:00:00+08:00"
        self.assertEqual(self.call("tick")["action"], "stop_requested")
        self.finish(a, outcome="checkpoint")
        self.now = "2026-10-02T08:00:00+08:00"
        self.assertEqual(self.call("tick")["key"], "a")
        self.assertEqual(self.call("status")["days"]["2026-10-02"], ["a", "b"])

    def test_day_checkpoint_cannot_restart_same_day(self):
        a = self.start()
        self.finish(a, outcome="checkpoint")
        self.assertEqual(self.call("tick")["key"], "b")

    def test_paused_invalid_and_changed_phase_tasks_are_skipped(self):
        self.meta("a", status="暂停中", current_stage={"phase": 1, "status": "暂停中"})
        self.call("enable", instruction="启用")
        self.assertEqual(self.call("tick")["key"], "b")
        self.meta("a", execution_mode="automatic")
        self.assertIn("a", self.call("tick")["skipped"])
        self.meta("a", phase=2)
        self.assertEqual(self.call("tick")["key"], "b")

    def test_meta_pause_stops_running_task(self):
        self.start()
        self.meta("a", status="暂停中", current_stage={"phase": 1, "status": "暂停中"})
        self.assertEqual(self.call("tick")["action"], "stop_requested")

    def test_revoked_auto_mode_stops_running_development(self):
        self.start()
        self.meta("a", execution_mode="manual")
        self.assertEqual(self.call("tick")["action"], "stop_requested")

    def test_evening_continuation_is_limited_to_explicit_existing_task(self):
        a = self.start()
        self.now = "2026-10-01T18:05:00+08:00"
        with self.assertRaises(ValueError):
            self.call("add", command_id="evening", instruction="继续", key="a")
        result = self.call("add", command_id="evening", instruction="今晚继续任务a",
                           key="a", after_hours=True)
        self.assertEqual(result["added"], ["a"])
        self.assertEqual(self.call("tick")["action"], "observe")
        self.finish(a)
        self.assertEqual(self.call("claim")["action"], "day_done")

    def test_binding_new_workspace_must_exist_before_coding(self):
        (self.docs["a"] / "meta.yaml").unlink()
        self.call("enable", instruction="启用")
        run = self.call("claim")["run"]
        self.assertEqual(run["kind"], "prepare")
        self.call("attach", run_id=run["id"], thread_id="thread-a")
        self.call("ack", run_id=run["id"])
        with self.assertRaises(ValueError):
            self.finish(run, outcome="ready")
        self.meta("a")
        self.finish(run, outcome="ready")
        self.assertEqual(self.call("claim")["action"], "dispatch")

    def test_corrupted_state_reports_error_without_reset(self):
        for bad in ([], {"version": 1, "enabled": False}):
            self.path.write_text(json.dumps(bad))
            with self.assertRaises(ValueError):
                self.call("tick")
            self.assertEqual(json.loads(self.path.read_text()), bad)

    def test_failed_atomic_replace_preserves_previous_state(self):
        from unittest.mock import patch
        original = self.path.read_bytes()
        with patch.object(dispatch.os, "replace", side_effect=OSError("disk fault")):
            with self.assertRaises(OSError):
                self.call("enable", instruction="启用")
        self.assertEqual(self.path.read_bytes(), original)

    def test_early_extra_checkpoint_resumes_before_next_days_plan(self):
        self.call("enable", instruction="启用")
        self.call("add", command_id="early-e", instruction="提前处理e", key="e")
        for key in ("a", "b", "e"):
            run = self.call("claim")["run"]
            self.assertEqual(run["key"], key)
            self.call("attach", run_id=run["id"], thread_id="thread-" + key)
            self.call("ack", run_id=run["id"])
            self.finish(run, outcome="checkpoint" if key == "e" else "verified")
        self.now = "2026-10-02T08:00:00+08:00"
        self.assertEqual(self.call("tick")["key"], "e")
        self.assertEqual(self.call("status")["days"]["2026-10-02"], ["e", "c"])

    def test_metadata_pause_does_not_occupy_future_carryover_slot(self):
        self.meta("a", status="暂停中", current_stage={"phase": 1, "status": "暂停中"})
        b = self.start()
        self.assertEqual(b["key"], "b")
        self.finish(b)
        self.now = "2026-10-02T08:00:00+08:00"
        self.call("tick")
        self.assertEqual(self.call("status")["days"]["2026-10-02"], ["c", "d"])

    def test_missing_active_for_unfinished_run_fails_closed(self):
        self.start()
        state = json.loads(self.path.read_text())
        state["active"] = None
        self.path.write_text(json.dumps(state))
        with self.assertRaises(ValueError):
            self.call("claim")

    def test_pending_thread_creation_is_saved_without_becoming_receipt(self):
        self.call("enable", instruction="启用")
        run = self.call("claim")["run"]
        self.call("creating", run_id=run["id"], client_thread_id="pending-123")
        current = self.call("status")["active"]
        self.assertEqual(current["client_thread_id"], "pending-123")
        self.assertIsNone(current["thread_id"])
        with self.assertRaises(ValueError):
            self.call("ack", run_id=run["id"])

    def test_manual_and_missing_workspace_only_prepare(self):
        self.meta("a", execution_mode="manual")
        self.call("enable", instruction="启用")
        result = self.call("claim")
        self.assertEqual(result["action"], "prepare")
        self.assertEqual(result["run"]["kind"], "prepare")

    def test_failed_cleanup_keeps_slot_until_reconciled(self):
        a = self.start()
        self.finish(a, outcome="blocked", released=False)
        self.assertEqual(self.call("claim")["action"], "cleanup_required")
        self.finish(a, outcome="blocked")
        self.assertEqual(self.call("claim")["run"]["key"], "b")

    def test_verified_requires_all_evidence(self):
        a = self.start()
        with self.assertRaises(ValueError):
            self.call("handoff", run_id=a["id"], outcome="verified", checkpoint="test",
                      resources={"released": True, "evidence": "stopped"},
                      evidence={"checks": "unit tests only"})
        self.assertIsNotNone(self.call("status")["active"])

    def test_unknown_delivery_cannot_be_released_without_receipt(self):
        self.call("enable", instruction="启用")
        a = self.call("claim")["run"]
        with self.assertRaises(ValueError):
            self.finish(a, outcome="blocked")

    def test_human_hold_requires_explicit_resume_and_meta_ready(self):
        a = self.start()
        self.finish(a, outcome="blocked")
        self.call("add", command_id="again", instruction="继续后面的任务")
        self.assertNotEqual(self.call("tick")["key"], "a")
        self.call("resume", key="a", instruction="明确恢复任务a")
        self.assertEqual(self.call("tick")["key"], "a")

    def test_resolve_interruption_requires_confirmed_ended_executor(self):
        a = self.start()
        with self.assertRaises(ValueError):
            self.call("recover", run_id=a["id"], executor_ended=False,
                      checkpoint="查询失败", resources={"released": True, "evidence": "none"})
        self.assertIsNotNone(self.call("status")["active"])
        self.call("recover", run_id=a["id"], executor_ended=True,
                  checkpoint="已查询会话确认结束，progress保存", resources={"released": True, "evidence": "stopped"})
        self.assertIsNone(self.call("status")["active"])
        self.assertEqual(self.call("status")["tasks"]["a"]["hold"], "human")

    def test_outbox_deduplicates_and_retains_unknown_send(self):
        args = {"event_id": "a:run1:blocked", "text": "任务a第1阶段受阻"}
        first = self.call("notify", **args)
        self.assertEqual(self.call("notify", **args), first)
        self.call("notification_result", event_id=args["event_id"], status="unknown", receipt="task123")
        item = self.call("status")["outbox"][args["event_id"]]
        self.assertEqual(item["uuid"], first["uuid"])
        self.assertEqual(item["status"], "unknown")
        self.call("notification_result", event_id=args["event_id"], status="sent", receipt="SUCCESS:msg123")
        self.assertEqual(self.call("notify", **args)["status"], "sent")

    def test_idempotency_key_cannot_change_request(self):
        self.call("enable", instruction="启用")
        self.call("add", command_id="one", instruction="追加一项")
        with self.assertRaises(ValueError):
            self.call("add", command_id="one", instruction="追加两项", count=2)
        self.call("notify", event_id="event", text="first")
        with self.assertRaises(ValueError):
            self.call("notify", event_id="event", text="changed")

    def test_malformed_state_is_not_reset(self):
        self.path.write_text('{"broken":', encoding="utf-8")
        with self.assertRaises(ValueError):
            self.call("tick")
        self.assertEqual(self.path.read_text(), '{"broken":')

    def test_unique_workspace_and_no_overwrite(self):
        with self.assertRaises(ValueError):
            dispatch.initialize(self.path, self.plan)
        self.plan["tasks"][1]["docs"] = self.plan["tasks"][0]["docs"]
        with self.assertRaises(ValueError):
            dispatch.initialize(self.root / "other.json", self.plan)

    def test_replan_before_first_run_preserves_notifications(self):
        self.call("notify", event_id="existing", text="此前通知")
        plan = json.loads(json.dumps(self.plan))
        plan["start_date"] = "2026-09-30"
        plan["tasks"][0]["day"] = "2026-09-30"
        self.call("replan", plan=plan, instruction="移一项到今天并启用7+1天")
        state = self.call("status")
        self.assertIn("existing", state["outbox"])
        self.assertEqual(state["tasks"]["a"]["not_before"], "2026-09-30")
        self.assertFalse(state["enabled"])

    def test_replan_rejects_active_queue_or_changed_task_identity(self):
        plan = json.loads(json.dumps(self.plan))
        plan["tasks"][0]["phase"] = 2
        with self.assertRaises(ValueError):
            self.call("replan", plan=plan, instruction="调整日期")
        self.start()
        with self.assertRaises(ValueError):
            self.call("replan", plan=self.plan, instruction="调整日期")

    def test_cli_outputs_json_and_errors_without_traceback(self):
        request = self.root / "request.json"
        request.write_text(json.dumps({"command": "status"}))
        script = Path(dispatch.__file__)
        result = subprocess.run([sys.executable, str(script), "--state", str(self.path),
                                 "--request", str(request)], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(json.loads(result.stdout)["enabled"])
        request.write_text(json.dumps({"command": "unknown"}))
        result = subprocess.run([sys.executable, str(script), "--state", str(self.path),
                                 "--request", str(request)], text=True, capture_output=True)
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("Traceback", result.stderr)

    def schedule_early_hours(self):
        self.now = "2026-09-30T16:40:00+08:00"
        return self.call("schedule", instruction="正式调度固定为凌晨执行", start="02:00",
                         last_start="13:30", end="14:00")

    def test_fixed_hours_preserve_active_run_and_explicit_today_exception(self):
        plan = json.loads(json.dumps(self.plan))
        plan["start_date"] = "2026-09-30"
        plan["tasks"][0]["day"] = "2026-09-30"
        self.call("replan", plan=plan, instruction="今天先行")
        self.now = "2026-09-30T16:00:00+08:00"
        run = self.start()
        self.call("notify", event_id="existing", text="已有通知")
        before = self.call("status")
        self.schedule_early_hours()
        after = self.call("status")
        for field in ("active", "runs", "days", "tasks", "outbox", "enabled"):
            self.assertEqual(after[field], before[field])
        self.assertEqual(after["plan"]["work_hours"],
                         {"start": "02:00", "last_start": "13:30", "end": "14:00"})
        self.assertEqual(self.call("tick")["action"], "stop_requested")
        self.call("add", command_id="today-only", instruction="今天当前任务临时继续",
                  key="a", after_hours=True)
        self.assertEqual(self.call("tick")["action"], "observe")
        self.finish(run, outcome="checkpoint")
        self.now = "2026-10-01T02:00:00+08:00"
        self.assertEqual(self.call("claim")["run"]["key"], "a")

    def test_new_schedule_dispatch_and_wind_down_boundaries(self):
        self.schedule_early_hours()
        self.call("enable", instruction="启用")
        for time, action in (("01:59:59", "outside_window"), ("02:00:00", "dispatch"),
                             ("13:29:59", "dispatch"), ("13:30:00", "wind_down"),
                             ("13:59:59", "wind_down"), ("14:00:00", "outside_window"),
                             ("14:30:00", "outside_window")):
            with self.subTest(time=time):
                self.now = f"2026-10-01T{time}+08:00"
                self.assertEqual(self.call("tick")["action"], action)
        self.now = "2026-10-01T13:30:00+08:00"
        self.assertEqual(self.call("claim")["action"], "wind_down")
        self.assertIsNone(self.call("status")["active"])

    def test_active_run_winds_down_then_stops_without_releasing_slot(self):
        self.schedule_early_hours()
        self.now = "2026-10-01T02:00:00+08:00"
        run = self.start()
        self.now = "2026-10-01T13:30:00+08:00"
        self.assertEqual(self.call("tick")["action"], "wind_down")
        self.now = "2026-10-01T14:00:00+08:00"
        self.assertEqual(self.call("tick")["action"], "stop_requested")
        self.assertEqual(self.call("status")["active"]["id"], run["id"])

    def test_scheduled_cutoff_requires_explicit_task_override(self):
        self.schedule_early_hours()
        self.now = "2026-10-01T02:00:00+08:00"
        run = self.start()
        self.now = "2026-10-01T13:30:00+08:00"
        with self.assertRaises(ValueError):
            self.call("add", command_id="late", instruction="普通追加")
        with self.assertRaises(ValueError):
            self.call("add", command_id="late", instruction="窗口外继续", after_hours=True)
        self.call("add", command_id="late", instruction="明确今天窗口外继续任务a",
                  key="a", after_hours=True)
        for time in ("13:30:00", "14:00:00"):
            self.now = f"2026-10-01T{time}+08:00"
            self.assertEqual(self.call("tick")["action"], "observe")
        self.finish(run)
        self.assertEqual(self.call("claim")["action"], "day_done")
        self.now = "2026-10-02T01:59:59+08:00"
        self.assertEqual(self.call("tick")["action"], "outside_window")
        with self.assertRaises(ValueError):
            self.call("add", command_id="early", instruction="继续", key="b", after_hours=True)

    def test_invalid_schedule_is_rejected_atomically(self):
        self.schedule_early_hours()
        before = self.path.read_bytes()
        for changes in ({"start": "2:00"}, {"last_start": "01:00"}, {"end": "24:00"},
                        {"end": "13:29"}):
            request = dict(instruction="调整", start="02:00", last_start="13:30", end="14:00")
            request.update(changes)
            with self.assertRaises(ValueError):
                self.call("schedule", **request)
            self.assertEqual(self.path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
