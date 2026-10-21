import math
import os
import unittest
from jarvis_reactor import reactor_lines,phase_at,completion_age,ripple,SPEEDS

class ReactorTests(unittest.TestCase):
    @unittest.skipUnless(os.name=='posix','Uses Ubuntu status telemetry')
    def test_tool_timestamps_follow_actual_events(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        import jarvis_status as status
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'state.json'
            with patch.dict(os.environ,{'JARVIS_STATUS_FILE':str(path)}):
                with patch.object(status.time,'time',return_value=100):
                    status.emit('processing','Checking storage.',result='running',activity_caption='Measuring storage use',activity_step='inspecting')
                self.assertEqual(status.read_state(path)['reactor_tool_started'],'100')
                with patch.object(status.time,'time',return_value=100.001):
                    status.emit('processing','Reviewing.',activity_caption='Reviewing results',activity_step='reviewing')
                self.assertEqual(status.read_state(path)['reactor_tool_returned'],'100.001')
                with patch.object(status.time,'time',return_value=120):
                    status.emit('complete','Done.',result='0')
                with patch.object(status.time,'time',return_value=130):
                    status.emit(detail='Unrelated status update.')
                self.assertEqual(status.read_state(path)['reactor_completed'],'120')

    def test_three_rings_move_independently(self):
        self.assertGreater(SPEEDS[0],0)
        self.assertLess(SPEEDS[1],0)
        self.assertEqual(len(set(abs(x) for x in SPEEDS)),3)
        data={'stage':'processing','result':'running'}
        first=reactor_lines(data,now=100)
        self.assertNotEqual(first,reactor_lines(data,now=100.4))
        self.assertTrue(any('*' in row or '#' in row for row,_ in first))

    def test_dimensions_are_unchanged_in_every_state(self):
        for large,width,height in [(True,49,31),(False,31,23)]:
            for state in ('standby','listening','processing','speaking','attention'):
                data={'stage':state,'result':'0' if state=='standby' else 'running'}
                for when in (0,1,100,100.7,10000):
                    lines=reactor_lines(data,now=when,large=large,state=state)
                    self.assertEqual(len(lines),height)
                    self.assertTrue(all(len(text)<=width for text,_ in lines))
                    self.assertIn('JARVIS',''.join(text for text,_ in lines))

    def test_quick_tool_gets_two_distinct_pulses(self):
        data={'reactor_tool_started':'100','reactor_tool_returned':'100.001'}
        self.assertEqual(ripple(data,100.3,10)[1],'*')
        self.assertEqual(ripple(data,100.9,10)[1],'+')
        self.assertIsNone(ripple(data,102,10))
        self.assertIsNone(ripple({},102,10))

    def test_completion_aligns_flashes_then_settles(self):
        data={'stage':'complete','result':'0','reactor_completed':'100'}
        self.assertAlmostEqual(completion_age(data,100.7),.7)
        for ring in range(3):
            self.assertAlmostEqual(phase_at(ring,100.7,.7)%math.tau,0)
        self.assertIn('COMPLETE',''.join(line for line,_ in reactor_lines(data,now=100.7)))
        self.assertIn('STANDBY',''.join(line for line,_ in reactor_lines(data,now=102)))
        self.assertEqual(completion_age(dict(data,attention='failed'),101),-1)

    def test_each_active_state_changes_over_time(self):
        for state in ('standby','listening','processing','speaking','attention'):
            data={'stage':state,'result':'running' if state!='standby' else '0'}
            frames=[reactor_lines(data,now=100+t*.2,state=state) for t in range(8)]
            self.assertTrue(any(frame!=frames[0] for frame in frames[1:]),state)

if __name__=='__main__':unittest.main()
