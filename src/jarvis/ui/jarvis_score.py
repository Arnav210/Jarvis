"""Avengers score cues and an isolated MPV player for the ASCII film."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import socket
import subprocess
import time

# Seconds measured from this recording, paired with the film's original shot times.
CUES = ((0.,0.),(8.986,7.),(16.533,16.),(25.078,28.),(33.135,35.),(47.253,47.),(54.,54.))
IMPACTS = (13.026,15.047,19.064,21.060,24.079,34.644,38.684,42.701,44.234,46.719)
_clock_cache = {}


def story_time(seconds):
    value=max(0.,min(54.,float(seconds)))
    for (a,x),(b,y) in zip(CUES,CUES[1:]):
        if value<=b:
            return x+(value-a)/(b-a)*(y-x)
    return 54.


def audio_path():
    root=Path(os.environ.get('JARVIS_HOME',Path.home()/'Jarvis'))
    return Path(os.environ.get('JARVIS_IRONMAN_AUDIO',root/'data/ironman/avengers-theme.wav')).expanduser()


def request(path, command, timeout=.08):
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
        client.settimeout(timeout)
        client.connect(str(path))
        client.sendall((json.dumps({'command':command,'request_id':913})+'\n').encode())
        body=b''
        while len(body)<65536:
            data=client.recv(4096)
            if not data:break
            body+=data
            while b'\n' in body:
                row,body=body.split(b'\n',1)
                reply=json.loads(row)
                if reply.get('request_id')==913:
                    if reply.get('error')!='success':
                        raise RuntimeError('MPV command failed: '+str(reply.get('error')))
                    return reply.get('data')
        raise RuntimeError('No soundtrack response.')


def elapsed(data, now=None):
    """Prefer the audio playhead; interpolate between polls to avoid IPC per frame."""
    now=time.time() if now is None else now
    fallback=max(0.,now-float(data.get('show_started',now)))
    name=data.get('show_audio_socket')
    if not name:return fallback
    stamp=time.monotonic()
    previous=_clock_cache.get(name)
    if previous and stamp-previous[1]<.20:
        return max(0.,previous[0]+stamp-previous[1])
    try:
        position=request(name,['get_property','time-pos'],timeout=.025)
        if isinstance(position,(int,float)) and math.isfinite(position):
            _clock_cache.clear()
            _clock_cache[name]=(float(position),stamp)
            return max(0.,float(position))
    except (OSError,ValueError,RuntimeError,TypeError):
        pass
    if previous and stamp-previous[1]<1:
        return max(0.,previous[0]+stamp-previous[1])
    return fallback


class LibraryPause:
    """Pause the separate library player; restore only the same untouched track."""
    def __init__(self):self.saved=None

    def begin(self):
        from jarvis.music.jarvis_music import controller_lock,ipc,SOCKET
        try:
            with controller_lock():
                if not SOCKET.exists() or ipc(['get_property','pause']):return
                saved=(ipc(['get_property','pid']),ipc(['get_property','path']))
                ipc(['set_property','pause',True])
                self.saved=saved
        except Exception:
            # No library player must never prevent the dedicated score from playing.
            self.saved=None

    def restore(self):
        if self.saved is None:return
        from jarvis.music.jarvis_music import controller_lock,ipc
        try:
            with controller_lock():
                same=(ipc(['get_property','pid']),ipc(['get_property','path']))==self.saved
                if same and ipc(['get_property','pause']):ipc(['set_property','pause',False])
        except Exception:
            pass
        self.saved=None


class Soundtrack:
    def __init__(self,path,runtime):
        self.path=Path(path)
        self.socket=Path(runtime)/f'ironman-score-{os.getpid()}.sock'
        self.process=None
        self.library=LibraryPause()

    def start(self):
        self.socket.unlink(missing_ok=True)
        self.process=subprocess.Popen(['mpv','--no-config','--no-video','--terminal=no',
            '--really-quiet','--pause=yes','--keep-open=no','--volume=100',
            '--input-ipc-server='+str(self.socket),str(self.path)],
            stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            if self.process.poll() is not None:raise RuntimeError('The soundtrack player could not start.')
            try:
                value=request(self.socket,['get_property','time-pos'])
                if isinstance(value,(int,float)):
                    self.library.begin()
                    request(self.socket,['set_property','pause',False])
                    return
            except (OSError,RuntimeError,ValueError):pass
            time.sleep(.04)
        raise RuntimeError('The soundtrack did not become ready.')

    def position(self):
        try:
            value=request(self.socket,['get_property','time-pos'])
            return float(value) if isinstance(value,(int,float)) else None
        except (OSError,ValueError,RuntimeError):return None

    def stop(self):
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:self.process.wait(timeout=1.5)
            except subprocess.TimeoutExpired:self.process.kill();self.process.wait()
        self.socket.unlink(missing_ok=True)
        self.library.restore()
