from array import array
import json
import math
import os
import unittest
from unittest.mock import patch
from jarvis.audio.jarvis_mic_meter import MicMeter,meter_lines
from jarvis.ui import jarvis_console_layout as layout
from jarvis.ui.jarvis_reactor import reactor_lines

class MicMeterTests(unittest.TestCase):
    @unittest.skipUnless(os.name=='posix','Uses deployed Ubuntu wake source')
    def test_capture_audio_is_unchanged_and_meter_stops_on_failure(self):
        import ast,io,tempfile,wave,time
        from pathlib import Path
        import numpy as np
        source=(Path(__file__).resolve().parents[1] / 'src/jarvis/audio/jarvis_wake.py').read_text()
        function=next(node for node in ast.parse(source).body if isinstance(node,ast.FunctionDef) and node.name=='capture_command')
        module=ast.Module(body=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0),function],type_ignores=[])
        updates=[]
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'XDG_RUNTIME_DIR':directory}):
            namespace=dict(os=os,tempfile=tempfile,Path=Path,wave=wave,np=np,running=True,COMMAND_START_TIMEOUT=.16,COMMAND_MAX_SECONDS=1,COMMAND_MIN_SECONDS=.16,COMMAND_SILENCE_SECONDS=.16,COMMAND_RMS_THRESHOLD=450,FRAME_SAMPLES=1280,FRAME_BYTES=2560,read_frame=lambda stream,**kwargs:stream.read(2560),time=time,generation=lambda:0,begin_capture=lambda:0,end_capture=lambda token:None,listening_paused=lambda:False,log=lambda *_:None,MicMeter=lambda **kwargs:MicMeter(emit=lambda **fields:updates.append(fields),**kwargs))
            exec(compile(ast.fix_missing_locations(module),'<actual-capture-command>','exec'),namespace)
            pre=self.pcm(500)
            raw=self.pcm(1000)*2+self.pcm(0)*2
            path=namespace['capture_command'](io.BytesIO(raw),(pre,))
            with wave.open(str(path),'rb') as audio:
                self.assertEqual(audio.readframes(audio.getnframes()),pre+raw)
            self.assertEqual(updates[-1]['mic_active'],'0')
            path.unlink()
            def failed_read(_,**kwargs):raise OSError('Synthetic stream failure')
            namespace['read_frame']=failed_read
            with self.assertRaises(OSError):namespace['capture_command'](None,())
            self.assertEqual(updates[-1]['mic_active'],'0')
            self.assertEqual(list(Path(directory).glob('*.wav')),[])

    @unittest.skipUnless(os.name=='posix','Uses Unix watcher shutdown')
    def test_existing_wav_watcher_updates_and_stops_cleanly(self):
        import tempfile,time,subprocess,sys,wave
        from pathlib import Path
        from jarvis.audio import jarvis_mic_meter as module
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);path=root/'existing.wav';state=root/'state.json'
            process=None
            def read():
                try:return json.loads(state.read_text())
                except (OSError,ValueError):return {}
            try:
                with path.open('wb') as stream:
                    with wave.open(stream,'wb') as writer:
                        writer.setparams((1,2,16000,64000,'NONE','not compressed'))
                        writer.writeframesraw(self.pcm(1000));stream.flush()
                        process=subprocess.Popen([sys.executable,module.__file__,'--watch-wav',str(path),'--seconds','3'],env=dict(os.environ,JARVIS_STATUS_FILE=str(state)),stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                        deadline=time.monotonic()+3
                        while 'mic_rms_db' not in read() and time.monotonic()<deadline:time.sleep(.03)
                        self.assertEqual(read().get('mic_label'),'Sound detected')
                        writer.writeframesraw(self.pcm(32767));stream.flush()
                        deadline=time.monotonic()+3
                        while read().get('mic_label')!='CLIPPING' and time.monotonic()<deadline:time.sleep(.03)
                        self.assertEqual(read().get('mic_label'),'CLIPPING')
                process.terminate();out,err=process.communicate(timeout=3)
                self.assertEqual(process.returncode,0,err)
                self.assertEqual(read().get('mic_active'),'0')
            finally:
                if process and process.poll() is None:process.kill();process.communicate()

    def pcm(self,amplitude):
        samples=array('h',[int(amplitude*math.sin(2*math.pi*440*i/16000)) for i in range(1280)])
        import sys
        if sys.byteorder!='little':samples.byteswap()
        return samples.tobytes()

    def test_actual_samples_drive_levels_silence_sound_and_clipping(self):
        updates=[];meter=MicMeter(emit=lambda **fields:updates.append(fields))
        meter.start();meter.feed(self.pcm(0),force=True)
        self.assertEqual(updates[-1]['mic_label'],'Quiet')
        self.assertEqual(float(updates[-1]['mic_rms_db']),-96)
        meter.feed(self.pcm(1000),force=True)
        self.assertEqual(updates[-1]['mic_label'],'Sound detected')
        self.assertAlmostEqual(float(updates[-1]['mic_rms_db']),-33.3,delta=.2)
        quiet_level=json.loads(updates[-1]['mic_history'])[-1]
        meter.feed(self.pcm(32767),force=True)
        self.assertEqual(updates[-1]['mic_label'],'CLIPPING')
        self.assertGreater(json.loads(updates[-1]['mic_history'])[-1],quiet_level)
        meter.stop();self.assertEqual(updates[-1]['mic_active'],'0')

    def test_history_bounded_and_odd_chunks_handled(self):
        updates=[];meter=MicMeter(emit=lambda **fields:updates.append(fields))
        meter.start()
        for _ in range(50):meter.feed(self.pcm(1000),force=True)
        self.assertEqual(len(json.loads(updates[-1]['mic_history'])),20)
        raw=self.pcm(1000)
        meter.feed(raw[:1],force=True);meter.feed(raw[1:],force=True)
        self.assertEqual(updates[-1]['mic_label'],'Sound detected')

    def test_stale_audio_never_shows_live_bars(self):
        data={'mic_active':'1','mic_updated':'100','mic_history':'[0.2,0.8]','mic_label':'Sound detected','mic_rms_db':'-30'}
        self.assertIn('▇',meter_lines(data,100.2)[0][0])
        self.assertIn('Waiting',meter_lines(data,101)[0][0])
        self.assertIn('finished',meter_lines(dict(data,mic_active='0'),100.2)[0][0])

    def test_listening_layout_and_processing_hide_meter(self):
        data={'stage':'listening','result':'running','mic_active':'1','mic_updated':'100','mic_history':'[0.2,0.5,0.8]','mic_label':'Sound detected','mic_rms_db':'-30'}
        for width,height in ((144,48),(220,58),(100,40),(80,24),(40,12)):
            positions,_=layout.compose(data,{},width,height,'listening',reactor_lines,now=100.1)
            self.assertIn('MIC /',' '.join(item[2] for item in positions))
            occupied=set()
            for row,col,text,style,limit in positions:
                self.assertLess(col+layout.cells(text),width)
                for x in range(col,col+layout.cells(text)):
                    self.assertNotIn((row,x),occupied)
                    occupied.add((row,x))
        positions,_=layout.compose(dict(data,stage='processing'),{},144,48,'processing',reactor_lines,now=100.1)
        self.assertNotIn('MIC /',' '.join(item[2] for item in positions))

if __name__=='__main__':unittest.main()
