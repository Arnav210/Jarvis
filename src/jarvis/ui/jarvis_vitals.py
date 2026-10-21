#!/usr/bin/env python3
"""Read-only system vitals for a separate Jarvis terminal or demo monitor."""

# Allow the dedicated runtime interpreters to execute this source file directly.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))

import argparse
import copy
import curses
import datetime
import fcntl
import json
import math
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import threading
import time
from collections import deque

PROJECT = Path(__file__).resolve().parents[3]
USER_SERVICES = [('Wake listener', 'jarvis-wake.service'), ('Speech recognition', 'jarvis-stt.service'),
                 ('Vision / SAM3', 'jarvis-sam3.service'), ('Local music', 'jarvis-music.service'),
                 ('Spotify', 'jarvis-spotify.service'), ('Room stream', 'jarvis-stream.service')]
SYSTEM_SERVICES = [('Local AI', 'ollama.service'), ('Depth vision', 'jarvis.vision.depth_service.service')]


def read_cpu(path=Path('/proc/stat')):
    result = {}
    for line in path.read_text().splitlines():
        parts = line.split()
        if parts and (parts[0] == 'cpu' or parts[0][3:].isdigit() and parts[0].startswith('cpu')):
            ticks = [int(n) for n in parts[1:9]]  # Guest time is already included in user/nice.
            result[parts[0]] = (sum(ticks), ticks[3], ticks[4] if len(ticks) > 4 else 0)
    return result


def cpu_delta(previous, current):
    result = {}
    for name, (total, idle, wait) in current.items():
        old = previous.get(name)
        if not old or total <= old[0]:
            result[name] = {'busy': None, 'wait': None}
            continue
        elapsed = total - old[0]
        clamp = lambda value: max(0., min(100., value))
        result[name] = {'busy': clamp(100 * (elapsed - (idle-old[1]) - (wait-old[2])) / elapsed),
                        'wait': clamp(100 * (wait-old[2]) / elapsed)}
    return result


def memory_info(path=Path('/proc/meminfo')):
    values = {}
    for line in path.read_text().splitlines():
        key, value = line.split(':', 1)
        values[key] = int(value.split()[0]) * 1024
    total = values['MemTotal']
    available = values.get('MemAvailable', values.get('MemFree', 0))
    swap = values.get('SwapTotal', 0)
    return {'total': total, 'available': available, 'used': max(0, total-available),
            'percent': 100 * (total-available) / total if total else None,
            'swap_total': swap, 'swap_used': max(0, swap-values.get('SwapFree', 0))}


def temperatures(base=Path('/sys/class/thermal')):
    result = []
    for zone in sorted(base.glob('thermal_zone*')):
        try:
            value = float((zone/'temp').read_text()) / 1000
            if math.isfinite(value) and -20 < value < 150:
                name = (zone/'type').read_text().strip().replace('x86_pkg_temp', 'CPU package')
                result.append({'name': name, 'celsius': value})
        except (OSError, ValueError):
            continue
    return result


def service_info(services, user=False):
    command = ['systemctl', *(['--user'] if user else []), 'show',
               *[unit for _, unit in services], '-p', 'Id', '-p', 'LoadState',
               '-p', 'ActiveState', '-p', 'SubState', '--no-pager']
    try:
        response = subprocess.run(command, capture_output=True, text=True, timeout=2)
        records = {}
        for block in response.stdout.strip().split('\n\n'):
            fields = dict(line.split('=', 1) for line in block.splitlines() if '=' in line)
            if fields.get('Id'):
                records[fields['Id']] = fields
        result = []
        for label, unit in services:
            fields = records.get(unit, {})
            if fields.get('LoadState') == 'not-found':
                state, detail = 'not-installed', 'Not configured'
            elif fields:
                state = fields.get('ActiveState', 'unknown')
                detail = fields.get('SubState', state)
            else:
                state, detail = 'unknown', 'Unavailable'
            result.append({'name': label, 'state': state, 'detail': detail})
        return result
    except (OSError, subprocess.TimeoutExpired):
        return [{'name': label, 'state': 'unknown', 'detail': 'Check timed out'} for label, _ in services]


def gpu_info():
    tool = shutil.which('nvidia-smi')
    if not tool:
        return []
    try:
        response = subprocess.run([tool, '--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu',
                                   '--format=csv,noheader,nounits'], capture_output=True, text=True, timeout=2)
        result = []
        for line in response.stdout.splitlines():
            name, busy, used, total, temp = [part.strip() for part in line.split(',')]
            result.append({'name': name, 'busy': float(busy), 'used': float(used)*1024**2,
                           'total': float(total)*1024**2, 'temperature': float(temp)})
        return result
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return []


class Monitor:
    def __init__(self):
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.ready = threading.Event()
        self.data = {'host': socket.gethostname(), 'updated': 0, 'services': [], 'gpu': [],
                     'cpu_history': [], 'memory_history': [], 'errors': []}
        self.threads = [threading.Thread(target=self.metrics, daemon=True),
                        threading.Thread(target=self.services, daemon=True)]
        for thread in self.threads:
            thread.start()

    def snapshot(self):
        with self.lock:
            return copy.deepcopy(self.data)

    def metrics(self):
        previous = {}
        cpu_history, memory_history = deque(maxlen=60), deque(maxlen=60)
        while not self.stop.is_set():
            update = {'cpu': {}, 'memory': None, 'disk': None, 'load': [], 'uptime': 0}
            errors = []
            try:
                current = read_cpu()
                update['cpu'] = cpu_delta(previous, current)
                previous = current
                busy = update['cpu'].get('cpu', {}).get('busy')
                if busy is not None:
                    cpu_history.append(busy)
                update['load'] = os.getloadavg()
                update['cores'] = len([key for key in current if key != 'cpu'])
                update['uptime'] = float(Path('/proc/uptime').read_text().split()[0])
            except (OSError, ValueError, IndexError) as error:
                errors.append('CPU readings unavailable')
            try:
                update['memory'] = memory_info()
                memory_history.append(update['memory']['percent'])
            except (OSError, ValueError, KeyError):
                errors.append('Memory readings unavailable')
            try:
                disk = shutil.disk_usage(PROJECT)
                update['disk'] = dict(total=disk.total, used=disk.used, free=disk.free)
            except OSError:
                errors.append('Disk readings unavailable')
            update['temperatures'] = temperatures()
            update.update(cpu_history=list(cpu_history), memory_history=list(memory_history),
                          errors=errors, updated=time.time())
            with self.lock:
                self.data.update(update)
            if len(cpu_history):
                self.ready.set()
            self.stop.wait(1)

    def services(self):
        while not self.stop.is_set():
            records = service_info(USER_SERVICES, user=True) + service_info(SYSTEM_SERVICES)
            gpu = gpu_info()
            with self.lock:
                self.data.update(services=records, gpu=gpu, services_updated=time.time())
            self.stop.wait(5)

    def close(self):
        self.stop.set()
        for thread in self.threads:
            thread.join(timeout=.2)


def size(value):
    return f'{value / 1024**3:.1f} GiB'


def percent(value):
    return '--' if value is None else f'{value:.1f}%'


def bar(value, width):
    count = round(max(0., min(100., value or 0.)) / 100 * width)
    return '█'*count + '░'*(width-count)


def spark(values, width):
    return ''.join('▁▂▃▄▅▆▇█'[min(7, max(0, round(value / 100 * 7)))] for value in values[-width:]) or 'Collecting history…'


def heat(value):
    return 4 if value is not None and value >= 90 else 2 if value is not None and value >= 75 else 1


def panels(data, width):
    inner = max(8, width-4)
    cpu = data.get('cpu', {})
    aggregate = cpu.get('cpu', {})
    busy = aggregate.get('busy')
    cpu_rows = [(f'PROCESSOR   {percent(busy)} busy', heat(busy)), (bar(busy, inner), heat(busy)),
                ('Recent samples  '+spark(data.get('cpu_history', []), max(8, inner-16)), 1), ('', 0)]
    cores = [(name, values) for name, values in cpu.items() if name != 'cpu']
    for name, values in cores[:8]:
        cpu_rows.append((f'Core {int(name[3:])+1:02d}  {bar(values.get("busy"), max(8, inner-22))}  {percent(values.get("busy"))}', heat(values.get('busy'))))
    if len(cores) > 8:
        cpu_rows.append((f'+ {len(cores)-8} more logical cores included in total', 3))
    cpu_rows += [('', 0), ('Disk wait  '+percent(aggregate.get('wait')), 3),
                 ('Load 1 / 5 / 15 min  '+' / '.join(f'{n:.2f}' for n in data.get('load', [])), 3)]
    mem = data.get('memory')
    memory_rows = [('Waiting for memory readings…', 3)]
    if mem:
        memory_rows = [(f'{size(mem["used"])} used / {size(mem["total"])}   {percent(mem["percent"])}', heat(mem['percent'])),
                       (bar(mem['percent'], inner), heat(mem['percent'])),
                       ('Available   '+size(mem['available']), 0),
                       ('Swap used   '+size(mem['swap_used'])+' / '+size(mem['swap_total']), 2 if mem['swap_used'] else 3),
                       ('Recent samples  '+spark(data.get('memory_history', []), max(8, inner-16)), 1)]
    disk = data.get('disk')
    disk_rows = [('Disk readings unavailable', 3)]
    if disk:
        used = 100*disk['used']/disk['total'] if disk['total'] else 0
        disk_rows = [(size(disk['free'])+' FREE', heat(used)), (bar(used, inner), heat(used)),
                     (size(disk['used'])+' used / '+size(disk['total'])+' total', 3),
                     ('Filesystem containing the Jarvis folder', 3)]
    service_rows = []
    labels = {'active': 'ONLINE', 'inactive': 'STOPPED', 'failed': 'FAILED', 'activating': 'STARTING',
              'deactivating': 'STOPPING', 'not-installed': 'NOT CONFIGURED', 'unknown': 'UNAVAILABLE'}
    for item in data.get('services', []):
        state = item['state']
        color = 5 if state == 'active' else 4 if state == 'failed' else 3 if state in {'not-installed', 'inactive', 'unknown'} else 2
        label = 'RETRYING' if item['detail'] == 'auto-restart' else labels.get(state, state.upper())
        service_rows.append((f'{item["name"]:<20} {label}', color))
    if not service_rows:
        service_rows = [('Checking services…', 3)]
    sensors = [(item['name']+'   '+f'{item["celsius"]:.1f} °C', heat(item['celsius'])) for item in data.get('temperatures', [])]
    gpu_rows = [('Usage data unavailable on this host', 3)]
    if data.get('gpu'):
        gpu_rows = []
        for gpu in data['gpu']:
            gpu_rows.extend([(gpu['name'], 1), (percent(gpu['busy'])+' busy  /  '+f'{gpu["temperature"]:.0f} °C', heat(gpu['busy'])),
                             (size(gpu['used'])+' / '+size(gpu['total'])+' VRAM', 3)])
    return [('CPU ACTIVITY', cpu_rows), ('MEMORY', memory_rows), ('STORAGE', disk_rows),
            ('JARVIS SERVICES', service_rows), ('TEMPERATURE', sensors or [('Sensor readings unavailable', 3)]), ('GPU', gpu_rows)]


def compose(data, width, height, now=None):
    now = time.time() if now is None else now
    area = max(12, min(136, width-2));origin = max(0, (width-area)//2)
    result = []
    def put(row, col, text, style=0):
        if 0 <= row < height-1 and 0 <= col < width-1:
            result.append((row, col, text[:max(0, width-col-1)], style))
    put(0, origin, 'J A R V I S  /  SYSTEM VITALS', 1)
    uptime = int(data.get('uptime', 0))
    age = max(0, now-data.get('updated', 0)) if data.get('updated') else None
    freshness = 'CONNECTING' if age is None else 'LIVE' if age < 3 else f'LAST SAMPLE {age:.0f}s AGO'
    put(2, origin, f'{data.get("host", "Jarvis")}  ·  {freshness}  ·  UPTIME {uptime//86400}d {uptime//3600%24:02d}h {uptime//60%60:02d}m  ·  '+datetime.datetime.fromtimestamp(now).strftime('%H:%M:%S'), 3 if age is None or age < 3 else 2)
    if area < 100 or height < 38:
        busy = data.get('cpu', {}).get('cpu', {}).get('busy')
        compact = [('CPU   '+percent(busy)+'   '+bar(busy, max(4, area-20)), heat(busy))]
        memory = data.get('memory')
        compact += [('RAM   '+(size(memory['used'])+' / '+size(memory['total'])+'   '+percent(memory['percent']) if memory else 'Unavailable'), heat(memory['percent']) if memory else 3)]
        disk = data.get('disk')
        compact += [('DISK  '+(size(disk['free'])+' free / '+size(disk['total']) if disk else 'Unavailable'), 3)]
        sensors = data.get('temperatures', [])
        compact += [('TEMP  '+(f'{sensors[0]["celsius"]:.1f} °C' if sensors else 'Unavailable'), 3),
                    ('', 0), ('JARVIS SERVICES', 1)]
        compact += panels(data, area)[3][1]
        for row, (text, style) in enumerate(compact, 4):
            if row >= height-2:
                put(height-2, origin, 'Enlarge the terminal for all readings.', 2)
                break
            put(row, origin, text, style)
        return result
    columns = 2 if area >= 100 else 1
    panel_width = (area-3)//2 if columns == 2 else area
    groups = panels(data, panel_width)
    positions = [(0, 4), (0, 4+len(groups[0][1])+5), (0, 4+len(groups[0][1])+len(groups[1][1])+10)]
    if columns == 2:
        positions += [(panel_width+3, 4), (panel_width+3, 4+len(groups[3][1])+5),
                      (panel_width+3, 4+len(groups[3][1])+len(groups[4][1])+10)]
    else:
        y = 4; positions = []
        for _, content in groups:
            positions.append((0, y));y += len(content)+4
    for (title, content), (x, y) in zip(groups, positions):
        title = title[:max(1, panel_width-6)]
        put(y, origin+x, '┌─ '+title+' '+'─'*max(0, panel_width-len(title)-5)+'┐', 1)
        for i, (text, style) in enumerate(content):
            put(y+i+1, origin+x, '│', 3)
            put(y+i+1, origin+x+2, text[:max(1, panel_width-4)].ljust(max(1, panel_width-4)), style)
            put(y+i+1, origin+x+panel_width-1, '│', 3)
        put(y+len(content)+1, origin+x, '└'+'─'*max(0, panel_width-2)+'┘', 3)
    if data.get('errors'):
        put(height-2, origin, '  ·  '.join(data['errors']), 2)
    return result


def draw(screen):
    curses.curs_set(0);screen.timeout(250)
    colors = curses.has_colors()
    if colors:
        curses.start_color();curses.use_default_colors()
        for number, value in [(1, curses.COLOR_CYAN), (2, curses.COLOR_YELLOW), (3, 244 if curses.COLORS >= 256 else curses.COLOR_WHITE), (4, curses.COLOR_RED), (5, curses.COLOR_GREEN)]:
            curses.init_pair(number, value, -1)
    monitor = Monitor()
    try:
        while True:
            height, width = screen.getmaxyx();screen.erase()
            for row, col, text, style in compose(monitor.snapshot(), width, height):
                attr = (curses.color_pair(style) if colors else 0) | (curses.A_BOLD if style in {1, 4, 5} else 0)
                try:
                    screen.addnstr(row, col, text, max(0, width-col-1), attr)
                except curses.error:
                    pass
            footer = 'Q close  ·  Read-only monitor  ·  Metrics ~1s / services ~5s'
            try:
                screen.addnstr(height-1, 1, footer, max(0, width-2), curses.A_DIM)
            except curses.error:
                pass
            screen.refresh()
            if screen.getch() in (ord('q'), ord('Q')):
                break
    finally:
        monitor.close()


def runtime():
    path = Path(os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}')) / 'jarvis-vitals'
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


def open_window():
    from jarvis.ui.jarvis_status import desktop_env
    with (runtime()/'launch.lock').open('a') as launch, (runtime()/'desktop.lock').open('a') as desktop:
        try:
            fcntl.flock(launch, fcntl.LOCK_EX|fcntl.LOCK_NB)
            fcntl.flock(desktop, fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            return 'System vitals is already open or starting.'
        pending = runtime()/'pending'
        try:
            if 0 <= time.monotonic()-float(pending.read_text()) < 5:
                return 'System vitals is already starting.'
        except (OSError, ValueError):
            pass
        env = desktop_env()
        if not (env.get('DISPLAY') or env.get('WAYLAND_DISPLAY')):
            raise RuntimeError('No desktop session found. Run jarvis-vitals in your SSH terminal.')
        terminal = shutil.which('gnome-terminal')
        if not terminal:
            raise RuntimeError('Desktop terminal unavailable. Run jarvis-vitals in your SSH terminal.')
        pending.write_text(str(time.monotonic()))
        with (runtime()/'window.log').open('a') as log:
            subprocess.Popen([terminal, '--window', '--title=JARVIS | System Vitals', '--geometry=124x44',
                              '--hide-menubar', '--', '/usr/bin/python3', str(Path(__file__).resolve()), '--desktop-view'],
                             env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
        return 'Opened JARVIS System Vitals on the desktop.'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--open', action='store_true', help='Open a separate desktop terminal for the second monitor.')
    mode.add_argument('--json', action='store_true', help='Print one snapshot without opening a window.')
    mode.add_argument('--desktop-view', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.open:
        print(open_window());return 0
    if args.json:
        monitor = Monitor()
        try:
            monitor.ready.wait(timeout=4)
            print(json.dumps(monitor.snapshot(), indent=2))
        finally:
            monitor.close()
        return 0
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        parser.error('Run jarvis-vitals in an interactive terminal, or use --open or --json.')
    if args.desktop_view:
        with (runtime()/'desktop.lock').open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:
                return 0
            (runtime()/'pending').unlink(missing_ok=True)
            curses.wrapper(draw)
    else:
        curses.wrapper(draw)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, curses.error) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
