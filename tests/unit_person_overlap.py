"""Check real monitor output using synthetic manifests and an isolated HOME."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

MONITOR = Path(__file__).resolve().parents[1] / 'src/jarvis/vision/object_monitor.py'


def detection(prompt, score, box):
    return {'prompt': prompt, 'score': score, 'box': box}


class PersonOverlapTests(unittest.TestCase):
    def monitor(self, detections):
        with tempfile.TemporaryDirectory() as directory:
            home=Path(directory)
            project=home/'Jarvis'
            run=project/'Masks/runs/synthetic'
            run.mkdir(parents=True)
            state_dir=project/'object_monitor/object_monitor'
            state_dir.mkdir(parents=True)
            (project/'Masks/latest').symlink_to(run,target_is_directory=True)
            manifest={'run_id':'synthetic','captured_at':'2026-10-23T09:00:00-07:00',
                      'image_size':{'width':640,'height':480},'detections':detections}
            (run/'manifest.json').write_text(json.dumps(manifest))
            env=dict(os.environ,HOME=str(home))
            result=subprocess.run([sys.executable,str(MONITOR)],env=env,capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr)
            return json.loads((run/'changes.json').read_text()),json.loads((state_dir/'object_state.json').read_text())

    def test_overlapping_and_contained_people_all_count(self):
        report,state=self.monitor([
            detection('person',.95,[0,0,100,100]),
            detection('person',.85,[10,0,110,100]),
            detection('person',.75,[20,20,50,80]),
            detection('person',.65,[0,0,100,100])])
        self.assertEqual(report['person_count'],4)
        self.assertEqual(state['person_count'],4)
        self.assertEqual(report['person_count_method'],'sam3_score_0.50_no_overlap_filter')

    def test_confidence_cutoff_keeps_exactly_fifty_percent(self):
        report,state=self.monitor([detection('person',score,[0,0,100,100]) for score in [.95,.50,.499,.10]])
        self.assertEqual(report['person_count'],2)
        self.assertEqual(state['person_count'],2)

    def test_other_classes_still_deduplicate_and_do_not_change_person_count(self):
        report,state=self.monitor([
            detection('person',.9,[0,0,100,100]),detection('person',.8,[0,0,100,100]),
            detection('chair',.9,[0,0,100,100]),detection('chair',.8,[0,0,100,100]),
            detection('laptop',.8,[0,0,100,100]),detection('laptop',.7,[20,20,40,40])])
        self.assertEqual(report['person_count'],2)
        objects=list(state['objects'].values())
        self.assertEqual(len(objects),2)

    def test_no_qualifying_people_remains_zero(self):
        report,state=self.monitor([detection('person',.49,[0,0,100,100])])
        self.assertEqual(report['person_count'],0)
        self.assertEqual(state['person_count'],0)


if __name__=='__main__':unittest.main()
