"""Shared keyboard pause for wake detection and command recording."""

# Allow the dedicated runtime interpreters to execute this source file directly.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))

import argparse
import fcntl
import os
from pathlib import Path
import subprocess
import signal
import time

PAUSED = 76


def root():
    path = Path(os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}')) / 'jarvis-status'
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


def listening_paused():
    return (root() / 'listening-paused').exists() or (root() / 'resetting').exists()


def read_token(name):
    try:
        return (root() / name).read_text().strip()
    except FileNotFoundError:
        return ''


def begin_capture():
    token = f'{os.getpid()}:{time.monotonic_ns()}'
    with (root() / 'capture-control.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        (root() / 'capture-active').write_text(token)
        (root() / 'capture-finish').unlink(missing_ok=True)
    return token


def finish_requested(token):
    return bool(token) and read_token('capture-finish') == token


def end_capture(token):
    with (root() / 'capture-control.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if read_token('capture-active') == token:
            (root() / 'capture-active').unlink(missing_ok=True)
        if read_token('capture-finish') == token:
            (root() / 'capture-finish').unlink(missing_ok=True)


def request_finish():
    with (root() / 'capture-control.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        token = read_token('capture-active')
        if not token:
            return 'No active recording. Press L to start listening.'
        try:
            os.kill(int(token.split(':', 1)[0]), 0)
        except (OSError, ValueError):
            return 'No active recording. Press L to start listening.'
        (root() / 'capture-finish').write_text(token)
    return 'Finishing recording. Processing the audio captured so far...'


def toggle_pause():
    with (root() / 'listening-pause.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        marker = root() / 'listening-paused'
        if marker.exists():
            marker.unlink()
            return 'Listening resumed. Say Hey Jarvis or press L.'
        fd = os.open(marker, os.O_CREAT | os.O_WRONLY, 0o600)
        os.close(fd)
        return 'Listening paused. Press P to resume.'


def record(command):
    if listening_paused():
        return PAUSED
    token = begin_capture()
    child = None
    try:
        child = subprocess.Popen(command)
        while child.poll() is None:
            if listening_paused():
                return PAUSED
            if finish_requested(token):
                # SIGINT lets arecord finalize the existing WAV before STT reads it.
                child.send_signal(signal.SIGINT)
                try:
                    code = child.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    return 1
                return 0 if code in {0, 130, -signal.SIGINT} else code
            time.sleep(.05)
        return child.returncode
    finally:
        if child is not None and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=1)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        end_capture(token)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--record', action='store_true', help='Record until completion or listening is paused.')
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not args.record or not command:
        parser.error('Use --record -- COMMAND to run a recording.')
    return record(command)


if __name__ == '__main__':
    raise SystemExit(main())
