"""History regression checks against isolated temporary files only."""
import importlib.util
import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1] / "backend"))
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("jarvis_web_server", Path(__file__).resolve().parents[1] / "backend" / "server.py")
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        server.MONITOR_DIR = Path(self.directory.name)

    def write_events(self, count):
        events = [{"event": "object_missing", "message": f"Synthetic item {i}", "time": "2026-10-22T12:00:00Z"} for i in range(count)]
        (server.MONITOR_DIR / "events.jsonl").write_text("\n".join(json.dumps(e) for e in events)+"\n", encoding="utf-8")

    def test_absent_inventory_is_unavailable_not_zero(self):
        result = server.get_object_monitor(50, None)
        self.assertFalse(result["state_available"])
        self.assertIsNone(result["person_count"])
        self.assertEqual(result["recent_events"], [])

    def test_pages_have_no_duplicates_when_new_events_arrive(self):
        self.write_events(105)
        first = server.get_object_monitor(50, None)
        self.assertEqual([e["sequence"] for e in first["recent_events"]], list(range(56, 106)))
        self.write_events(108)
        second = server.get_object_monitor(50, first["next_before"])
        self.assertEqual([e["sequence"] for e in second["recent_events"]], list(range(6, 56)))
        last = server.get_object_monitor(50, second["next_before"])
        self.assertEqual([e["sequence"] for e in last["recent_events"]], list(range(1, 6)))
        self.assertFalse(last["has_more"])

    def test_partial_lines_and_unknown_events_do_not_hide_history(self):
        self.write_events(3)
        with (server.MONITOR_DIR / "events.jsonl").open("a", encoding="utf-8") as f:
            f.write('[]\n{"event":[]}\n{"event":{}}\n{"event":"diagnostic"}\n{"event":')
        result = server.get_object_monitor(2, None)
        self.assertEqual(result["total_events"], 3)
        self.assertEqual(len(result["recent_events"]), 2)
        self.assertTrue(result["has_more"])

    def test_corrupt_inventory_keeps_valid_history(self):
        self.write_events(2)
        (server.MONITOR_DIR / "object_state.json").write_text('{"objects":', encoding="utf-8")
        result = server.get_object_monitor(50, None)
        self.assertFalse(result["state_available"])
        self.assertEqual(len(result["recent_events"]), 2)
        self.assertTrue(result["warnings"])

    def test_inventory_and_timestamp_are_reported(self):
        state = {"objects": {"synthetic": {"status": "present"}}, "person_count": 0, "last_run_id": "synthetic-run"}
        (server.MONITOR_DIR / "object_state.json").write_text(json.dumps(state), encoding="utf-8")
        result = server.get_object_monitor(50, None)
        self.assertTrue(result["state_available"])
        self.assertEqual(result["person_count"], 0)
        self.assertEqual(result["objects"], state["objects"])
        self.assertIsNotNone(result["updated_at"])


class OccupancyTests(unittest.TestCase):
    def setUp(self):
        from unittest.mock import patch
        from zoneinfo import ZoneInfo
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        server.MONITOR_DIR = self.root / 'monitor'
        server.MONITOR_DIR.mkdir()
        server.RUNS_DIR = self.root / 'runs'
        server.RUNS_DIR.mkdir()
        self.zone_patch = patch.object(server, 'room_timezone', return_value=(ZoneInfo('America/Los_Angeles'), 'America/Los_Angeles'))
        self.zone_patch.start()
        self.addCleanup(self.zone_patch.stop)

    def events(self, values):
        events = [{'event':'person_count_changed','time':stamp,'data':{'current':count}} for stamp,count in values]
        (server.MONITOR_DIR / 'events.jsonl').write_text('\n'.join(json.dumps(e) for e in events))

    def capture(self, name, stamp, report):
        folder=server.RUNS_DIR/name
        folder.mkdir()
        (folder/'manifest.json').write_text(json.dumps({'captured_at':stamp}))
        (folder/'changes.json').write_text(json.dumps(report))

    def test_empty_day_does_not_invent_zero_or_carry_old_counts(self):
        self.events([('2026-10-21T16:00:00Z',12)])
        result=server.get_occupancy('2026-10-22')
        self.assertEqual(result['observations'],[])
        self.assertIsNone(result['peak'])
        self.assertEqual(result['latest_observation']['count'],12)

    def test_real_zero_is_preserved(self):
        self.events([('2026-10-22T16:00:00Z',0)])
        result=server.get_occupancy('2026-10-22')
        self.assertEqual(result['peak'],0)
        self.assertEqual(result['observations'][0]['count'],0)

    def test_camera_day_boundaries_use_local_time(self):
        self.events([('2026-10-22T06:59:59Z',99),('2026-10-22T07:00:00Z',3),('2026-10-23T06:59:59Z',7),('2026-10-23T07:00:00Z',88)])
        result=server.get_occupancy('2026-10-22')
        self.assertEqual([p['count'] for p in result['observations']],[3,7])
        self.assertEqual(result['observations'][0]['hour'],0)

    def test_unchanged_counts_are_separate_capture_observations(self):
        self.capture('2026-10-22_09-00-00','2026-10-22T09:00:00-07:00',{'person_count':5,'changes':[]})
        self.capture('2026-10-22_09-05-00','2026-10-22T09:05:00-07:00',{'person_count':5,'changes':[]})
        self.assertEqual([p['count'] for p in server.get_occupancy('2026-10-22')['observations']],[5,5])

    def test_legacy_change_is_not_duplicated_at_processing_time(self):
        event={'event':'person_count_changed','time':'2026-10-22T16:04:00Z','data':{'current':17}}
        self.capture('2026-10-22_09-00-00','2026-10-22T09:00:00-07:00',{'changes':[event]})
        self.events([(event['time'],17)])
        points=server.get_occupancy('2026-10-22')['observations']
        self.assertEqual(len(points),1)
        self.assertEqual(points[0]['hour'],9)

    def test_latest_state_uses_capture_time_instead_of_poll_time(self):
        self.capture('2026-10-22_09-00-00','2026-10-22T09:00:00-07:00',{'changes':[]})
        (server.MONITOR_DIR/'object_state.json').write_text(json.dumps({'last_run_id':'2026-10-22_09-00-00','person_count':8}))
        self.assertEqual(server.get_occupancy('2026-10-22')['observations'][0]['hour'],9)

    def test_invalid_counts_and_timestamps_are_ignored(self):
        self.events([('2026-10-22T16:00:00Z',True),('2026-10-22T16:01:00Z',-1),('bad time',7),('2026-10-22T16:03:00Z',4)])
        self.assertEqual([p['count'] for p in server.get_occupancy('2026-10-22')['observations']],[4])

    def test_invalid_date_rejected_and_dst_midnights_correct(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException):
            server.get_occupancy('2026-02-31')
        result=server.get_occupancy('2026-11-01')
        self.assertTrue(result['start'].endswith('-07:00'))
        self.assertTrue(result['end'].endswith('-08:00'))


if __name__ == "__main__":
    unittest.main()


class DailyCaptureTests(unittest.TestCase):
    def setUp(self):
        from unittest.mock import patch
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.patch = patch.object(server, "RUNS_DIR", Path(self.directory.name))
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.zone_patch = patch.dict(server.os.environ, {"TZ": "America/Los_Angeles"})
        self.zone_patch.start()
        self.addCleanup(self.zone_patch.stop)

    def capture(self, name, stamp=None):
        folder = server.RUNS_DIR / name
        folder.mkdir()
        (folder / "original.jpg").write_bytes(b"synthetic")
        if stamp:
            (folder / "manifest.json").write_text(json.dumps({"captured_at": stamp, "detections": []}))
        return folder

    def test_selected_day_includes_46_frames_and_extra_manual_captures(self):
        for i in range(47):
            self.capture(f"2026-10-22_08-{i:02d}-00")
        self.capture("2026-10-21_15-40-00")
        result = server.get_latest_runs("2026-10-22", 46)
        self.assertEqual(len(result["runs"]), 47)
        self.assertEqual(result["day"], "2026-10-22")
        self.assertEqual(result["runs"][0]["folder"], "2026-10-22_08-46-00")
        self.assertTrue(all(r["folder"].startswith("2026-10-22") for r in result["runs"]))

    def test_latest_default_has_46_frames(self):
        for i in range(48):
            self.capture(f"2026-10-22_08-{i:02d}-00")
        result = server.get_latest_runs()
        self.assertEqual(len(result["runs"]), 46)
        self.assertEqual(result["runs"][0]["folder"], "2026-10-22_08-47-00")

    def test_manifest_uses_camera_date_not_utc_date_or_folder_name(self):
        self.capture("2026-10-23_01-00-00", "2026-10-23T01:00:00Z")
        result = server.get_latest_runs("2026-10-22")
        self.assertEqual(len(result["runs"]), 1)
        self.assertTrue(result["runs"][0]["captured_at"].startswith("2026-10-22T18:00:00"))
        self.assertEqual(server.get_latest_runs("2026-10-23")["runs"], [])

    def test_empty_day_and_invalid_dates(self):
        self.assertEqual(server.get_latest_runs("2026-10-20")["runs"], [])
        for day in ["2026-02-30", "20261022", "bad-date"]:
            with self.assertRaises(server.HTTPException):
                server.get_latest_runs(day)


class CaptureStatusTests(unittest.TestCase):
    def setUp(self):
        from unittest.mock import patch
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.footage = self.root / 'Footage'
        self.runs = self.root / 'runs'
        self.footage.mkdir()
        self.runs.mkdir()
        unit = Path(__file__).resolve().parents[2] / 'systemd/user/jarvis-capture.timer'
        self.expressions = [line.split('=', 1)[1] for line in unit.read_text().splitlines() if line.startswith('OnCalendar=')]
        self.runtime = {
            'jarvis-capture.timer': {'ActiveState': 'active', 'calendar': self.expressions, 'NextElapseUSecRealtime': 'Fri 2026-10-23 08:20:00 PDT'},
            'jarvis-capture.service': {'ActiveState': 'inactive', 'Result': 'success'},
            'jarvis-sam3.service': {'ActiveState': 'active'}}
        active_zone = patch.dict(server.os.environ, {'TZ': 'America/Los_Angeles'})
        active_zone.start()
        self.addCleanup(active_zone.stop)

    def photo(self, stamp, count=None):
        value = server.datetime.fromisoformat(stamp)
        name = value.strftime('%Y-%m-%d_%H-%M-%S_%f')
        (self.footage / (name + '.jpg')).write_bytes(b'synthetic')
        if count is not None:
            folder = self.runs / name
            folder.mkdir()
            (folder / 'changes.json').write_text(json.dumps({'person_count': count}))

    def status(self, stamp):
        return server.build_capture_status(server.datetime.fromisoformat(stamp), self.runtime, self.footage, self.runs)

    def test_weekends_have_no_slots_or_missing_picture_alerts(self):
        for stamp in ("2026-10-24T12:00:00-07:00", "2026-10-25T12:00:00-07:00",
                      "2026-11-01T12:00:00-08:00"):
            with self.subTest(stamp=stamp):
                data = self.status(stamp)
                self.assertEqual(data['state'], 'outside_hours')
                self.assertEqual(data['planned_today'], 0)
                self.assertEqual(data['missed_today'], 0)
                self.assertIn('Weekend', data['message'])

    def test_schedule_has_46_slots_with_inclusive_endpoints(self):
        slots, zone = server.capture_slots(server.date(2026, 10, 23), self.expressions)
        self.assertEqual(len(slots), 46)
        self.assertEqual(slots[0].strftime('%H:%M'), '08:10')
        self.assertEqual(slots[-1].strftime('%H:%M'), '15:40')
        self.assertEqual(zone, 'America/Los_Angeles')

    def test_waiting_with_completed_zero_count(self):
        self.photo('2026-10-23T08:10:00-07:00', 0)
        data = self.status('2026-10-23T08:15:00-07:00')
        self.assertEqual(data['state'], 'waiting')
        self.assertEqual(data['analysis'], 'complete')
        self.assertEqual(data['people_count'], 0)
        self.assertEqual(data['captured_today'], 1)
        self.assertEqual(data['processed_today'], 1)
        self.assertEqual(data['missed_today'], 0)
        self.assertEqual(data['next_capture'], '2026-10-23T08:20:00-07:00')

    def test_pending_analysis_and_delayed_analysis(self):
        self.photo('2026-10-23T08:10:00-07:00')
        self.assertEqual(self.status('2026-10-23T08:12:00-07:00')['state'], 'processing')
        data = self.status('2026-10-23T08:30:00-07:00')
        self.assertEqual(data['state'], 'problem')
        self.assertEqual(data['analysis'], 'delayed')

    def test_missing_capture_has_a_one_minute_grace_period(self):
        self.assertEqual(self.status('2026-10-23T08:10:30-07:00')['state'], 'waiting')
        self.assertEqual(self.status('2026-10-23T08:12:00-07:00')['state'], 'problem')

    def test_manual_photos_do_not_inflate_slot_progress(self):
        self.photo('2026-10-23T08:10:00-07:00', 2)
        self.photo('2026-10-23T08:10:30-07:00', 2)
        self.photo('2026-10-23T08:14:00-07:00', 3)
        data = self.status('2026-10-23T08:15:00-07:00')
        self.assertEqual(data['captured_today'], 1)
        self.assertEqual(data['other_pictures_today'], 2)

    def test_outside_hours_and_setup_day_do_not_report_missed_slots(self):
        self.runtime['enabled_since'] = '2026-10-23T22:00:00-07:00'
        data = self.status('2026-10-23T23:00:00-07:00')
        self.assertEqual(data['state'], 'outside_hours')
        self.assertEqual(data['missed_today'], 0)

    def test_paused_or_unavailable_scheduler_never_claims_healthy(self):
        self.runtime['jarvis-capture.timer']['ActiveState'] = 'inactive'
        data = self.status('2026-10-23T08:15:00-07:00')
        self.assertEqual(data['state'], 'paused')
        self.assertIsNone(data['next_capture'])
        self.runtime.clear()
        self.assertEqual(self.status('2026-10-23T08:15:00-07:00')['state'], 'unavailable')

    def test_stopped_watcher_and_failed_capture_are_problems(self):
        self.runtime['jarvis-sam3.service']['ActiveState'] = 'inactive'
        self.assertEqual(self.status('2026-10-23T08:15:00-07:00')['state'], 'problem')
        self.runtime['jarvis-sam3.service']['ActiveState'] = 'active'
        self.photo('2026-10-23T08:10:00-07:00', 2)
        self.runtime['jarvis-capture.service']['Result'] = 'exit-code'
        self.assertEqual(self.status('2026-10-23T08:15:00-07:00')['state'], 'problem')

    def test_pacific_midnight_resets_daily_progress(self):
        self.photo('2026-10-22T15:40:00-07:00', 4)
        data = self.status('2026-10-23T07:01:00+00:00')
        self.assertEqual(data['captured_today'], 0)
        self.assertEqual(data['state'], 'outside_hours')


    def test_older_pending_analysis_is_not_hidden_by_a_newer_success(self):
        self.photo('2026-10-23T08:10:00-07:00')
        self.photo('2026-10-23T08:20:00-07:00', 3)
        data = self.status('2026-10-23T08:27:00-07:00')
        self.assertEqual(data['state'], 'problem')
        self.assertEqual(data['analysis'], 'complete')
        self.assertEqual(data['captured_today'], 2)
        self.assertEqual(data['processed_today'], 1)

    def test_unrecognized_timer_rule_is_unavailable(self):
        self.runtime['jarvis-capture.timer']['calendar'] = ['Mon..Fri *:00:00']
        self.assertEqual(self.status('2026-10-23T08:15:00-07:00')['state'], 'unavailable')

    def test_runtime_query_is_read_only_cached_and_fails_closed(self):
        from unittest.mock import patch
        text = 'TimersCalendar={ OnCalendar=' + self.expressions[0] + ' ; next_elapse=n/a }\nId=jarvis-capture.timer\nActiveState=active\n'
        result = server.subprocess.CompletedProcess([], 0, stdout=text, stderr='')
        with patch.object(server, '_runtime_cache', (0, {})), patch.object(server.subprocess, 'run', return_value=result) as run:
            first = server.capture_runtime()
            self.assertEqual(first['jarvis-capture.timer']['calendar'], self.expressions[:1])
            self.assertEqual(first, server.capture_runtime())
            self.assertEqual(run.call_count, 1)
            self.assertIn('show', run.call_args.args[0])
            self.assertNotIn('start', run.call_args.args[0])
        with patch.object(server, '_runtime_cache', (0, {})), patch.object(server.subprocess, 'run', side_effect=server.subprocess.TimeoutExpired('systemctl', 3)):
            self.assertEqual(server.capture_runtime(), {})
