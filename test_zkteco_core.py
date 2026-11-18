#!/usr/bin/env python3
"""Unit tests for headless core (no device / no network)."""

import json
import os
import tempfile
import unittest
from datetime import datetime
from unittest import mock

import zkteco_core as core


class TestNormalize(unittest.TestCase):
    def test_token_strips_bearer_and_space(self):
        self.assertEqual(
            core.normalize_cloud_token("  Bearer  abc def\n"),
            "abcdef",
        )

    def test_url_strips_sync(self):
        self.assertEqual(
            core.normalize_cloud_base_url(
                "https://service.rejekiamerta.com/api/attendance/sync/"
            ),
            "https://service.rejekiamerta.com/api/attendance",
        )

    def test_redact(self):
        t = "b8e8541a572d1359b4b37c63645a1325"
        r = core.redact_token(t)
        self.assertNotIn(t, r)
        self.assertIn("…", r)


class TestPayload(unittest.TestCase):
    def test_build_payload_employees(self):
        with tempfile.TemporaryDirectory() as td:
            core.set_base(td)
            core.init_db()
            cfg = {
                "user_map": {"1": "NICHOLAS", "2": "SERLI"},
            }
            punches = [
                {
                    "uid": 1,
                    "nama": "NICHOLAS",
                    "timestamp": datetime(2026, 8, 1, 8, 5, 0),
                    "punch": 0,
                    "recovered": False,
                }
            ]
            body = core.build_cloud_payload(cfg, punches=punches)
            self.assertEqual(len(body["employees"]), 2)
            self.assertEqual(body["punches"][0]["timestamp"], "2026-08-01 08:05:00")
            self.assertEqual(body["punches"][0]["uid"], 1)


class TestAnomaly(unittest.TestCase):
    def test_is_anomaly(self):
        self.assertTrue(core.is_anomaly_ts(datetime(2000, 2, 1, 10, 0, 0)))
        self.assertFalse(core.is_anomaly_ts(datetime(2026, 2, 1, 10, 0, 0)))

    def test_remap(self):
        anomaly = [
            {
                "uid": 1,
                "nama": "A",
                "timestamp": datetime(2000, 2, 1, 9, 0, 0),
                "punch": 0,
            },
            {
                "uid": 1,
                "nama": "A",
                "timestamp": datetime(2000, 2, 1, 16, 0, 0),
                "punch": 1,
            },
        ]
        from datetime import date

        out = core.remap_anomalies(anomaly, date(2026, 6, 11), "07:00", "16:00")
        self.assertEqual(len(out), 2)
        self.assertTrue(all(r["recovered"] for r in out))
        self.assertEqual(out[0]["timestamp"].date().isoformat(), "2026-06-11")


class TestConfigEnv(unittest.TestCase):
    def test_env_token_override(self):
        with tempfile.TemporaryDirectory() as td:
            core.set_base(td)
            path = os.path.join(td, "config.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"cloud_api_token": "fromfile"}, f)
            with mock.patch.dict(os.environ, {"ZKTECO_CLOUD_TOKEN": "fromenv"}):
                cfg = core.load_config(path)
            self.assertEqual(cfg["cloud_api_token"], "fromenv")


class _Att:
    def __init__(self, uid, ts, punch=0):
        self.user_id = str(uid)
        self.timestamp = ts
        self.punch = punch


class _FakeLiveConn:
    """Mimics pyzk: live_capture yields until end_live_capture, then cleans up."""

    def __init__(self, events):
        self.events = list(events)
        self.end_live_capture = False
        self.cleaned = False
        self.disconnected = False

    def live_capture(self, new_timeout=10):
        self.end_live_capture = False
        it = iter(self.events)
        while not self.end_live_capture:
            yield next(it, None)
        self.cleaned = True

    def disconnect(self):
        self.disconnected = True


class _TmpDb(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        core.set_base(self._td.name)
        core.init_db()
        self.cfg = {
            "user_map": {"1": "NICHOLAS", "5": "LISA"},
            "cloud_sync_enabled": True,
            "history_sync_time": "23:50",
        }

    def tearDown(self):
        self._td.cleanup()


class TestInsertRows(_TmpDb):
    def test_returns_only_new_rows(self):
        r1 = {"uid": 1, "nama": "N", "timestamp": datetime(2026, 11, 16, 7, 0), "punch": 0}
        r2 = {"uid": 5, "nama": "L", "timestamp": datetime(2026, 11, 16, 7, 1), "punch": 0}
        core.db_insert_attendance([r1])
        new_rows, skip = core.db_insert_attendance_rows([r1, r2])
        self.assertEqual(new_rows, [r2])
        self.assertEqual(skip, 1)
        self.assertEqual(core.db_insert_attendance([r1, r2]), (0, 2))


class TestSyncAfterPull(_TmpDb):
    def setUp(self):
        super().setUp()
        self.cache = [{"uid": 1, "nama": "N", "timestamp": datetime(2026, 11, 16, 7, 0)}]
        self.new = [{"uid": 5, "nama": "L", "timestamp": datetime(2026, 11, 16, 7, 1)}]

    def test_new_mode_without_new_rows_sends_nothing(self):
        with mock.patch.object(core, "cloud_sync") as cs:
            res = core._sync_after_pull(self.cfg, "new", self.cache, [])
        cs.assert_not_called()
        self.assertTrue(res["ok"])

    def test_new_mode_sends_only_new_rows(self):
        with mock.patch.object(core, "cloud_sync", return_value={"punches_new": 1}) as cs:
            core._sync_after_pull(self.cfg, "new", self.cache, self.new)
        self.assertEqual(cs.call_args.kwargs["punches"], self.new)

    def test_failure_marks_pending_and_next_new_sync_sends_all(self):
        with mock.patch.object(core, "cloud_sync", side_effect=RuntimeError("down")):
            res = core._sync_after_pull(self.cfg, "new", self.cache, self.new)
        self.assertFalse(res["ok"])
        self.assertEqual(core.agent_state_get("cloud_pending"), "1")
        with mock.patch.object(core, "cloud_sync", return_value={}) as cs:
            core._sync_after_pull(self.cfg, "new", self.cache, [])
        self.assertEqual(cs.call_args.kwargs["punches"], self.cache)
        self.assertEqual(core.agent_state_get("cloud_pending"), "0")

    def test_history_mode_sends_whole_db(self):
        with mock.patch.object(core, "cloud_sync", return_value={}) as cs:
            core._sync_after_pull(self.cfg, "history", self.cache, self.new)
        self.assertIsNone(cs.call_args.kwargs["punches"])


class TestHistoryDue(_TmpDb):
    def test_today_then_tomorrow_after_done(self):
        now = datetime(2026, 11, 16, 22, 0)
        self.assertEqual(core.history_sync_due_at(self.cfg, now), datetime(2026, 11, 16, 23, 50))
        core.agent_state_set("last_history_sync_date", "2026-11-16")
        self.assertEqual(core.history_sync_due_at(self.cfg, now), datetime(2026, 11, 17, 23, 50))

    def test_bad_time_falls_back(self):
        cfg = dict(self.cfg, history_sync_time="nanti")
        at = core.history_sync_due_at(cfg, datetime(2026, 11, 16, 1, 0))
        self.assertEqual((at.hour, at.minute), (23, 50))


class TestLiveSession(_TmpDb):
    def _run(self, events, until, stop_flag=None):
        conn = _FakeLiveConn(events)
        with mock.patch.object(core, "connect_device", return_value=conn), \
                mock.patch.object(core, "check_clock"), \
                mock.patch.object(core, "LIVE_BATCH_S", 0), \
                mock.patch.object(core, "cloud_sync", return_value={}) as cs:
            reason = core.live_session(self.cfg, until, stop_flag=stop_flag)
        return reason, conn, [c.kwargs["punches"] for c in cs.call_args_list]

    def test_punch_sent_and_anomaly_held(self):
        far = datetime(2099, 1, 1)
        reason, conn, sent = self._run(
            [
                _Att(5, datetime(2026, 11, 16, 7, 1)),
                None,
                _Att(5, datetime(2026, 11, 16, 7, 1)),  # duplicate: not re-sent
                _Att(1, datetime(2000, 1, 1, 0, 5)),  # clock reset
                _Att(1, datetime(2026, 11, 16, 7, 9)),  # after anomaly: ignored
            ],
            far,
        )
        self.assertEqual(reason, "anomaly")
        self.assertTrue(conn.cleaned)
        self.assertTrue(conn.disconnected)
        self.assertEqual(len(sent), 1)
        self.assertEqual([(r["uid"], r["nama"]) for r in sent[0]], [(5, "LISA")])
        self.assertEqual(core.db_count(), 1)

    def test_deadline_ends_session(self):
        past = datetime(2020, 1, 1)
        reason, conn, sent = self._run([], past)
        self.assertEqual(reason, "deadline")
        self.assertTrue(conn.cleaned)
        self.assertEqual(sent, [])

    def test_stop_flag_ends_session(self):
        reason, conn, _ = self._run([], datetime(2099, 1, 1), stop_flag=lambda: True)
        self.assertEqual(reason, "stop")
        self.assertTrue(conn.cleaned)


class _ClockConn:
    """eFace10 behaviour: set_time only sticks while the device is disabled."""

    def __init__(self, now, sticky_when_enabled=False, never=False):
        self.now = now
        self.enabled = True
        self.sticky_when_enabled = sticky_when_enabled
        self.never = never
        self.calls = []

    def get_time(self):
        return self.now

    def disable_device(self):
        self.calls.append("disable")
        self.enabled = False

    def enable_device(self):
        self.calls.append("enable")
        self.enabled = True

    def set_time(self, when):
        self.calls.append("set")
        if not self.never and (not self.enabled or self.sticky_when_enabled):
            self.now = when
        return True


class TestCheckClock(unittest.TestCase):
    def test_reset_clock_set_with_device_disabled(self):
        conn = _ClockConn(datetime(2000, 2, 1, 6, 17))
        skew = core.check_clock(conn)
        self.assertLess(skew, core.CLOCK_SKEW_MAX_S)
        self.assertEqual(conn.calls, ["disable", "set", "enable"])
        self.assertTrue(conn.enabled)

    def test_small_skew_left_alone(self):
        conn = _ClockConn(datetime.now())
        core.check_clock(conn)
        self.assertEqual(conn.calls, [])

    def test_refused_time_retried_then_reported(self):
        conn = _ClockConn(datetime(2000, 2, 1), never=True)
        skew = core.check_clock(conn)
        self.assertGreater(skew, core.CLOCK_SKEW_MAX_S)
        self.assertEqual(conn.calls.count("set"), 2)
        # Device must never be left disabled: it would stop taking punches.
        self.assertTrue(conn.enabled)

    def test_enable_runs_even_if_set_time_fails(self):
        conn = _ClockConn(datetime(2000, 2, 1))

        def boom(when):
            raise OSError("timeout")

        conn.set_time = boom
        self.assertIsNone(core.check_clock(conn))
        self.assertTrue(conn.enabled)


class TestCliParser(unittest.TestCase):
    def test_no_live_flag(self):
        import zkteco_cli

        args = zkteco_cli.build_parser().parse_args(["daemon", "--no-live"])
        self.assertTrue(args.no_live)

    def test_parser_commands(self):
        import zkteco_cli

        p = zkteco_cli.build_parser()
        args = p.parse_args(["status", "-v"])
        self.assertEqual(args.command, "status")
        self.assertTrue(args.verbose)


if __name__ == "__main__":
    unittest.main()
