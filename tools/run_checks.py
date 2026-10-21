#!/usr/bin/env python3
"""Run existing regression tests with isolated state and silent MPV output."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    layout = subprocess.run([sys.executable, str(ROOT / 'tools/check_layout.py')], cwd=ROOT)
    if layout.returncode:
        return layout.returncode
    with tempfile.TemporaryDirectory(prefix='jarvis-checks-') as directory:
        root = Path(directory)
        home = root / 'home'
        home.mkdir()
        # A fresh HOME avoids reading the operator's recordings, song library,
        # model credentials, or interactive runtime state.
        env = {k: v for k, v in os.environ.items() if not k.startswith(('JARVIS_', 'XDG_'))}
        env.update(HOME=str(home), XDG_RUNTIME_DIR=str(root / 'runtime'),
                   XDG_STATE_HOME=str(root / 'state'), XDG_CONFIG_HOME=str(root / 'config'),
                   JARVIS_HOME=str(home / 'Jarvis'), JARVIS_STATUS_FILE=str(root / 'status.json'),
                   PYTHONDONTWRITEBYTECODE='1', PYTHONPATH=os.pathsep.join([str(ROOT / 'src'), str(ROOT / 'tests')]),
                   JARVIS_MUSIC_SOCKET=str(root / 'no-live-player.sock'))
        env.pop('DISPLAY', None)
        env.pop('WAYLAND_DISPLAY', None)
        for path in ['runtime', 'state', 'config']:
            (root / path).mkdir(mode=0o700)
        commands = [[sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-p', 'unit_*.py', '-v']]
        commands += [[sys.executable, str(ROOT / 'tests' / name)] for name in ('test_console_design.py', 'test_music_duck.py', 'test_music_panel.py')]
        for command in commands:
            print('CHECK:', ' '.join(command), flush=True)
            try:
                result = subprocess.run(command, cwd=ROOT, env=env, timeout=120)
            except subprocess.TimeoutExpired:
                print('Check timed out.', file=sys.stderr)
                return 1
            if result.returncode:
                return result.returncode
    print('All isolated regression checks passed.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
