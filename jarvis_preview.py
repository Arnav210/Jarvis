#!/usr/bin/env python3
"""A windowed desktop viewer of Jarvis's existing shared camera feed."""
import argparse
import os
import subprocess
import sys

UNIT = 'jarvis-camera-preview.service'
FEED = 'http://127.0.0.1:8766/stream.mjpg'


def active():
    return subprocess.run(['systemctl', '--user', 'is-active', '--quiet', UNIT]).returncode == 0


def main():
    parser = argparse.ArgumentParser(description='Open a movable, resizable camera window on the Jarvis monitor. Preview only; does not start recording or play microphone audio.')
    parser.add_argument('action', nargs='?', choices=['open', 'close', 'status'], default='open')
    parser.add_argument('--width', type=int, default=640, help='Initial window width (default: 640)')
    parser.add_argument('--height', type=int, default=480, help='Initial window height (default: 480)')
    parser.add_argument('--on-top', action='store_true', help='Keep the preview above other windows')
    args = parser.parse_args()
    if args.action == 'close':
        subprocess.run(['systemctl', '--user', 'stop', UNIT], check=True)
        print('Camera preview closed. Existing recordings and the shared camera feed continue.')
        return 0
    if args.action == 'status':
        print('Camera preview is open.' if active() else 'Camera preview is closed.')
        return 0
    if not 160 <= args.width <= 3840 or not 120 <= args.height <= 2160:
        parser.error('Choose a width from 160 to 3840 and height from 120 to 2160.')
    if active():
        print('Camera preview is already open on the Jarvis monitor.')
        return 0
    env = os.environ.copy()
    result = subprocess.run(['systemctl', '--user', 'show-environment'], capture_output=True, text=True, check=True, timeout=5)
    keys = {'DISPLAY', 'WAYLAND_DISPLAY', 'XAUTHORITY', 'DBUS_SESSION_BUS_ADDRESS', 'XDG_RUNTIME_DIR'}
    for line in result.stdout.splitlines():
        key, sep, value = line.partition('=')
        if sep and key in keys:
            env[key] = value
    if not (env.get('DISPLAY') or env.get('WAYLAND_DISPLAY')):
        raise RuntimeError('No desktop session is available on the Jarvis monitor.')
    subprocess.run(['systemctl', '--user', 'start', 'jarvis-camera-feed.service'], check=True, timeout=15)
    command = ['systemd-run', '--user', '--collect', '--unit=' + UNIT, '--description=JARVIS camera preview']
    command += ['--setenv=' + key + '=' + env[key] for key in sorted(keys) if key in env]
    command += ['ffplay', '-hide_banner', '-loglevel', 'warning', '-nostats', '-an', '-sn', '-autoexit', '-framedrop', '-filter_threads', '1', '-window_title', 'JARVIS Camera | Live preview', '-x', str(args.width), '-y', str(args.height), '-left', '40', '-top', '80']
    if args.on_top:
        command.append('-alwaysontop')
    command += ['-f', 'mpjpeg', '-i', FEED, '-vf', 'hflip']
    subprocess.run(command, check=True, timeout=10)
    print('Camera preview opened on the Jarvis monitor. Drag the title bar to move; drag an edge to resize. Q or Esc closes this preview.')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        print('Camera preview: ' + str(error), file=sys.stderr)
        raise SystemExit(1)
