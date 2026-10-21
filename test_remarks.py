import unittest
from unittest.mock import patch
from jarvis_remarks import schedule,current_remark,THRESHOLDS,LINES
import jarvis_console_layout as layout

class RemarkTests(unittest.TestCase):
    def data(self):
        return {'started':'100','processing_started':'110','result':'running','model_pending':'1','stage':'processing'}

    def test_one_decision_per_threshold_and_stable_on_redraw(self):
        for seed in range(500):
            selected=schedule(str(seed))
            self.assertEqual(selected,schedule(str(seed)))
            self.assertLessEqual(len(selected),2)
            self.assertEqual(len({line for _,line in selected}),len(selected))
            self.assertTrue(all(line in LINES for _,line in selected))
        with patch('jarvis_remarks.schedule',return_value=[]):
            for tick in range(1000):
                self.assertIsNone(current_remark(self.data(),'processing',125+tick*.001))

    def test_low_probability_and_most_requests_quiet(self):
        schedules=[schedule(str(seed)) for seed in range(10000)]
        self.assertGreater(sum(not items for items in schedules)/len(schedules),.70)
        for threshold,chance in THRESHOLDS:
            observed=sum(any(t==threshold for t,_ in items) for items in schedules)/len(schedules)
            self.assertAlmostEqual(observed,chance,delta=.015)

    def test_six_seconds_fade_and_no_late_replay(self):
        with patch('jarvis_remarks.schedule',return_value=[(15,'One moment, sir.')]):
            self.assertIsNone(current_remark(self.data(),'processing',124.9))
            self.assertEqual(current_remark(self.data(),'processing',125),('"One moment, sir."',1))
            self.assertEqual(current_remark(self.data(),'processing',129),('"One moment, sir."',3))
            self.assertIsNone(current_remark(self.data(),'processing',131))
            self.assertIsNone(current_remark(self.data(),'processing',160))

    def test_reply_and_error_stop_remarks_immediately(self):
        with patch('jarvis_remarks.schedule',return_value=[(15,'One moment, sir.')]):
            for state in ('listening','speaking','standby','attention'):
                self.assertIsNone(current_remark(self.data(),state,125))
            for extra in ({'reply':'Ready'},{'attention':'Timeout'},{'result':'0'},{'model_pending':'0'}):
                self.assertIsNone(current_remark(dict(self.data(),**extra),'processing',125))

    def test_remark_does_not_displace_reactor_or_music(self):
        import jarvis_reactor
        with patch('jarvis_remarks.schedule',return_value=[(15,'One moment, sir.')]):
            for width,height in ((144,48),(220,58),(100,40),(80,24)):
                positions,_=layout.compose(self.data(),{'state':'stopped'},width,height,'processing',jarvis_reactor.reactor_lines,now=125)
                text=' '.join(row[2] for row in positions)
                self.assertIn('One moment, sir.',text)
                occupied=set()
                for row,col,line,style,limit in positions:
                    self.assertLess(col+layout.cells(line),width)
                    for x in range(col,col+layout.cells(line)):
                        self.assertNotIn((row,x),occupied)
                        occupied.add((row,x))
                if height>=40:self.assertIn('NOW PLAYING',text)

if __name__=='__main__':unittest.main()
