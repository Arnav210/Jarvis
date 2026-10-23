"""Exercise the capture report expression without running camera/model code."""
import ast
from pathlib import Path
import unittest

class CaptureCountReportTests(unittest.TestCase):
    def report(self, count):
        path=Path(__file__).resolve().parents[1]/'src/jarvis/vision/object_monitor.py'
        tree=ast.parse(path.read_text())
        node=next(n for n in ast.walk(tree) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='report' for t in n.targets))
        namespace={'current_person_count':count,'manifest':{'captured_at':'2026-10-22T09:00:00-07:00'},'run_id':'synthetic','previous_run_id':'previous','RUN_EVENTS':[],'change_types':set()}
        exec(compile(ast.Module(body=[node],type_ignores=[]),str(path),'exec'),namespace)
        return namespace['report']

    def test_unchanged_count_is_saved_with_no_change_events(self):
        report=self.report(7)
        self.assertEqual(report['person_count'],7)
        self.assertEqual(report['changes'],[])
        self.assertEqual(report['observed_at'],'2026-10-22T09:00:00-07:00')

    def test_empty_room_count_is_not_omitted(self):
        self.assertEqual(self.report(0)['person_count'],0)

if __name__=='__main__': unittest.main()
