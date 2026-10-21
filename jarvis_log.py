#!/usr/bin/env python3
"""Captain's log: explicit recording, local dated files, and typed controls."""
import argparse
import fcntl
import json
import os
import signal
import subprocess
import sys
import time
import wave
from datetime import datetime
from pathlib import Path

ROOT = Path(os.environ.get('JARVIS_LOG_DIR', str(Path.home() / 'Jarvis/data/captains-log')))
UNIT = 'jarvis-log.service'
LOG_HELP = """JARVIS LOG COMMAND GUIDE

Run on the Mac mini, locally or through SSH. No voice command is required.
If the command is not found, use ~/.local/bin/jarvis-log instead.

  jarvis-log start "Team update"   Start a named video and audio recording
  jarvis-log start                 Start with the default captain's log title
  jarvis-log status                Check whether recording is running
  jarvis-log stop                  Finish and save the current log
  jarvis-log list                  List numbered entries, oldest to newest
  jarvis-log play latest           Play the latest saved log's AUDIO
  jarvis-log play YYYY-MM-DD       Play that date's latest saved AUDIO
  jarvis-log help                  Display this guide

The mirrored webcam preview opens on the Mac mini's monitor, even over SSH.
Closing the preview alone does NOT stop recording: use jarvis-log stop.
Recordings stop automatically after 30 minutes. Duplicate starts are ignored.
Log numbers are calculated across all dates from entry timestamps. Deleting
an entry renumbers the remaining entries; numbers are not permanent IDs.

Files: ~/Jarvis/data/captains-log/YYYY-MM-DD/
  .mp4   Webcam video and microphone audio together
  .wav   Audio copy for playback and future transcription
  .json  Title, dates, duration, file paths, and recording status
  .stderr / .preview.stderr   Recorder and preview diagnostics

To watch video, open the MP4 in a video player. The play command is audio only.
Audio playback uses the Mac mini's speakers. Earlier audio-only logs still work.
Transcripts and search are not implemented yet. Files stay on the Mac mini.

Voice alternative: say Hey Jarvis, then begin captain's log.
To finish, say Hey Jarvis again, then end log.

Troubleshooting (read-only):
  systemctl --user status jarvis-log.service
  journalctl --user -u jarvis-log.service -n 30 --no-pager
The service being inactive when no log is recording is normal.
"""


def save(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


def entries():
    result = []
    for path in ROOT.glob('*/*.json'):
        try:
            value = json.loads(path.read_text())
            value['_timestamp'] = datetime.fromisoformat(value['started_at']).timestamp()
            value['metadata_path'] = str(path)
            result.append(value)
        except (OSError, ValueError, KeyError, TypeError):
            continue
    # Numbers are views of the current chronological order, never stored IDs.
    result.sort(key=lambda item: (item['_timestamp'], item['metadata_path']))
    for number, item in enumerate(result, start=1):
        item.pop('_timestamp')
        item['number'] = number
    return result


def active():
    return subprocess.run(['systemctl', '--user', 'is-active', '--quiet', UNIT]).returncode == 0


def open_preview(errors):
    """Show a mirrored camera view on the desktop inherited by the user service."""
    if os.environ.get('JARVIS_LOG_PREVIEW', '1') == '0':
        return None
    if not (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')):
        raise RuntimeError('No desktop display session is available.')
    source = os.environ.get('JARVIS_LOG_VIDEO_URL')
    if source:
        input_args = ['-f', 'mpjpeg', '-i', source]
    else:
        input_args = ['-f', 'v4l2', '-framerate', '30', '-video_size', '640x480',
                      '-i', os.environ.get('JARVIS_LOG_CAMERA', '/dev/video0')]
    overlay = ('hflip,drawtext=text=CAPTAIN LOG - VIDEO AND AUDIO RECORDING:x=20:y=20:'
               'fontsize=22:fontcolor=white:box=1:boxcolor=black@0.65:boxborderw=12,'
               'drawtext=text=Hey Jarvis ... end log:x=20:y=h-50:'
               'fontsize=20:fontcolor=white:box=1:boxcolor=black@0.65:boxborderw=8')
    return subprocess.Popen(['ffplay', '-hide_banner', '-loglevel', 'warning',
                             '-nostats', '-an', '-x', '640', '-y', '480', '-window_title',
                             "Captain's log - live webcam preview", *input_args,
                             '-vf', overlay], stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=errors)


def record():
    """The service owns this process and stops it with SIGINT."""
    request = json.loads((ROOT / 'request.json').read_text())
    started = datetime.now().astimezone()
    folder = ROOT / started.strftime('%Y-%m-%d')
    folder.mkdir(mode=0o700, exist_ok=True)
    identifier = started.strftime('%H%M%S-%f')
    audio = folder / (identifier + '.wav')
    video = folder / (identifier + '.mp4')
    metadata = folder / (identifier + '.json')
    value = dict(id=identifier, title=request['title'], speaker=request['speaker'],
                 started_at=started.isoformat(), audio=str(audio), video=str(video), status='recording')
    save(metadata, value)
    recorder = None
    preview = None
    preview_errors = None
    stopping = False

    def stop(signum, frame):
        nonlocal stopping
        stopping = True
        if recorder is not None and recorder.poll() is None:
            recorder.send_signal(signal.SIGINT)

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        with (folder / (identifier + '.stderr')).open('w') as errors:
            recorder = subprocess.Popen([
                'ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'warning',
                '-thread_queue_size', '512', '-use_wallclock_as_timestamps', '1',
                '-f', 'mpjpeg', '-i', os.environ.get('JARVIS_LOG_VIDEO_URL', 'http://127.0.0.1:8766/stream.mjpg'),
                '-thread_queue_size', '512', '-f', 'pulse', '-i',
                os.environ.get('JARVIS_LOG_AUDIO_SOURCE', 'alsa_input.usb-046d_Logitech_BRIO_4A78B6D2-03.analog-stereo'),
                '-map', '0:v:0', '-map', '1:a:0', '-t', '1800',
                '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '23',
                '-pix_fmt', 'yuv420p', '-g', '60', '-fps_mode', 'vfr',
                '-c:a', 'aac', '-b:a', '128k', '-ac', '1',
                '-movflags', '+frag_keyframe+empty_moov+default_base_moof',
                '-flush_packets', '1', str(video)], stderr=errors, stdin=subprocess.DEVNULL)
            if stopping:
                recorder.send_signal(signal.SIGINT)
            # A preview failure must not discard the recorded log.
            try:
                preview_errors = (folder / (identifier + '.preview.stderr')).open('w')
                preview = open_preview(preview_errors)
                value['preview'] = 'started' if preview is not None else 'disabled'
            except (OSError, RuntimeError) as error:
                value['preview'] = 'unavailable'
                value['preview_error'] = str(error)
            save(metadata, value)
            code = recorder.wait()
            probe = subprocess.run(['ffprobe', '-v', 'error', '-show_streams',
                                    '-show_format', '-of', 'json', str(video)],
                                   text=True, capture_output=True, check=True, timeout=20)
            media = json.loads(probe.stdout)
            kinds = {stream['codec_type'] for stream in media['streams']}
            if not {'video', 'audio'}.issubset(kinds) or (code != 0 and not stopping):
                raise RuntimeError('The video log did not finish with both video and audio.')
            # Derive WAV from the same recorded sound, for existing audio playback.
            subprocess.run(['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error',
                            '-i', str(video), '-vn', '-ac', '1', '-ar', '16000',
                            '-c:a', 'pcm_s16le', str(audio)], check=True, timeout=60,
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        with wave.open(str(audio), 'rb') as recording:
            value['duration_seconds'] = round(recording.getnframes() / recording.getframerate(), 2)
        value['status'] = 'saved' if value['duration_seconds'] > 0 and (code == 0 or stopping) else 'failed'
        if value['status'] == 'failed':
            value['error'] = 'Recorder stopped unexpectedly; see the adjacent stderr file.'
    except (OSError, wave.Error, EOFError, RuntimeError, ValueError,
            subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        value.update(status='failed', error=str(error))
    finally:
        if preview is not None:
            if preview.poll() is None:
                preview.terminate()
                try:
                    preview.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    preview.kill()
                    preview.wait()
                value['preview'] = 'closed'
            else:
                value['preview'] = 'exited'
                value['preview_exit_code'] = preview.returncode
        if preview_errors is not None:
            preview_errors.close()
        value['ended_at'] = datetime.now().astimezone().isoformat()
        save(metadata, value)
    return 0 if value['status'] == 'saved' else 1


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(prog='jarvis-log', description=LOG_HELP,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True, title='commands')
    start = sub.add_parser('start', help='Start a video and audio log',
                           description='Start recording video and audio and open the webcam preview on the Mac mini monitor.',
                           epilog='Example: jarvis-log start "Team update"')
    start.add_argument('title', nargs='?', default="Captain's log",
                       help="entry title; quote titles with spaces (default: Captain's log)")
    descriptions = {'stop': 'Stop recording, save the MP4 and WAV, and close the preview.',
                    'status': 'Show whether a log is currently recording.',
                    'list': 'List dynamically numbered entries, oldest to newest, with date, title, status, and duration.',
                    'record': 'Internal recorder worker used by the service; do not launch manually.'}
    for name, description in descriptions.items():
        sub.add_parser(name, help=description, description=description)
    sub.add_parser('help', help='Display the log command guide',
                   description='Display the complete log command guide without starting a recording.')
    play = sub.add_parser('play', help='Play a saved log\'s audio',
                          description='Play the latest saved audio, or the latest saved audio for a specified date, on the Mac mini speakers. This command does not play video.',
                          epilog='Examples: jarvis-log play latest; jarvis-log play 2026-10-08')
    play.add_argument('day', nargs='?', default='latest', metavar='DATE',
                      help='latest or a date in YYYY-MM-DD format (default: latest)')
    args = parser.parse_args()
    if args.command == 'help':
        print(LOG_HELP)
        return 0
    ROOT.mkdir(parents=True, mode=0o700, exist_ok=True)
    if args.command == 'record':
        return record()
    # Serialize start/stop so two commands cannot create competing recordings.
    with (ROOT / 'control.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if args.command == 'start':
            if active():
                print('A captain\'s log is already recording.')
                return 0
            save(ROOT / 'request.json', dict(title=args.title, speaker=os.environ.get('JARVIS_SPEAKER', 'Unknown')))
            before = {item['metadata_path'] for item in entries()}
            subprocess.run(['systemctl', '--user', 'start', UNIT], check=True)
            for _ in range(150):
                new = [item for item in entries() if item['metadata_path'] not in before]
                if (new and new[-1]['status'] == 'recording' and active()
                        and Path(new[-1]['video']).exists()
                        and Path(new[-1]['video']).stat().st_size > 1024):
                    time.sleep(0.3)
                    if active():
                        print(f"Captain's log {new[-1]['number']}. Recording. Say Hey Jarvis, end log when finished.")
                        return 0
                if new and new[-1]['status'] == 'failed':
                    break
                time.sleep(0.1)
            raise RuntimeError('Recording did not start. Check journalctl --user -u jarvis-log.service.')
        if args.command == 'stop':
            if not active():
                print('No captain\'s log is currently recording.')
                return 0
            subprocess.run(['systemctl', '--user', 'stop', UNIT], check=True)
            latest = entries()[-1]
            if latest['status'] != 'saved':
                raise RuntimeError('Recording could not be finalized; check its metadata and stderr.')
            print(f"Captain's log {latest['number']} saved with video and audio. Duration: {latest['duration_seconds']} seconds.")
        elif args.command == 'status':
            print('Recording.' if active() else 'Not recording.')
        elif args.command == 'list':
            for item in entries():
                print(f"Log {item['number']}", '|', item['started_at'], '|', item['title'], '|', item['status'], '|', item.get('duration_seconds', 0), 'seconds')
        elif args.command == 'play':
            candidates = [item for item in entries() if item['status'] == 'saved' and
                          (args.day == 'latest' or item['started_at'].startswith(args.day + 'T'))]
            if not candidates:
                raise RuntimeError('No saved log found for ' + args.day)
            if active():
                raise RuntimeError('End the current log before playing a recording.')
            subprocess.run(['pw-play', candidates[-1]['audio']], check=True)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
