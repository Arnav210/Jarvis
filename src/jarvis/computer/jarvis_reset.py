"""Cancel the current voice command and return Jarvis to wake-word standby."""

# Allow the dedicated runtime interpreters to execute this source file directly.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))

import argparse
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
import uuid
from jarvis.audio.jarvis_listen_control import root


def generation():
    try:
        return (root() / 'request-generation').read_text().strip()
    except FileNotFoundError:
        return 'initial'


def stop_group(child):
    """Only called for a command launched in its own session by our runner."""
    try:
        os.killpg(child.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        child.wait(timeout=.4)
    except subprocess.TimeoutExpired:
        pass
    # Clean up descendants even if their parent exited first.
    try:
        os.killpg(child.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    child.wait()


def monitor(child, token, done):
    def watch():
        while not done.wait(.05):
            if generation() != token:
                stop_group(child)
                return
    thread = threading.Thread(target=watch, daemon=True)
    thread.start()
    return thread


def perform_reset():
    from jarvis.ui.jarvis_status import emit
    with (root() / 'reset.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 'A reset is already in progress.', 1
        marker = root() / 'resetting'
        marker.touch(mode=0o600)
        try:
            token = uuid.uuid4().hex
            temporary = root() / 'request-generation.tmp'
            temporary.write_text(token)
            temporary.replace(root() / 'request-generation')
            os.environ['JARVIS_REQUEST_GENERATION'] = token
            os.environ['JARVIS_STATUS_FILE'] = str(root() / 'state.json')
            # Give capture and command cancellation a chance to release their locks.
            time.sleep(.25)
            deadline = time.monotonic() + 5
            with (root() / 'runner.lock').open('a') as runner:
                while True:
                    try:
                        fcntl.flock(runner, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        if time.monotonic() >= deadline:
                            return 'Cancellation requested; the command has not finished stopping. Press R to retry.', 1
                        time.sleep(.05)
                state_dir = Path(os.environ.get('XDG_STATE_HOME', Path.home() / '.local/state')) / 'jarvis'
                state_dir.mkdir(parents=True, exist_ok=True)
                state_file = state_dir / 'assistant.json'
                try:
                    saved = json.loads(state_file.read_text())
                    if not isinstance(saved, dict):
                        saved = {}
                except (OSError, ValueError):
                    saved = {}
                saved['paused'] = False
                temp_state = state_file.with_suffix('.tmp')
                temp_state.write_text(json.dumps(saved) + '\n')
                os.chmod(temp_state, 0o600)
                temp_state.replace(state_file)
                (root() / 'listening-paused').unlink(missing_ok=True)
                with (root() / 'state.lock').open('a') as state_lock:
                    fcntl.flock(state_lock, fcntl.LOCK_EX)
                    (root() / 'state.json').unlink(missing_ok=True)
                emit('standby', 'Reset complete. Say Hey Jarvis for a new command.',
                     result='idle', started=str(time.time()), transcript='', reply='',
                     speaker='Pending', attention='', mic_active='0', model_pending='0')
            return 'Reset complete. Ready for Hey Jarvis.', 0
        finally:
            marker.unlink(missing_ok=True)


class ResetController:
    def __init__(self):
        self.child = None

    def trigger(self):
        if self.child is not None and self.child.poll() is None:
            return 'Reset already in progress.'
        try:
            fd = os.open(root() / 'reset.log', os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            with os.fdopen(fd, 'a') as log:
                self.child = subprocess.Popen([sys.executable, str(Path(__file__).resolve())],
                                              stdin=subprocess.DEVNULL, stdout=log,
                                              stderr=log, start_new_session=True)
            return 'Cancelling the current command...'
        except OSError:
            return 'Could not start reset. Try jarvis-reset in a terminal.'

    def poll_message(self):
        if self.child is None or self.child.poll() is None:
            return None
        code = self.child.returncode
        self.child = None
        return ('Reset complete. Ready for Hey Jarvis.' if code == 0
                else 'Reset needs attention. See reset.log or run jarvis-reset.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    message, code = perform_reset()
    print(message, flush=True)
    return code


if __name__ == '__main__':
    raise SystemExit(main())
