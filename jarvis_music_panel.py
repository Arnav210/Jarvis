"""Read-only music telemetry and character-cell console layout."""
import json
import math
import os
from pathlib import Path
import socket
import threading
import textwrap
import time

RUNTIME = Path(os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}'))
SOCKET = Path(os.environ.get('JARVIS_MUSIC_SOCKET', RUNTIME / 'jarvis-music/player.sock'))
INDEX = Path(os.environ.get('JARVIS_HOME', Path.home() / 'Jarvis')) / 'data/music/library.json'
DUCK = RUNTIME / 'jarvis-music-duck.json'


def clean(value):
    return ' '.join(''.join(c for c in str(value) if c.isprintable() or c.isspace()).split())


def seconds(value):
    try:
        value = float(value)
        return max(0, value) if math.isfinite(value) else 0
    except (ValueError, TypeError):
        return 0


def clock(value):
    value = int(seconds(value))
    return f'{value//60:02d}:{value%60:02d}'


def snapshot():
    """One bounded IPC read. Never starts, changes, pauses, or resumes MPV."""
    if not SOCKET.exists():
        return {'state': 'stopped'}
    properties = ['idle-active', 'pause', 'path', 'metadata', 'time-pos', 'duration', 'volume', 'pid']
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(.20)
            connection.connect(str(SOCKET))
            connection.sendall(b''.join((json.dumps({'command': ['get_property', name], 'request_id': i})+'\n').encode() for i, name in enumerate(properties)))
            replies = {}
            with connection.makefile('rb') as stream:
                for _ in range(40):
                    line = stream.readline(65536)
                    if not line:
                        break
                    response = json.loads(line)
                    i = response.get('request_id')
                    if isinstance(i, int) and 0 <= i < len(properties):
                        replies[i] = response.get('data') if response.get('error') == 'success' else None
                    if len(replies) == len(properties):
                        break
            if len(replies) != len(properties) or replies[0] is None:
                return {'state': 'unavailable'}
        data = dict(zip(properties, (replies[i] for i in range(len(properties)))))
        if data['idle-active']:
            return {'state': 'stopped'}
        metadata = data['metadata'] if isinstance(data['metadata'], dict) else {}
        title, artist = metadata.get('title', metadata.get('TITLE', 'Unknown track')), metadata.get('artist', metadata.get('ARTIST', 'Unknown artist'))
        try:
            entries = json.loads(INDEX.read_text())
            for track in entries:
                if str((INDEX.parent / track['file']).resolve()) == data['path']:
                    title, artist = track['title'], track['artist']
                    break
        except (OSError, ValueError, TypeError, KeyError):
            pass
        lowered = False
        try:
            recovery = json.loads(DUCK.read_text())
            lowered = recovery.get('pid') == data['pid'] and abs(float(data['volume'])-float(recovery['lowered'])) < .01
        except (OSError, ValueError, KeyError, TypeError):
            pass
        return {'state': 'paused' if data['pause'] else 'playing', 'title': clean(title), 'artist': clean(artist),
                'elapsed': seconds(data['time-pos']), 'duration': seconds(data['duration']), 'lowered': lowered}
    except (OSError, ValueError, TypeError):
        return {'state': 'unavailable'}


class MusicMonitor:
    """Keep IPC off the UI thread so a broken player never freezes the console."""
    def __init__(self):
        self.data = {'state': 'checking'}
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        while not self.stop_event.is_set():
            self.data = snapshot()
            self.stop_event.wait(.6)

    def close(self):
        self.stop_event.set()
        self.thread.join(timeout=.5)



from jarvis_console_layout import box, music_lines, left_lines, draw_console
