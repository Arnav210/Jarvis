"""History regression checks against isolated temporary files only."""
import importlib.util
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
