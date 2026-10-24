"""Read-only spoken answers from the room dashboard; no camera or AI calls."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import re
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener
from zoneinfo import ZoneInfo

DEFAULT_URL = 'http://100.116.50.193:8000'
MAX_BYTES = 2 * 1024 * 1024


class RoomDataError(ValueError):
    pass


def intent(transcript: str) -> str | None:
    text = re.sub(r"[^a-z0-9' ]", ' ', transcript.lower().replace('\u2019', "'"))
    text = re.sub(r'\s+', ' ', text).strip()
    text = re.sub(r'^(?:hey )?jarvis\s+', '', text)
    text = re.sub(r'^(?:(?:can|could|would) you )?(?:please )?(?:tell me )?', '', text)
    text = re.sub(r' please$', '', text)
    patterns = {
        'current': r"(?:how many (?:people|persons|students) are (?:there )?in (?:the |this |our )?(?:room|classroom)(?: right now| now)?|what(?:'s| is) (?:the )?(?:current |latest |last recorded )?(?:room |classroom )?(?:occupancy|people count|person count))",
        'peak': r"(?:what(?:'s| is| was) (?:(?:the )?(?:highest|peak|maximum) (?:room )?(?:occupancy|people count|person count)(?: (?:for )?today)?|today(?:'s| s)? (?:highest|peak|maximum) (?:occupancy|people count|person count))|how many people were in (?:the )?(?:room|classroom) at (?:its|the) (?:peak|busiest)(?: today)?)",
        'busiest': r"when (?:was|is) (?:the |our )?(?:room|classroom) (?:the )?busiest(?: today)?",
        'last_capture': r"(?:when was (?:the )?(?:last|latest|most recent) (?:picture|photo|image|capture)(?: taken)?|when did you (?:last take a (?:picture|photo)|take (?:the )?last (?:picture|photo)))",
        'analyzed': r"how many (?:pictures|photos|images|captures) (?:were|have been|have you) (?:analyzed|processed) today",
    }
    return next((key for key, pattern in patterns.items() if re.fullmatch(pattern, text)), None)


def fetch_json(path: str) -> dict:
    # The local assistant bypasses system HTTP proxies; no public login or tokens.
    url = os.environ.get('JARVIS_ROOM_API_URL', DEFAULT_URL).rstrip('/') + path
    try:
        with build_opener(ProxyHandler({})).open(url, timeout=3) as response:
            raw = response.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise RoomDataError('Room response too large')
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise RoomDataError('Invalid room response')
        return value
    except (OSError, URLError, ValueError, UnicodeError) as error:
        raise RoomDataError('Room dashboard unavailable') from error


def count(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def stamp(value, zone):
    if not isinstance(value, str):
        raise RoomDataError('Missing observation time')
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if result.tzinfo is None:
            raise ValueError('No timezone')
        return result.astimezone(zone)
    except ValueError as error:
        raise RoomDataError('Invalid observation time') from error


def clock_label(value, now, zone_name):
    clock = value.strftime('%I:%M %p').lstrip('0')
    day = 'today' if value.date() == now.date() else f"on {value.strftime('%B')} {value.day}, {value.year}"
    zone = 'Pacific time' if zone_name == 'America/Los_Angeles' else zone_name.replace('_', ' ')
    return f'{day} at {clock} {zone}'


def people(value):
    return f'{value} person' if value == 1 else f'{value} people'


def answer(request: str, *, fetch=None, now=None) -> str:
    """Produce text only. Callers decide whether to speak it."""
    fetch = fetch or fetch_json
    try:
        data = fetch('/api/capture-status' if request == 'last_capture' else '/api/occupancy')
        zone_name = data.get('timezone')
        if not isinstance(zone_name, str):
            raise RoomDataError('Missing room timezone')
        zone = ZoneInfo(zone_name)
        current = (now or datetime.now(timezone.utc)).astimezone(zone)
        warning = ' Some saved data is unavailable, so this answer may be incomplete.' if data.get('warnings') else ''
        if request == 'last_capture':
            if data.get('state') == 'unavailable':
                raise RoomDataError('Capture archive unavailable')
            if not data.get('last_capture'):
                return 'No saved picture is available yet.'
            observed = stamp(data['last_capture'], zone)
            if observed > current:
                raise RoomDataError('Future capture')
            suffix = ' Its people-count analysis is still pending.' if data.get('analysis') in ('processing', 'delayed') else ''
            return f'The last saved picture was taken {clock_label(observed, current, zone_name)}.' + suffix
        if request == 'current':
            latest = data.get('latest_observation')
            if latest is None:
                return 'I do not have a saved people-count observation yet. That does not mean the room is empty.' + warning
            if not isinstance(latest, dict) or count(latest.get('count')) is None:
                raise RoomDataError('Invalid latest count')
            observed = stamp(latest.get('time'), zone)
            if observed > current:
                raise RoomDataError('Future observation')
            age = (current - observed).total_seconds()
            suffix = ' This is an older observation, not a live headcount.' if age > 900 else ' This is a recorded estimate, not a live headcount.'
            return f"The last observation estimated {people(latest['count'])} in the room, recorded {clock_label(observed, current, zone_name)}." + suffix + warning
        if data.get('day') != current.date().isoformat() or not isinstance(data.get('observations'), list):
            raise RoomDataError('Daily data unavailable')
        points = []
        for point in data['observations']:
            if not isinstance(point, dict) or count(point.get('count')) is None:
                warning = ' Some saved data is unavailable, so this answer may be incomplete.'
                continue
            try:
                observed = stamp(point.get('time'), zone)
            except RoomDataError:
                warning = ' Some saved data is unavailable, so this answer may be incomplete.'
                continue
            if observed.date() == current.date() and observed <= current:
                points.append((observed, point))
        if request == 'analyzed':
            captures = {point.get('run_id') or observed.isoformat() for observed, point in points if point.get('source') == 'capture'}
            total = len(captures)
            return f"{total} saved {'capture has' if total == 1 else 'captures have'} a completed people-count analysis today." + warning
        if request not in ('peak', 'busiest'):
            raise RoomDataError('Unsupported room question')
        if not points:
            return 'No people-count observations have been recorded today yet. That does not mean the room was empty.' + warning
        peak = max(point['count'] for _, point in points)
        peaks = sorted(observed for observed, point in points if point['count'] == peak)
        when = clock_label(peaks[0], current, zone_name)
        tie = ' That count also appeared in other saved observations today.' if len(peaks) > 1 else ''
        return f"Today's highest recorded occupancy was an estimated {people(peak)}, first observed {when}." + tie + ' This covers saved observations only.' + warning
    except (RoomDataError, OSError, KeyError, TypeError, ValueError):
        return 'I cannot read the room dashboard data right now. I cannot confirm the count. Please try again shortly.'
