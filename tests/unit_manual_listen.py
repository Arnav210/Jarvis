import contextlib
import fcntl
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch,Mock
from jarvis.audio import jarvis_manual_listen as manual
from jarvis.ui import jarvis_status as status

class ManualListenTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.env=patch.dict(os.environ,{'XDG_RUNTIME_DIR':self.temp.name})
        self.env.start()

    def tearDown(self):
        self.env.stop();self.temp.cleanup()

    def test_cross_view_guard_and_stale_state(self):
        with (manual.root()/'manual-listen.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            self.assertTrue(manual.manual_active())
            with patch.object(status,'run_listen') as run:
                self.assertEqual(manual.run_manual(),75)
                run.assert_not_called()
        self.assertFalse(manual.manual_active())
        (manual.root()/'state.json').write_text(json.dumps({'result':'running','mic_active':'1','mic_updated':0}))
        with patch.object(status,'run_listen',return_value=0) as run,patch.dict(os.environ,{'JARVIS_AUDIO_FILE':'old.wav','JARVIS_STATUS_CHILD':'1','JARVIS_STATUS_DISABLE':'1'}):
            self.assertEqual(manual.run_manual(),0)
            self.assertNotIn('JARVIS_AUDIO_FILE',os.environ)
            self.assertNotIn('JARVIS_STATUS_DISABLE',os.environ)
            self.assertEqual(os.environ['JARVIS_MANUAL_TRIGGER'],'1')
            self.assertEqual(run.call_args.kwargs,{'window':False,'manual':True})

    def test_runner_lock_busy_does_not_start_child_or_duck_music(self):
        with (manual.root()/'runner.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            with patch.object(status.subprocess,'Popen') as popen,patch('jarvis.music.jarvis_music_duck.ducked') as duck:
                self.assertEqual(status.run_listen('/unused',[],window=False,manual=True),75)
                popen.assert_not_called();duck.assert_not_called()

    def test_fresh_capture_is_not_interrupted(self):
        with patch.object(manual.time,'time',return_value=100):
            (manual.root()/'state.json').write_text(json.dumps({'mic_active':'1','mic_updated':'99.8'}))
            with patch.object(status,'run_listen') as run:
                self.assertEqual(manual.run_manual(),75)
                run.assert_not_called()

    def test_ui_launch_is_detached_and_repeat_key_is_guarded(self):
        controller=manual.ManualListenController()
        child=Mock();child.poll.return_value=None
        with patch.object(manual.subprocess,'Popen',return_value=child) as popen:
            self.assertIn('Starting',controller.trigger())
            self.assertIn('Already',controller.trigger())
            self.assertEqual(popen.call_count,1)
            self.assertTrue(popen.call_args.kwargs['start_new_session'])
            self.assertEqual(popen.call_args.kwargs['stdin'],manual.subprocess.DEVNULL)
        child.poll.return_value=75
        self.assertIn('busy',controller.poll_message())

    def test_full_runner_without_microphone_capture_or_playback(self):
        script=Path(self.temp.name)/'fake-listen'
        script.write_text('#!/bin/sh\nprintf "Listening for 5 seconds...\\nTranscript: test command\\nJarvis: Test complete.\\n"\n')
        script.chmod(0o700)
        with patch.dict(os.environ,{'JARVIS_MANUAL_TRIGGER':'1'}),patch('jarvis.music.jarvis_music_duck.ducked',return_value=contextlib.nullcontext()) as duck:
            result=status.run_listen(str(script),[],window=False,manual=True)
        self.assertEqual(result,0)
        data=status.read_state(manual.root()/'state.json')
        self.assertEqual(data['stage'],'complete')
        self.assertEqual(data['transcript'],'test command')
        self.assertEqual(data['reply'],'Test complete.')
        duck.assert_called_once()

if __name__=='__main__':unittest.main()
