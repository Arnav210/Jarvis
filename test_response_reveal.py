import os
import unittest
from jarvis_console_layout import response_glow,compose
from jarvis_reactor import reactor_lines,completion_age

class ResponseRevealTests(unittest.TestCase):
    def sample(self):
        return {'reply':'The music folder uses 139.7 MiB.','stage':'speaking','result':'running','response_ready':'100'}

    def test_answer_is_visible_immediately_and_text_is_not_animated(self):
        for now in (100,100.5,101.3,102):
            positions,_=compose(self.sample(),{},144,48,'speaking',reactor_lines,now=now)
            self.assertIn(self.sample()['reply'],' '.join(item[2] for item in positions))
            body=[item for item in positions if self.sample()['reply'] in item[2]]
            self.assertEqual(body[0][3],0)
        self.assertEqual(response_glow(self.sample(),'speaking',100),1)
        self.assertEqual(response_glow(self.sample(),'speaking',100.6),7)
        self.assertIsNone(response_glow(self.sample(),'speaking',102))

    def test_completion_uses_reactor_timestamp(self):
        data=dict(self.sample(),stage='complete',result='0',reactor_completed='110')
        self.assertAlmostEqual(completion_age(data,110.6),.6)
        self.assertEqual(response_glow(data,'standby',110.6),7)
        self.assertIsNone(response_glow(data,'standby',112))

    def test_errors_and_processing_do_not_flash(self):
        for activity in ('processing','listening','attention'):
            self.assertIsNone(response_glow(self.sample(),activity,100.5))
        self.assertIsNone(response_glow(dict(self.sample(),attention='Failed'),'speaking',100.5))
        self.assertIsNone(response_glow(dict(self.sample(),reply=''),'speaking',100.5))

    def test_only_response_edges_glow_and_layout_stays_bounded(self):
        for width,height in ((144,48),(220,58),(100,40),(80,24),(40,12)):
            positions,_=compose(self.sample(),{},width,height,'speaking',reactor_lines,now=100.6)
            occupied=set()
            for row,col,line,style,limit in positions:
                if style==7:self.assertGreaterEqual(row,11 if height>=30 else 4)
                self.assertLess(col+len(line),width)
                for x in range(col,col+len(line)):
                    self.assertNotIn((row,x),occupied)
                    occupied.add((row,x))
            if height>=30:self.assertTrue(any(item[2]=='│' and item[3]==7 for item in positions))

    @unittest.skipUnless(os.name=='posix','Ubuntu status lifecycle')
    def test_repeated_reply_and_status_updates_do_not_restart_reveal(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        import jarvis_status as status
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'state.json'
            with patch.dict(os.environ,{'JARVIS_STATUS_FILE':str(path)}):
                with patch.object(status.time,'time',return_value=100):
                    status.emit('speaking',reply='An answer',result='running')
                with patch.object(status.time,'time',return_value=101):
                    status.emit('speaking','Still speaking.',reply='An answer')
                self.assertEqual(status.read_state(path)['response_ready'],'100')
                with patch.object(status.time,'time',return_value=110):
                    status.emit('complete',result='0')
                with patch.object(status.time,'time',return_value=120):
                    status.emit(detail='Another status update.')
                data=status.read_state(path)
                self.assertEqual(data['response_ready'],'100')
                self.assertEqual(data['reactor_completed'],'110')
                self.assertIsNone(response_glow(data,'standby',120))
                status.emit('starting',reply='',result='running')
                self.assertNotIn('response_ready',status.read_state(path))

if __name__=='__main__':unittest.main()
