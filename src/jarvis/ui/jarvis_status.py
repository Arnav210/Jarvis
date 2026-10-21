#!/usr/bin/env python3
"""Local live command console. Only observable progress and final responses."""

# Allow the dedicated runtime interpreters to execute this source file directly.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))

import argparse
import contextlib
import curses
import datetime
import fcntl
import json
import math
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import textwrap
import time


def runtime():
    root = Path(os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}')) / 'jarvis-status'
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    return root


def clean(value):
    return ''.join(c for c in str(value) if c.isprintable() or c == '\n')[:12000]


def read_state(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def emit(stage=None, detail=None, **fields):
    """Best effort telemetry; a display failure must never break a command."""
    name = os.environ.get('JARVIS_STATUS_FILE')
    if not name:
        return
    try:
        path = Path(name)
        with path.with_suffix('.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            token = os.environ.get('JARVIS_REQUEST_GENERATION')
            if token:
                from jarvis.computer.jarvis_reset import generation
                if token != generation():
                    return
            data = read_state(path)
            previous_reply = data.get('reply', '')
            data.update({key: clean(value) for key, value in fields.items()})
            now = time.time()
            if fields.get('reply') and data.get('reply') != previous_reply:
                data['response_ready'] = str(now)
            elif stage == 'starting':
                data.pop('response_ready', None)
            processing = stage in {'processing', 'action', 'routing'}
            if processing and (not data.get('processing_started') or data.get('processing_finished')):
                data['processing_started'] = str(now)
                data['processing_finished'] = ''
            if fields.get('model_pending') == '1':
                data['model_started'] = str(now)
            if stage in {'speaking', 'complete', 'cancelled', 'error', 'attention', 'standby'}:
                if data.get('processing_started') and not data.get('processing_finished'):
                    data['processing_finished'] = str(now)
                data['model_pending'] = '0'
            if stage:
                data['stage'] = clean(stage)
            if detail:
                data['detail'] = clean(detail)
                events = data.get('events', [])
                events.append([datetime.datetime.now().strftime('%H:%M:%S'), clean(detail)])
                data['events'] = events[-10:]
            caption = fields.get('activity_caption')
            phase = fields.get('activity_step', '')
            target = fields.get('activity_target', '')
            terminal = {'speaking': ('Delivering the response', 'speaking'),
                        'complete': ('Request complete', 'complete'),
                        'cancelled': ('Request cancelled', 'cancelled'),
                        'error': ('Request failed', 'error'),
                        'attention': ('Needs attention', 'attention')}
            if not caption and data.get('activity_events') and (stage in terminal or fields.get('attention')):
                caption, phase = terminal.get(stage, ('Needs attention', 'attention'))
            if caption:
                caption, phase, target = clean(caption), clean(phase), clean(target)
                data.update(activity_caption=caption, activity_step=phase, activity_target=target)
                history = data.get('activity_events', [])
                entry = [datetime.datetime.now().strftime('%H:%M:%S'), caption, phase, target]
                if not history or history[-1][1:] != entry[1:]:
                    previous_phase = history[-1][2] if history else ''
                    event_time = str(time.time())
                    if phase in {'inspecting', 'searching', 'acting'}:
                        data['reactor_tool_started'] = event_time
                    elif previous_phase in {'inspecting', 'searching', 'acting'} and phase in {'reviewing', 'reply'}:
                        data['reactor_tool_returned'] = event_time
                    history.append(entry)
                data['activity_events'] = history[-8:]
            if stage == 'complete':
                data['reactor_completed'] = str(time.time())
            data['updated'] = time.time()
            tmp = path.with_suffix('.tmp')
            with tmp.open('w', encoding='utf-8') as handle:
                os.chmod(tmp, 0o600)
                json.dump(data, handle)
            tmp.replace(path)
    except (OSError, ValueError, TypeError):
        pass


def attention(detail):
    """Latch a real problem until a new command explicitly clears it."""
    emit(detail=detail, attention=detail)


def visual_state(data):
    if data.get('attention') or data.get('stage') in {'error', 'attention'}:
        return 'attention'
    if data.get('result') != 'running':
        return 'standby'
    stage = data.get('stage')
    if stage in {'starting', 'captured', 'listening'}:
        return 'listening'
    if stage == 'speaking':
        return 'speaking'
    return 'processing'


def desktop_env():
    env = os.environ.copy()
    try:
        result = subprocess.run(['systemctl', '--user', 'show-environment'], capture_output=True, text=True, timeout=3)
        for line in result.stdout.splitlines():
            key, sep, value = line.partition('=')
            if sep and key in {'DISPLAY', 'WAYLAND_DISPLAY', 'XAUTHORITY', 'DBUS_SESSION_BUS_ADDRESS', 'XDG_RUNTIME_DIR'}:
                env[key] = value
    except (OSError, subprocess.TimeoutExpired):
        pass
    env['TERM'] = 'xterm-256color'
    return env


def viewer_active(proc_root=None):
    """Recognize both desktop and SSH consoles, including already-open viewers."""
    script = Path(__file__).resolve()
    for proc in Path(proc_root or '/proc').iterdir():
        try:
            if not proc.name.isdigit() or proc.stat().st_uid != os.getuid():
                continue
            args = (proc / 'cmdline').read_bytes().split(b'\0')
            if b'--run' in args or not {b'--view', b'--desktop-view'}.intersection(args):
                continue
            if os.fsencode(script) in args:
                return True
            cwd = (proc / 'cwd').resolve()
            for arg in args[1:]:
                value = os.fsdecode(arg)
                if Path(value).name == script.name and (cwd / value).resolve() == script:
                    return True
        except (OSError, ValueError):
            continue
    return False


def open_window(force=False):
    # Serialize launch checks while a newly requested terminal starts its viewer.
    with (runtime() / 'desktop-launch.lock').open('a') as launch:
        try:
            fcntl.flock(launch, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        if not force and viewer_active():
            return
        pending = runtime() / 'desktop-launch-pending'
        try:
            if 0 <= time.monotonic() - float(pending.read_text()) < 5:
                return
        except (OSError, ValueError):
            pass
        _open_desktop_window(pending)


def _open_desktop_window(pending):
    # The lock is held by the viewer, not by a stale PID marker.
    with (runtime() / 'desktop-viewer.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
    env = desktop_env()
    if not (env.get('DISPLAY') or env.get('WAYLAND_DISPLAY')):
        return
    terminal = shutil.which('gnome-terminal')
    if not terminal:
        return
    command = [terminal, '--window', '--title=JARVIS | Live Command Console', '--geometry=144x48', '--hide-menubar', '--', '/usr/bin/python3', str(Path(__file__).resolve()), '--desktop-view']
    # Keep the viewer independent of wake/barge-in process-group cancellation.
    with (runtime() / 'window.log').open('a') as log:
        pending.write_text(str(time.monotonic()))
        try:
            subprocess.Popen(command, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
        except OSError:
            pending.unlink(missing_ok=True)
            raise


def observe(line):
    text = clean(line.strip())
    if text.startswith('Transcript: '):
        emit('identifying', 'Checking speaker identity.', transcript=text[12:])
    elif text.startswith('Heard: '):
        emit('routing', 'Matching the request to an available action.', transcript=text[7:])
    elif text.startswith('Speaker: '):
        emit(speaker=text[9:])
    elif text.startswith('Jarvis: '):
        emit('speaking', 'Playing the response.', reply=text[8:])
    elif 'Transcribing with' in text:
        emit('transcribing', 'Converting microphone audio into text.')
    elif 'using local fallback' in text:
        emit('transcribing', 'Warm transcription unavailable; trying local fallback.')
    elif text.startswith('Listening for '):
        emit('listening', text)
    elif text.startswith('Using wake-captured audio.'):
        emit('captured', 'Received audio captured by the wake listener.')
    elif text.startswith(('Speech error:', 'AI error:', 'Spotify error:', 'Camera error:', 'Alarm error:', 'State error:', 'Manifest error:', "Captain's log error:")):
        attention(text)


def run_listen(script, args, window=True, manual=False):
    import threading
    from jarvis.computer.jarvis_reset import generation, monitor, stop_group
    if (runtime() / 'resetting').exists():
        return 130
    token = generation()
    os.environ['JARVIS_REQUEST_GENERATION'] = token
    env = os.environ.copy()
    env['JARVIS_STATUS_CHILD'] = '1'
    env['PYTHONUNBUFFERED'] = '1'
    if env.get('JARVIS_STATUS_DISABLE') == '1':
        os.execve(script, [script, *args], env)
    with (runtime() / 'runner.lock').open('a') as lock, contextlib.ExitStack() as resources:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            if manual:
                return 75
            # Preserve the existing listen lock's busy behavior.
            return subprocess.call([script, *args], env=env)
        if manual:
            from jarvis.music.jarvis_music_duck import ducked
            resources.enter_context(ducked())
        path = runtime() / 'state.json'
        # Clear the last command before any child can emit status.
        path.unlink(missing_ok=True)
        os.environ['JARVIS_STATUS_FILE'] = str(path)
        env['JARVIS_STATUS_FILE'] = str(path)
        emit('starting', 'Command triggered. Preparing the microphone pipeline.', started=str(time.time()), transcript='', reply='', speaker='Pending', result='running', attention='')
        if window:
            try:
                open_window()
            except OSError:
                pass
        child = None
        watcher = None
        done = threading.Event()
        def cancelled(signum, frame):
            raise KeyboardInterrupt
        previous = signal.signal(signal.SIGTERM, cancelled)
        try:
            child = subprocess.Popen([script, *args], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors='replace', bufsize=1, start_new_session=True)
            watcher = monitor(child, token, done)
            for line in child.stdout:
                print(line, end='', flush=True)
                observe(line)
            code = child.wait()
            if generation() != token:
                return 130
            if code != 0:
                attention(read_state(path).get('attention') or f'Command failed with status {code}. Say Hey Jarvis to try again.')
            issue = read_state(path).get('attention')
            emit('attention' if issue else 'complete', issue or 'Command finished. Waiting for Hey Jarvis.', result=str(code))
            return code
        except KeyboardInterrupt:
            emit('cancelled', 'Command interrupted or cancelled by barge-in.', result='cancelled')
            return 130
        except OSError as error:
            attention(f'Listener unavailable: {error}')
            emit('error', str(error), result='error')
            print(f'Listen error: {error}', file=sys.stderr)
            return 1
        finally:
            signal.signal(signal.SIGTERM, previous)
            done.set()
            if watcher is not None:
                watcher.join(timeout=1)
            if child is not None and child.poll() is None:
                stop_group(child)
            if child is not None and child.stdout is not None:
                child.stdout.close()


def screen_lines(data, width=100, now=None):
    now = time.time() if now is None else now
    stage = 'ATTENTION' if visual_state(data) == 'attention' else data.get('stage', 'standby').upper()
    try:
        elapsed = max(0, int(float(data.get('updated', now) if data.get('result') != 'running' else now) - float(data.get('started', now))))
    except (ValueError, TypeError):
        elapsed = 0
    lines = [('J A R V I S   /   LIVE COMMAND CONSOLE', 1), ('LOCAL VOICE SYSTEM  |  OBSERVABLE STATUS', 3), ('=' * width, 3)]
    pulse = '|/-\\'[int(now * 3) % 4] if data.get('result') == 'running' else '*'
    lines += [(f'{pulse}  {stage}    |    {elapsed:02d}s', 4 if visual_state(data) == 'attention' else 2)]
    detail = data.get('attention') or data.get('detail', 'Waiting for the next command.')
    lines += [(line, 4 if data.get('attention') else 0) for line in textwrap.wrap(clean(detail), width=max(12, width))[:3]]
    lines += [('', 0)]
    for title, value in [('HEARD / EXACT TRANSCRIPT', data.get('transcript') or 'Waiting for transcription...'), ('SPEAKER / ESTIMATE', data.get('speaker', 'Pending')), ('JARVIS / RESPONSE', data.get('reply') or 'Waiting for a response...')]:
        lines.append((title, 1))
        wrapped = textwrap.wrap(clean(value), width=max(12, width - 4)) or ['']
        lines.extend(('  ' + line, 0) for line in wrapped[:5])
        lines.append(('', 0))
    lines.append(('PROCESS / ACTION TIMELINE', 1))
    for stamp, text in data.get('events', [])[-7:]:
        for index, part in enumerate(textwrap.wrap(clean(text), width=max(12, width - 12))[:2]):
            lines.append((f'  {stamp if index == 0 else "        "}  {part}', 3))
    return lines


def reactor_lines(data, now=None, large=True):
    from jarvis.ui.jarvis_reactor import reactor_lines as render
    return render(data, now=now, large=large, state=visual_state(data))


def draw(stdscr):
    from jarvis.ui.jarvis_music_panel import draw_console
    draw_console(stdscr, sys.modules[__name__])



def main():
    parser = argparse.ArgumentParser(description='Jarvis live transcript, action progress, and response console.')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--view', action='store_true', help='View live status in this terminal; Q closes it.')
    mode.add_argument('--desktop-view', action='store_true', help=argparse.SUPPRESS)
    mode.add_argument('--open', action='store_true', help='Open the desktop console without recording or playback.')
    mode.add_argument('--run', metavar='LISTENER', help=argparse.SUPPRESS)
    parser.add_argument('--no-window', action='store_true', help=argparse.SUPPRESS)
    options, args = parser.parse_known_args()
    if options.run:
        try:
            return run_listen(options.run, args, not options.no_window)
        except OSError as error:
            print(f"Status console unavailable: {error}; continuing listener.", file=sys.stderr)
            env = os.environ.copy()
            env["JARVIS_STATUS_CHILD"] = "1"
            os.execve(options.run, [options.run, *args], env)
    if args:
        parser.error('Unexpected arguments: ' + ' '.join(args))
    if options.open:
        open_window(force=True)
        return 0
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print('jarvis-status needs an interactive terminal. Run it directly in your SSH terminal.', file=sys.stderr)
        return 2
    try:
        if options.desktop_view:
            with (runtime() / 'desktop-viewer.lock').open('a') as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    return 0
                (runtime() / 'desktop-launch-pending').unlink(missing_ok=True)
                curses.wrapper(draw)
        else:
            # Interactive SSH views do not share the desktop-window lock.
            curses.wrapper(draw)
    except curses.error as error:
        print(f'Could not initialize the terminal display: {error}. Check TERM and terminal size.', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
