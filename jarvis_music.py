#!/usr/bin/env python3
"""Local-library music commands backed by a private MPV IPC socket."""
import argparse
import contextlib
import fcntl
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import sys
import time
import unicodedata

PROJECT = Path(os.environ.get('JARVIS_HOME', Path.home() / 'Jarvis'))
MUSIC = PROJECT / 'data/music'
RUNTIME = Path(os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}'))
SOCKET = Path(os.environ.get('JARVIS_MUSIC_SOCKET', RUNTIME / 'jarvis-music/player.sock'))


class MusicError(Exception):
    pass


def normalize(text):
    text = text.replace('&', ' and ')
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode().lower()
    return ' '.join(re.sub(r'[^a-z0-9 ]', '', text).split())


def artist_key(text):
    key = normalize(text)
    if key == 'jenny':
        return 'jennie'
    return 'the weeknd' if key in {'weeknd', 'the weeknd', 'weekend', 'the weekend'} else key.removeprefix('the ')


def parse_voice(text):
    """Return a deterministic local command, or None for unrelated/Spotify requests."""
    text = normalize(text)
    text = re.sub(r'^(?:hey )?jarvis\s+', '', text)
    text = re.sub(r'^(?:can|could|would|will) you\s+', '', text)
    text = re.sub(r'^please\s+', '', text)
    if re.search(r'\bspotify\b', text):
        return None
    if re.fullmatch(r'(?:whats playing|what is playing|what song is (?:this|playing)|now playing)', text):
        return 'now-playing', ''
    match = re.match(r'^(stop|pause|pausic|resume|unpause|continue) (?:the )?(?:music|song|track)\b', text)
    if match:
        action = {'pausic': 'pause', 'unpause': 'resume', 'continue': 'resume'}.get(match[1], match[1])
        return action, ''
    match = re.fullmatch(r'play (?:any|a random|some) (?:song|track) (?:from|by) (.+)', text)
    if match:
        return 'random-artist', match[1]
    match = re.fullmatch(r'play some (.+)', text)
    if match:
        return 'artist', match[1]
    match = re.fullmatch(r'play (?:(?:the )?(?:song|track) )?(.+)', text)
    if match:
        return 'play', match[1]
    return None


def library():
    try:
        entries = json.loads((MUSIC / 'library.json').read_text())
    except (OSError, ValueError) as error:
        raise MusicError('The local music library is unavailable.') from error
    if not isinstance(entries, list):
        raise MusicError('The local music library index is invalid.')
    tracks = []
    for entry in entries:
        if not isinstance(entry, dict) or not all(isinstance(entry.get(k), str) for k in ('file', 'title', 'artist')):
            continue
        path = (MUSIC / entry['file']).resolve()
        if path.is_relative_to(MUSIC.resolve()) and path.is_file() and path.suffix.lower() in {'.m4a', '.mp3', '.flac', '.ogg', '.opus', '.wav', '.aac'}:
            tracks.append(dict(entry, path=str(path)))
    return tracks


def matching_artist(track, query):
    artists = track.get('artists', [])
    if not isinstance(artists, list):
        artists = []
    for name in [track['artist'], *artists]:
        if isinstance(name, str) and artist_key(name) == artist_key(query):
            return name
    return None


def select_tracks(query, by_artist=False):
    tracks = library()
    if by_artist:
        matches = [t for t in tracks if matching_artist(t, query)]
        if not matches:
            raise MusicError(f'I do not have any saved songs by {query}.')
        return sorted(matches, key=lambda t: normalize(t['title']))
    title, separator, artist = query.partition(' by ')
    matches = [t for t in tracks if normalize(t['title']) == normalize(title) and (not separator or matching_artist(t, artist))]
    if len(matches) > 1:
        raise MusicError('More than one saved song matches. Please include the artist.')
    if not matches:
        raise MusicError(f'I do not have {query} in the local music library.')
    return matches


def ipc(command):
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(3)
            connection.connect(str(SOCKET))
            connection.sendall((json.dumps({'command': command, 'request_id': 1}) + '\n').encode())
            with connection.makefile('rb') as reader:
                for line in reader:
                    reply = json.loads(line)
                    if reply.get('request_id') == 1:
                        if reply.get('error') != 'success':
                            raise MusicError('The local music player could not complete that command.')
                        return reply.get('data')
        raise MusicError('The local music player did not respond.')
    except (OSError, ValueError) as error:
        raise MusicError('The local music player is not responding.') from error


def property_value(name, default=None):
    try:
        return ipc(['get_property', name])
    except MusicError:
        return default


def ensure_player():
    if SOCKET.exists():
        try:
            ipc(['get_property', 'mpv-version'])
            from jarvis_music_duck import sync_duck
            sync_duck()
            return
        except MusicError:
            pass
    if os.environ.get('JARVIS_MUSIC_SOCKET'):
        raise MusicError('The selected local music player is unavailable.')
    try:
        result = subprocess.run(['systemctl', '--user', 'start', 'jarvis-music.service'], capture_output=True, text=True, timeout=8)
        if result.returncode:
            raise MusicError('The local music service could not start.')
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if SOCKET.exists():
                try:
                    ipc(['get_property', 'mpv-version'])
                    from jarvis_music_duck import sync_duck
                    sync_duck()
                    return
                except MusicError:
                    pass
            time.sleep(0.1)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise MusicError('The local music service could not start.') from error
    raise MusicError('The local music player did not become ready.')


@contextlib.contextmanager
def controller_lock():
    RUNTIME.mkdir(parents=True, exist_ok=True)
    with (RUNTIME / 'jarvis-music-control.lock').open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def perform(action, query=''):
    with controller_lock():
        if action in {'play', 'artist', 'random-artist'}:
            tracks = select_tracks(query, action in {'artist', 'random-artist'})
            if action == 'random-artist':
                tracks = [secrets.choice(tracks)]
            ensure_player()
            ipc(['set_property', 'pause', True])
            ipc(['loadfile', tracks[0]['path'], 'replace'])
            for track in tracks[1:]:
                ipc(['loadfile', track['path'], 'append'])
            ipc(['set_property', 'pause', False])
            first = tracks[0]
            if action == 'artist':
                artist = matching_artist(first, query) or first['artist']
                return f"Playing {len(tracks)} saved songs by {artist}, starting with {first['title']}."
            return f"Playing {first['title']} by {first['artist']}."
        if not SOCKET.exists():
            if action == 'resume':
                raise MusicError('No local music is loaded. Ask me to play a song first.')
            return 'Music stopped.' if action == 'stop' else 'No local music is playing.'
        # Check the IPC connection explicitly; transport failure is not an idle player.
        idle = ipc(['get_property', 'idle-active'])
        if action == 'stop':
            ipc(['stop'])
            return 'Music stopped.'
        if action == 'now-playing':
            if idle:
                return 'No local music is playing.'
            path = ipc(['get_property', 'path'])
            track = next((t for t in library() if t['path'] == path), None)
            if not track:
                raise MusicError('The current track is not in the local library.')
            state = 'paused on' if ipc(['get_property', 'pause']) else 'playing'
            return f"Local music is {state} {track['title']} by {track['artist']}."
        if action in {'pause', 'resume'}:
            if idle:
                if action == 'resume':
                    raise MusicError('No local music is loaded. Ask me to play a song first.')
                return 'No local music is playing.'
            ipc(['set_property', 'pause', action == 'pause'])
            return 'Music paused.' if action == 'pause' else 'Resuming local music.'
        raise MusicError('Unknown local music command.')


def main():
    parser = argparse.ArgumentParser(description='Control music saved in the Jarvis local library.')
    commands = parser.add_subparsers(dest='action', required=True)
    for action in ('play', 'artist', 'random-artist'):
        commands.add_parser(action).add_argument('query', nargs='+')
    for action in ('now-playing', 'stop', 'pause', 'resume'):
        commands.add_parser(action)
    args = parser.parse_args()
    try:
        print(perform(args.action, ' '.join(getattr(args, 'query', []))))
        return 0
    except MusicError as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
