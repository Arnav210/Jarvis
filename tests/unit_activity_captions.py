"""Activity captions must reflect real operations and preserve the console layout."""
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from jarvis.assistant import jarvis_activity as activity
from jarvis.computer import jarvis_computer as computer
from jarvis.ui import jarvis_console_layout as layout
from jarvis.ui import jarvis_status as status
from jarvis.assistant import jarvis_ai as ai

class ActivityCaptionTests(unittest.TestCase):
    def test_real_controller_emits_operation_sequence(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            music=root/'Jarvis/data/music';music.mkdir(parents=True)
            (music/'sample.mp3').write_bytes(b'a'*100)
            path=root/'state.json'
            replies=iter([
                {'role':'assistant','tool_calls':[{'function':{'name':'inspect_path','arguments':{'path':'music'}}}]},
                {'role':'assistant','content':'Done.'},
            ])
            observed=[]
            def response(*args,**kwargs):
                observed.append(status.read_state(path).get('activity_caption'))
                return io.BytesIO(json.dumps({'message':next(replies)}).encode())
            with patch.dict(os.environ,{'JARVIS_STATUS_FILE':str(path)}),patch.object(computer,'HOME',root),patch.object(computer,'PROJECT',root/'Jarvis'),patch.object(computer,'RUNTIME',root/'private'),patch.object(computer.urllib.request,'urlopen',side_effect=response):
                status.emit('starting',result='running',started='100')
                answer=computer.ask('How big is the music folder?')
                self.assertIn('100.0 B',answer)
                data=status.read_state(path)
                captions=[entry[1] for entry in data['activity_events']]
                self.assertEqual(captions,['Choosing the next inspection','Measuring storage use','Reviewing the inspection results','Preparing the measured response'])
                self.assertEqual(observed,['Choosing the next inspection','Reviewing the inspection results'])
                self.assertEqual(data['model_pending'],'0')
                status.emit('speaking','Playing response.')
                status.emit('complete','Finished.',result='0')
                data=status.read_state(path)
                self.assertEqual(data['activity_events'][-1][1],'Request complete')
                self.assertEqual(data['activity_step'],'complete')
                self.assertEqual(data['activity_target'],'')

    def test_general_model_caption_matches_operation(self):
        for messages,expected in [([{'role':'system','content':ai.INTENT_SYSTEM}],'Understanding the request'),([{'role':'user','content':'Hello'}],'Forming a response')]:
            events=[]
            fake=io.BytesIO(json.dumps({'message':{'role':'assistant','content':'Hello'}}).encode())
            with patch.object(ai,'status_emit',side_effect=lambda *args,**kwargs:events.append(kwargs)),patch.object(ai.urllib.request,'urlopen',return_value=fake):
                ai.call_ollama(messages)
            self.assertEqual(events[0]['activity_caption'],expected)
            self.assertEqual(events[-1]['model_pending'],'0')

    def test_tool_captions_are_specific(self):
        self.assertEqual(activity.tool_activity('inspect_path',{'view':'largest_files'})['activity_caption'],'Finding the largest files')
        self.assertEqual(activity.tool_activity('service_status',{'unit':'jarvis-wake'})['activity_target'],'jarvis-wake')
        self.assertIn('memory',activity.tool_activity('system_health',{})['activity_caption'])

    def test_current_caption_and_fast_steps_are_visible(self):
        data={'stage':'processing','result':'running','model_pending':'1','processing_started':'100','activity_caption':'Reviewing the inspection results','activity_events':[['12:00:00','Choosing the next inspection','planning',''],['12:00:30','Measuring storage use','inspecting','music'],['12:00:30','Reviewing the inspection results','reviewing','']]}
        for width,height in [(144,48),(220,58),(100,40),(80,24),(40,12)]:
            positions,_=layout.compose(data,{},width,height,'processing',status.reactor_lines,now=150)
            text=' '.join(item[2] for item in positions)
            self.assertIn('Reviewing the inspection',text)
            if height>=40:self.assertIn('Measuring storage use',text)
            occupied=set()
            for row,col,line,style,limit in positions:
                self.assertLess(col+layout.cells(line),width)
                for x in range(col,col+layout.cells(line)):
                    self.assertNotIn((row,x),occupied)
                    occupied.add((row,x))

if __name__=='__main__':unittest.main()
