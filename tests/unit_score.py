import contextlib
import os
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch
import wave

from jarvis.ui import jarvis_score as score
from jarvis.ui import jarvis_ironman as film
from jarvis.music import jarvis_music as music


class ScoreTests(unittest.TestCase):
    def test_audio_eof_uses_the_last_playhead_instead_of_wall_clock(self):
        with patch.object(score,'audio_path') as path,patch.object(score,'Soundtrack') as factory,patch('jarvis.ui.jarvis_status.emit'),patch('jarvis.computer.jarvis_reset.generation',return_value='same'),patch.object(score.time,'monotonic',return_value=0),patch.object(score.time,'sleep'):
            path.return_value.is_file.return_value=True
            player=factory.return_value
            player.position.side_effect=[53.6,None]
            player.process.poll.side_effect=[None,0]
            self.assertTrue(film.run_show())
            player.stop.assert_called_once()

    def test_measured_cues_align_shots_and_impacts(self):
        for seconds,story in score.CUES:
            self.assertAlmostEqual(score.story_time(seconds),story)
        self.assertEqual(tuple(score.story_time(t) for t in score.IMPACTS),film.HITS)
        for index,(seconds,story) in enumerate(score.CUES[:-1]):
            self.assertEqual(film.shot(score.story_time(seconds+.001)),index)
        self.assertEqual(score.story_time(-5),0)
        self.assertEqual(score.story_time(90),54)

    def test_display_clock_uses_playhead_and_smoothly_extrapolates(self):
        data={'show_started':'0','show_audio_socket':'/test/score.sock'}
        score._clock_cache.clear()
        with patch.object(score,'request',return_value=12.5) as request,patch.object(score.time,'monotonic',side_effect=[100,100.08]):
            self.assertEqual(score.elapsed(data,999),12.5)
            self.assertAlmostEqual(score.elapsed(data,999),12.58)
            request.assert_called_once()
        score._clock_cache.clear()
        with patch.object(score,'request',side_effect=OSError):
            self.assertEqual(score.elapsed({'show_started':'5','show_audio_socket':'/missing'},9),4)

    def test_library_restores_only_the_original_player_and_track(self):
        with tempfile.TemporaryDirectory() as folder:
            sock=Path(folder)/'fake-player';sock.touch()
            state={'pause':False,'pid':10,'path':'synthetic.wav'}
            def ipc(command):
                if command[0]=='get_property':return state[command[1]]
                state[command[1]]=command[2]
            with patch.object(music,'SOCKET',sock),patch.object(music,'controller_lock',return_value=contextlib.nullcontext()),patch.object(music,'ipc',side_effect=ipc):
                pause=score.LibraryPause();pause.begin()
                self.assertTrue(state['pause'])
                pause.restore();self.assertFalse(state['pause'])
                pause.begin();state['path']='new-track.wav'
                pause.restore();self.assertTrue(state['pause'])

    @unittest.skipUnless(shutil.which('mpv') and os.name=='posix','Requires the silent Linux MPV output')
    def test_real_player_clock_and_cleanup_with_null_audio(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'synthetic.wav'
            with wave.open(str(path),'wb') as audio:
                audio.setparams((1,2,22050,0,'NONE','not compressed'))
                audio.writeframes(bytes(22050*2*2))
            player=score.Soundtrack(path,Path(folder))
            original=score.subprocess.Popen
            def silent_start(command,**kwargs):
                return original([command[0],'--ao=null',*command[1:]],**kwargs)
            try:
                with patch.object(score.subprocess,'Popen',side_effect=silent_start),patch.object(score.LibraryPause,'begin'),patch.object(score.LibraryPause,'restore'):
                    player.start()
                    deadline=time.monotonic()+1.5
                    position=player.position() or 0
                    while position<.12 and time.monotonic()<deadline:
                        time.sleep(.04);position=player.position() or 0
                    self.assertGreater(position,.1)
                    score._clock_cache.clear()
                    value=score.elapsed({'show_started':'0','show_audio_socket':str(player.socket)},999)
                    self.assertTrue(0<=value<2)
                    player.stop()
                    self.assertIsNotNone(player.process.poll())
                    self.assertFalse(player.socket.exists())
            finally:
                player.stop()


if __name__=='__main__':unittest.main()
