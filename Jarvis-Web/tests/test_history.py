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
            f.write('[]\n{"event":"diagnostic"}\n{"event":')
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


if __name__ == "__main__":
    unittest.main()
