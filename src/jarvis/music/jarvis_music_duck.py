#!/usr/bin/env python3
"""Temporarily lower local music during a wake command, independently of TTS."""

# Allow the dedicated runtime interpreters to execute this source file directly.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))

import contextlib
import json
import os
import sys
from jarvis.music.jarvis_music import RUNTIME, SOCKET, MusicError, controller_lock, ipc

STATE = RUNTIME / 'jarvis-music-duck.json'
FACTOR = 0.20


def _save(state):
    temporary = STATE.with_suffix('.tmp')
    with temporary.open('w') as handle:
        os.chmod(temporary, 0o600)
        json.dump(state, handle)
    temporary.replace(STATE)


def sync_duck():
    """Called under the music controller lock, including after player startup."""
    if not STATE.exists() or not SOCKET.exists():
        return
    state = json.loads(STATE.read_text())
    pid = ipc(['get_property', 'pid'])
    if state.get('pid') == pid:
        return
    volume = float(ipc(['get_property', 'volume']))
    state.update(pid=pid, volume=volume, lowered=volume * FACTOR)
    # Save before changing volume, so interruption is recoverable.
    _save(state)
    ipc(['set_property', 'volume', state['lowered']])


def _restore():
    if not STATE.exists():
        return
    state = json.loads(STATE.read_text())
    if SOCKET.exists() and state.get('pid') is not None:
        pid = ipc(['get_property', 'pid'])
        volume = float(ipc(['get_property', 'volume']))
        if pid == state['pid'] and abs(volume - state['lowered']) < 0.01:
            ipc(['set_property', 'volume', state['volume']])
    STATE.unlink(missing_ok=True)


def restore():
    with controller_lock():
        _restore()


def begin():
    with controller_lock():
        _restore()
        _save({'pid': None})
        sync_duck()


def recover():
    try:
        restore()
    except (MusicError, OSError, ValueError, KeyError, TypeError) as error:
        print(f'Music volume recovery deferred: {error}', file=sys.stderr, flush=True)


@contextlib.contextmanager
def ducked():
    try:
        begin()
    except (MusicError, OSError, ValueError, KeyError, TypeError) as error:
        print(f'Music ducking unavailable: {error}', file=sys.stderr, flush=True)
    try:
        yield
    finally:
        recover()


if __name__ == '__main__':
    recover()
