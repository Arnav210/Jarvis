"""Keyboard fallback for one normal voice command, independent of wake detection."""
import argparse
import fcntl
import os
from pathlib import Path
import subprocess
import sys
import time

from jarvis_listen_control import listening_paused

BUSY=75

def root():
    path=Path(os.environ.get('XDG_RUNTIME_DIR',f'/run/user/{os.getuid()}'))/'jarvis-status'
    path.mkdir(parents=True,exist_ok=True,mode=0o700)
    return path

def lock_busy(path):
    with path.open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return True
        return False

def manual_active():
    try:return lock_busy(root()/'manual-listen.lock')
    except OSError:return False

def run_manual():
    if listening_paused():return BUSY
    from jarvis_status import read_state,run_listen
    with (root()/'manual-listen.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return BUSY
        data=read_state(root()/'state.json')
        try:fresh=0<=time.time()-float(data.get('mic_updated',0))<.8
        except (ValueError,TypeError):fresh=False
        if data.get('mic_active')=='1' and fresh:return BUSY
        if lock_busy(root().parent/'jarvis-listen.lock'):return BUSY
        for key in ('JARVIS_AUDIO_FILE','JARVIS_TRANSCRIPT_FILE','JARVIS_STATUS_CHILD','JARVIS_STATUS_DISABLE'):
            os.environ.pop(key,None)
        os.environ['JARVIS_MANUAL_TRIGGER']='1'
        script=Path(__file__).resolve().parent/'bin/jarvis-listen'
        if not script.is_file():return 1
        return run_listen(str(script),[],window=False,manual=True)

class ManualListenController:
    """Launch without blocking curses; do not stop a command when a viewer closes."""
    def __init__(self):self.child=None

    def trigger(self):
        if listening_paused():return "Listening paused. Press P to resume."
        if self.child is not None and self.child.poll() is None:
            return 'Already listening or processing. Wait for the response.'
        try:
            log_path=root()/'manual-listen.log'
            fd=os.open(log_path,os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o600)
            with os.fdopen(fd,'a') as log:
                self.child=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--run'],stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            return 'Starting microphone. Speak when LISTENING appears.'
        except OSError:
            return 'Could not start listening. Try jarvis-listen in a terminal.'

    def poll_message(self):
        if self.child is None:return None
        result=self.child.poll()
        if result is None:return None
        self.child=None
        if result==130:return 'Command cancelled.'
        if result==BUSY:return 'Jarvis is busy. Press L after the current command.'
        if result:return 'Listening failed. Check the response panel or manual-listen.log.'
        return None

def main():
    parser=argparse.ArgumentParser(description='Start one voice command without the wake phrase.')
    parser.add_argument('--run',action='store_true',help='Start the normal capture and command flow.')
    args=parser.parse_args()
    if not args.run:parser.error('Use --run to start listening.')
    return run_manual()

if __name__=='__main__':raise SystemExit(main())
