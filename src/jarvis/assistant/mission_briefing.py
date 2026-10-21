"""Local daily mission briefings: plain text in, spoken and visual briefing out."""
from __future__ import annotations

if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))

import argparse
from datetime import date
import json
import os
from pathlib import Path
import re
import textwrap
import time

MAX_BYTES = 16384
STARTUP_SECONDS = 2.0


class BriefingError(ValueError):
    pass


def briefing_path():
    project = Path(os.environ.get('JARVIS_HOME', Path.home() / 'Jarvis'))
    return Path(os.environ.get('JARVIS_BRIEFING_FILE', project / 'data/mission-briefing.txt')).expanduser()


def parse(text, today=None):
    """Read explicit fields only; briefing text is never executed or sent to AI."""
    fields = {'date': '', 'mission': '', 'tasks': [], 'assignments': [], 'success': ''}
    seen = set()
    section = None
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        if any(not char.isprintable() for char in line):
            raise BriefingError(f'Line {number} contains unsupported control characters.')
        item = re.fullmatch(r'(?:[-*]|\d+[.)])\s+(.+)', line)
        if item:
            if section not in {'tasks', 'assignments'}:
                raise BriefingError(f'Put the list on line {number} under TASKS or ASSIGNMENTS.')
            if len(item[1]) > 240 or len(fields[section]) >= 12:
                raise BriefingError('Use at most 12 items per list, each no longer than 240 characters.')
            fields[section].append(item[1])
            continue
        match = re.fullmatch(r'([A-Za-z ]+):\s*(.*)', line)
        if not match:
            raise BriefingError(f'Check line {number}: use a FIELD: value or a list item beginning with a dash.')
        key = match[1].lower().strip()
        key = {'objective': 'mission', 'success condition': 'success'}.get(key, key)
        if key not in fields:
            raise BriefingError(f'Unknown field on line {number}; use DATE, MISSION, TASKS, ASSIGNMENTS, or SUCCESS.')
        if key in seen:
            raise BriefingError(f'Use only one {key.upper()} section.')
        seen.add(key)
        value = match[2].strip()
        if len(value) > (400 if key == 'success' else 240):
            raise BriefingError(f'The {key.upper()} field is too long.')
        if key in {'tasks', 'assignments'}:
            fields[key] = [value] if value else []
            section = key
        else:
            fields[key] = value
            section = None
    try:
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', fields['date']):
            raise ValueError
        day = date.fromisoformat(fields['date'])
    except ValueError:
        raise BriefingError('Set DATE to a real date using YYYY-MM-DD.') from None
    if not fields['mission'] or not fields['tasks']:
        raise BriefingError('Fill in MISSION and at least one item under TASKS before the briefing.')
    fields['date_warning'] = '' if day == (today or date.today()) else 'DATE CHECK: this briefing is dated ' + day.isoformat() + ', not today.'
    return fields


def load(path=None, today=None):
    try:
        # Bound the read even if a file is accidentally replaced with a huge export.
        with Path(path or briefing_path()).open('rb') as handle:
            raw = handle.read(MAX_BYTES + 1)
    except FileNotFoundError:
        raise BriefingError('Create and fill in mission-briefing.txt before the briefing.') from None
    except OSError:
        raise BriefingError('I could not read mission-briefing.txt. Check its location and permissions.') from None
    if len(raw) > MAX_BYTES:
        raise BriefingError('Keep mission-briefing.txt under 16 kilobytes.')
    try:
        return parse(raw.decode('utf-8-sig'), today)
    except UnicodeError:
        raise BriefingError('Save mission-briefing.txt as UTF-8 text.') from None


def is_briefing_request(text):
    return bool(re.fullmatch(
        r"(?:hey )?(?:jarvis )?(?:(?:can|could|would) you )?(?:please )?"
        r"(?:(?:give|show|read)(?: me)? |(?:begin|start) )?(?:the )?"
        r"(?:mission briefing|daily (?:mission )?briefing|today(?:'s| s) (?:mission|briefing))"
        r"(?: please)?", text))


def spoken(briefing):
    parts = [briefing['date_warning']] if briefing.get('date_warning') else []
    parts += ['Mission briefing. ' + briefing['mission'] + '.']
    parts += [f'Task {index}. {task}.' for index, task in enumerate(briefing['tasks'], 1)]
    if briefing['assignments']:
        parts += ['Team assignments.'] + [item + '.' for item in briefing['assignments']]
    if briefing['success']:
        parts += ['Success condition. ' + briefing['success'] + '.']
    parts += ['Team, you have your mission.']
    return ' '.join(parts)


def preview(briefing):
    lines = ['MISSION BRIEFING / ' + briefing['date']]
    if briefing.get('date_warning'):
        lines += [briefing['date_warning']]
    lines += ['', 'OBJECTIVE', briefing['mission'], '', 'TODAY\'S TASKS']
    lines += [f'{index:02d}  {task}' for index, task in enumerate(briefing['tasks'], 1)]
    if briefing['assignments']:
        lines += ['', 'TEAM ASSIGNMENTS'] + briefing['assignments']
    if briefing['success']:
        lines += ['', 'SUCCESS CONDITION', briefing['success']]
    return '\n'.join(lines)


def present(speak, emit, *, path=None, startup=STARTUP_SECONDS):
    """Run inside the normal voice-command runner, including its reset handling."""
    from jarvis.computer.jarvis_reset import generation
    emit(briefing_payload='', briefing_started='')
    try:
        briefing = load(path)
    except BriefingError as error:
        speak('The mission briefing needs an update. ' + str(error))
        return False
    token = generation()
    emit('action', 'Powering up the daily mission briefing.',
         briefing_payload=json.dumps(briefing, ensure_ascii=False),
         briefing_started=str(time.time()), result='running',
         activity_caption='Preparing the mission briefing', activity_step='briefing', model_pending='0')
    deadline = time.monotonic() + startup
    while time.monotonic() < deadline:
        if generation() != token:
            return False
        time.sleep(min(.05, max(0, deadline - time.monotonic())))
    if generation() != token:
        return False
    # Keep long valid briefings within the existing per-utterance playback timeout.
    for chunk in textwrap.wrap(spoken(briefing), width=900, break_long_words=False, break_on_hyphens=False):
        if generation() != token:
            return False
        speak(chunk)
    return True


def payload(data):
    try:
        value = json.loads(data.get('briefing_payload', ''))
        if not isinstance(value, dict) or not isinstance(value.get('tasks'), list) or not value['tasks']:
            return None
        if not all(isinstance(value.get(k), str) for k in ('mission', 'date', 'success', 'date_warning')):
            return None
        if not isinstance(value.get('assignments'), list):
            return None
        if not all(isinstance(item, str) for item in value['tasks'] + value['assignments']):
            return None
        return value
    except (ValueError, TypeError):
        return None


def active(data):
    return not data.get('attention') and data.get('stage') not in {'starting', 'listening', 'captured', 'cancelled', 'error', 'attention'} and payload(data) is not None


def content_lines(briefing, width, roomy=False):
    from jarvis.ui.jarvis_console_layout import wrap, fit, cells
    lines = []
    framed = width >= 24
    inside = max(1, width - 4 if framed else width)
    def section(title, items, accent=1):
        if lines:
            lines.append(('', 0))
        if framed:
            label = fit(' ' + title + ' ', width - 4)
            lines.append(('╭─' + label + '─' * (width - cells(label) - 3) + '╮', accent))
        else:
            lines.append((title, accent))
        if framed and roomy:
            lines.append(('│' + ' ' * (width - 2) + '│', 0))
        for item_index, (text, style, prefix) in enumerate(items):
            if framed and roomy and item_index:
                lines.append(('│' + ' ' * (width - 2) + '│', 0))
            for index, line in enumerate(wrap(text, max(1, inside - len(prefix)))):
                text = (prefix if index == 0 else ' ' * len(prefix)) + line
                text = fit(text, inside)
                if framed:
                    text = '│ ' + text + ' ' * (inside - cells(text)) + ' │'
                lines.append((text, style))
        if framed:
            if roomy:
                lines.append(('│' + ' ' * (width - 2) + '│', 0))
            lines.append(('╰' + '─' * (width - 2) + '╯', accent))
    if briefing.get('date_warning'):
        section('DATE CHECK', [(briefing['date_warning'], 4, '')], 4)
    section('PRIMARY OBJECTIVE', [(briefing['mission'], 7, '')])
    section("TODAY'S TASKS", [(task, 0, f'{index:02d} › ' if width >= 12 else '')
                               for index, task in enumerate(briefing['tasks'], 1)])
    if briefing['assignments']:
        section('TEAM ASSIGNMENTS', [(item, 0, '› ' if width >= 12 else '') for item in briefing['assignments']])
    if briefing['success']:
        section('SUCCESS CONDITION', [(briefing['success'], 0, '')], 11)
    return lines


def viewport(height):
    return max(1, height - (2 if height < 8 else 7 if height < 18 else 10))


def display_lines(briefing, width, height):
    if height >= 36:
        roomy = content_lines(briefing, width, roomy=True)
        if len(roomy) <= viewport(height):
            return roomy
    return content_lines(briefing, width)


def scroll_limit(data, width, height):
    briefing = payload(data)
    return max(0, len(display_lines(briefing, width, height)) - viewport(height)) if briefing else 0


def frame(data, width, height, reactor, *, now=None, scroll=0):
    from jarvis.ui.jarvis_console_layout import fit, cells
    now = time.time() if now is None else now
    briefing = payload(data)
    total_width = max(1, min(width - 2, 148))
    origin = max(0, (width - total_width) // 2)
    large = total_width >= 128 and height >= 44
    aside = 53 if large else 35 if total_width >= 100 and height >= 29 else 0
    body_width = total_width - aside - 3 if aside else total_width
    result = []
    def put(row, col, text, style=0, limit=None):
        if not (0 <= row < height - 1 and 0 <= col < width - 1):
            return
        limit = min(width - col - 1, limit if limit is not None else total_width)
        if limit > 0:
            result.append((row, col, fit(text, limit), style, limit))
    def rule(row, label, style=5):
        label = fit(' ' + label + ' ', max(0, total_width - 4))
        put(row, origin, '──' + label + '─' * max(0, total_width - cells(label) - 2), style)
    if height >= 18 and total_width >= 40:
        put(0, origin, '╔' + '═' * (total_width - 2) + '╗', 5)
        title = 'J A R V I S  /  MISSION CONTROL'
        stamp = 'DAILY OPERATIONS'
        gap = total_width - 6 - cells(title) - cells(stamp)
        middle = title + ' ' * gap + stamp if gap >= 3 else title
        middle = fit(middle, total_width - 6)
        put(1, origin, '║  ' + middle + ' ' * (total_width - 4 - cells(middle)) + '║', 1)
        put(2, origin, '╚' + '═' * (total_width - 2) + '╝', 5)
        summary = 'MISSION BRIEFING / ' + briefing['date']
        count = f'{len(briefing["tasks"]):02d} DIRECTIVES'
        gap = total_width - cells(summary) - len(count)
        put(4, origin, summary + (' ' * gap + count if gap >= 2 else ''), 4 if briefing['date_warning'] else 11)
    else:
        put(0, origin, 'MISSION / ' + briefing['date'], 1)
        if height >= 8:
            put(2, origin, 'J A R V I S / MISSION CONTROL', 5)
    try:
        age = max(0, now - float(data.get('briefing_started', 0)))
    except (TypeError, ValueError):
        age = STARTUP_SECONDS
    starting = age < STARTUP_SECONDS and width >= 48 and height >= 18
    art = reactor(dict(data, stage='action', result='running') if starting else data, now=now, large=large)
    if starting:
        # Keep the startup grid intact even in a short classroom terminal.
        hero = art[3:-3]
        if height >= (44 if large else 35):
            hero = art
        if len(hero) > height - 10:
            hero = [(line, 1 if int(age * 4) % 2 else 5) for line in [
                '       .-========-.       ',
                "    .-'            '-.    ",
                '   /    .------.      \\   ',
                '  |     |JARVIS|       |  ',
                "   \\    '------'      /   ",
                "    '-.            .-'    ",
                "       '-========-'       "]]
        art_width = max(cells(line) for line, _ in hero)
        art_col = max(origin, origin + (total_width - art_width) // 2)
        for index, (line, style) in enumerate(hero):
            if index + 6 >= height - 4:
                break
            put(index + 6, art_col, line, style)
        length = min(30, max(6, total_width - 40))
        filled = min(length, int(age / STARTUP_SECONDS * length))
        rule(height - 4, 'BRIEFING UPLINK', 5)
        put(height - 2, origin, '[' + '■' * filled + '·' * (length - filled) + ']  REACTOR ONLINE', 1)
    else:
        lines = display_lines(briefing, body_width, height)
        available = viewport(height)
        scroll = min(max(0, scroll), max(0, len(lines) - available))
        top = 1 if height < 8 else 4 if height < 18 else 6
        reveal = min(1., max(0., (age - STARTUP_SECONDS) / .9))
        for index, (line, style) in enumerate(lines[scroll:scroll + available]):
            if index > reveal * available and scroll == 0:
                style = 3
            row = top + index
            if line.startswith('│') and line.endswith('│'):
                put(row, origin, '│', 5, 1)
                put(row, origin + 1, line[1:-1], style, body_width - 2)
                put(row, origin + body_width - 1, '│', 5, 1)
            else:
                put(row, origin, line, style, body_width)
        if aside:
            col = origin + body_width + 3
            label = ' JARVIS CORE '
            put(6, col, '╭─' + label + '─' * (aside - len(label) - 3) + '╮', 1, aside)
            reactor_rows = art if height >= (44 if large else 35) else art[3:-3]
            for index, (line, style) in enumerate(reactor_rows):
                row = 7 + index
                # Complete the bordered card without colliding with the footer.
                if row >= height - 5:
                    break
                content = fit(line, aside - 4)
                pad = max(0, (aside - 2 - cells(content)) // 2)
                put(row, col, '│', 5, 1)
                put(row, col + 1, ' ' * pad + content + ' ' * (aside - 2 - pad - cells(content)), style, aside - 2)
                put(row, col + aside - 1, '│', 5, 1)
            bottom = min(7 + len(reactor_rows), height - 5)
            put(bottom, col, '╰' + '─' * (aside - 2) + '╯', 5, aside)
        if height >= 18:
            rule(height - 4, 'MISSION READY', 5)
        if height >= 8:
            hint = f'LINES {scroll + 1}-{min(len(lines), scroll + available)} / {len(lines)}  |  UP/DOWN SCROLL' if len(lines) > available else 'TEAM / YOU HAVE YOUR MISSION'
            put(height - 2, origin, hint, 3)
    return result, body_width


def main():
    parser = argparse.ArgumentParser(description='Preview the local mission briefing without audio or changing the console.')
    parser.add_argument('--preview', action='store_true', help='Print the briefing; this is also the default.')
    parser.add_argument('--file', type=Path, help='Preview a different briefing text file.')
    args = parser.parse_args()
    try:
        print(preview(load(args.file)))
    except BriefingError as error:
        print('Briefing needs an update: ' + str(error))
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
