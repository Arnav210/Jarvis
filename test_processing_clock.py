"""Check elapsed timing, telemetry lifecycle, and animation without room audio."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import jarvis_console_layout as layout
import jarvis_status as status
import jarvis_computer as computer
import jarvis_ai as ai

class ProcessingClockTests(unittest.TestCase):
    def test_live_frames_continue_without_new_status_events(self):
        data={'started':'90','processing_started':'100','updated':100,'stage':'processing','result':'running','model_pending':'1'}
        first,_=layout.compose(data,{},144,48,'processing',status.reactor_lines,now=161)
        later,_=layout.compose(data,{},144,48,'processing',status.reactor_lines,now=162.3)
        self.assertIn('01:01',layout.status_line(data,'processing',161)[0])
        self.assertIn('01:02',layout.status_line(data,'processing',162.3)[0])
        self.assertIn('MODEL WORKING',' '.join(x[2] for x in later))
        self.assertNotEqual(first,later)
        self.assertNotEqual(status.reactor_lines(data,now=161),status.reactor_lines(data,now=162.3))

    def test_processing_clock_is_not_reset_by_progress(self):
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'state.json'
            with patch.dict(os.environ,{'JARVIS_STATUS_FILE':str(target)}):
                with patch.object(status.time,'time',return_value=100):
                    status.emit('starting',started='100',result='running')
                with patch.object(status.time,'time',return_value=110):
                    status.emit('routing','Matching request.')
                with patch.object(status.time,'time',return_value=115):
                    status.emit('processing',model_pending='1')
                with patch.object(status.time,'time',return_value=170):
                    status.emit('processing','Still waiting for local model.')
                data=status.read_state(target)
                self.assertEqual(layout.processing_seconds(data,175),65)
                self.assertEqual(data['model_pending'],'1')
                with patch.object(status.time,'time',return_value=180):
                    status.emit('speaking','Reply ready.')
                data=status.read_state(target)
                self.assertEqual(layout.processing_seconds(data,250),70)
                self.assertEqual(data['model_pending'],'0')
                self.assertEqual(status.visual_state(data),'speaking')
                with patch.object(status.time,'time',return_value=260):
                    status.emit('starting',started='260',result='running')
                    status.emit('routing','Next request.')
                self.assertEqual(layout.processing_seconds(status.read_state(target),263),3)

    def test_timeout_clears_model_indicator(self):
        for module,invoke in [(computer,lambda:computer.call_model([],1)),(ai,lambda:ai.call_ollama([]))]:
            events=[]
            emitter=lambda *args,**kwargs:events.append((args,kwargs))
            with patch.object(module.urllib.request,'urlopen',side_effect=TimeoutError('test timeout')):
                # Computer imports the emitter at the start of each call; AI binds it at import.
                with patch.object(status,'emit',emitter),patch.object(ai,'status_emit',emitter):
                    with self.assertRaises(TimeoutError):invoke()
            self.assertEqual(events[0][1]['model_pending'],'1')
            self.assertEqual(events[-1][1]['model_pending'],'0')

    def test_small_and_large_displays_fit(self):
        data={'stage':'processing','result':'running','processing_started':'100','model_pending':'1'}
        for width,height in [(144,48),(220,58),(100,40),(80,24),(40,12)]:
            positions,_=layout.compose(data,{},width,height,'processing',status.reactor_lines,now=175)
            occupied=set()
            for row,col,text,style,limit in positions:
                self.assertLess(col+layout.cells(text),width)
                for x in range(col,col+layout.cells(text)):
                    self.assertNotIn((row,x),occupied)
                    occupied.add((row,x))
            self.assertIn('01:15',' '.join(x[2] for x in positions))

if __name__=='__main__':unittest.main()
