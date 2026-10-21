"""Exercise real MPV IPC using a silent output, never the room speaker."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import ModuleType
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

with tempfile.TemporaryDirectory(prefix='jarvis-duck-test-') as directory:
    os.environ['XDG_RUNTIME_DIR'] = directory
    os.environ['JARVIS_MUSIC_SOCKET'] = directory + '/player.sock'
    from jarvis.music import jarvis_music as music
    from music_fixture import prepare_music
    prepare_music(directory, music)
    from jarvis.music import jarvis_music_duck as duck
    player = None

    def start():
        process = subprocess.Popen(['mpv', '--no-config', '--ao=null', '--no-video', '--idle=yes', '--pause=yes', '--terminal=no', '--input-ipc-server=' + str(music.SOCKET)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            if music.property_value('pid') == process.pid:
                return process
            time.sleep(.05)
        process.terminate()
        raise AssertionError('Silent test player did not start')

    def volume(value=None):
        if value is not None:
            music.ipc(['set_property', 'volume', value])
        return music.ipc(['get_property', 'volume'])

    def equal(value):
        actual = volume()
        assert abs(actual - value) < .01, (actual, value)

    def stop_player():
        global player
        if player is not None:
            player.terminate()
            player.wait(timeout=5)
            player = None
        music.SOCKET.unlink(missing_ok=True)

    try:
        with duck.ducked():
            assert duck.STATE.exists()
            assert not music.SOCKET.exists(), 'Ducking must not start a player'
        assert not duck.STATE.exists()
        print('PASS no-player interaction has no playback side effects')

        player = start()
        volume(73)
        with duck.ducked():
            equal(14.6)
            assert duck.STATE.stat().st_mode & 0o777 == 0o600
        equal(73)
        print('PASS exact previous volume restored and state is private')

        with duck.ducked():
            music.perform('play', 'Get Lucky')
            equal(14.6)
            music.perform('pause')
            assert music.ipc(['get_property', 'pause'])
        equal(73)
        assert music.ipc(['get_property', 'pause'])
        print('PASS new song stays quiet during response; paused music remains paused')

        with duck.ducked():
            music.perform('resume')
            equal(14.6)
            music.perform('stop')
        equal(73)
        assert music.ipc(['get_property', 'idle-active'])
        print('PASS resume and stop do not unexpectedly restart music')

        for error in (RuntimeError, KeyboardInterrupt):
            try:
                with duck.ducked():
                    equal(14.6)
                    raise error('test')
            except error:
                pass
            equal(73)
        print('PASS exceptions and interruption restore volume')

        with duck.ducked():
            volume(31)
        equal(31)
        print('PASS explicit player-volume adjustment is preserved')

        volume(0)
        with duck.ducked():
            equal(0)
        equal(0)
        print('PASS zero volume is preserved')

        volume(63)
        duck.begin()
        equal(12.6)
        subprocess.run(['python3', str(Path(duck.__file__))], check=True)
        equal(63)
        assert not duck.STATE.exists()
        print('PASS separate recovery process restores abandoned session')

        with duck.ducked():
            stop_player()
            player = start()
            volume(82)
            music.perform('play', 'Billie Jean')
            equal(16.4)
        equal(82)
        music.perform('stop')
        print('PASS restarted player gets ducked and restores its own volume')

        stop_player()
        with duck.ducked():
            player = start()
            volume(91)
            music.perform('artist', 'Bruno Mars')
            equal(18.2)
        equal(91)
        print('PASS music started during initially silent session is ducked')

        with duck.ducked():
            stop_player()
        assert not duck.STATE.exists()
        print('PASS disappearing player cleans up without starting playback')

        # Exercise wake-loop placement without model packages or microphone access.
        # The real model loader is replaced below; fail if this test invokes it.
        def unexpected_model(*args, **kwargs):
            raise AssertionError('The isolated wake-loop test must not load a model')
        wake_package = ModuleType('openwakeword')
        wake_package.__path__ = []
        wake_model = ModuleType('openwakeword.model')
        wake_model.Model = unexpected_model
        with patch.dict(sys.modules, {'openwakeword': wake_package,
                                     'openwakeword.model': wake_model}):
            from jarvis.audio import jarvis_wake as wake
        player = start()
        volume(67)
        class Model:
            def predict(self, frame):
                return {'hey_jarvis': 1.0}
        class Recorder:
            stdout = object()
            def poll(self):
                return None
        wake.LISTEN_COMMAND = Path(directory) / 'fake-listen'
        wake.LISTEN_COMMAND.touch()
        wake.load_model = lambda: Model()
        wake.start_recorder = lambda: Recorder()
        wake.stop_recorder = lambda: None
        wake.read_frame = lambda stream: bytes(wake.FRAME_BYTES)
        wake.status_emit = lambda *args, **kwargs: None
        wake.open_status_window = lambda: None
        wake.time.sleep = lambda seconds: None

        for outcome in ('complete', 'capture-error', 'response-error', 'shutdown'):
            wake.running = True
            audio = Path(directory) / 'test-command.wav'
            audio.touch()
            def capture(*args):
                equal(13.4)
                if outcome == 'capture-error':
                    raise RuntimeError('injected capture failure')
                if outcome == 'shutdown':
                    wake.running = False
                return audio
            def respond(*args):
                equal(13.4)
                wake.running = False
                if outcome == 'response-error':
                    raise RuntimeError('injected response failure')
            wake.capture_command = capture
            wake.run_conversation = respond
            try:
                wake.main()
                assert outcome in ('complete', 'shutdown')
            except RuntimeError:
                assert outcome in ('capture-error', 'response-error')
            equal(67)
            assert not duck.STATE.exists()
            audio.unlink(missing_ok=True)
            print('PASS wake loop restores volume on ' + outcome)
        print('ALL_SILENT_DUCK_TESTS_PASSED')
    finally:
        stop_player()
