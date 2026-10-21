"""Open existing camera photos on the Jarvis desktop without taking a capture."""

# Allow the dedicated runtime interpreters to execute this source file directly.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))

from pathlib import Path
import subprocess
import os


def latest_image(folder):
    folder = Path(folder).resolve()
    candidates = []
    try:
        for path in folder.iterdir():
            try:
                if (path.suffix.lower() in {'.jpg', '.jpeg', '.png', '.webp'}
                        and path.is_file() and path.resolve().is_relative_to(folder)):
                    stat = path.stat()
                    if stat.st_size:
                        candidates.append((stat.st_mtime_ns, path.name, path))
            except OSError:
                continue
    except OSError:
        return None
    return max(candidates)[2] if candidates else None


def latest_masked_image(folder):
    folder = Path(folder).resolve()

    def valid(path):
        try:
            return (path.is_file() and path.resolve().is_relative_to(folder)
                    and path.stat().st_size > 0)
        except OSError:
            return False

    latest = folder / 'latest' / 'combined_overlay.png'
    if valid(latest):
        return latest.resolve()
    candidates = [folder / 'combined_overlay.png']
    candidates += [p for p in folder.glob('runs/*/combined_overlay.png')
                   if (p.parent / 'manifest.json').is_file()]
    available = []
    for path in candidates:
        try:
            if valid(path):
                available.append((path.stat().st_mtime_ns, str(path), path))
        except OSError:
            continue
    return max(available)[2] if available else None


def open_latest_image(folder=None, *, masked=False):
    from jarvis.ui.jarvis_status import desktop_env
    base = folder or Path.home() / 'Jarvis' / ('Masks' if masked else 'Footage')
    path = latest_masked_image(base) if masked else latest_image(base)
    if path is None:
        return ('I do not have a completed masked image to open yet.' if masked
                else 'I do not have a saved camera image to open yet.')
    env = desktop_env()
    if not (env.get('DISPLAY') or env.get('WAYLAND_DISPLAY')):
        # The user service manager can time out under load; use the live session.
        for proc in Path('/proc').iterdir():
            try:
                if not proc.name.isdigit() or proc.stat().st_uid != os.getuid():
                    continue
                if not (proc / 'comm').read_text().strip().startswith(('gnome-shell','gnome-terminal')):
                    continue
                entries = (proc / 'environ').read_bytes().split(b'\0')
                for entry in entries:
                    key, sep, value = entry.partition(b'=')
                    if sep and key.decode() in {'DISPLAY','WAYLAND_DISPLAY','XAUTHORITY','DBUS_SESSION_BUS_ADDRESS','XDG_RUNTIME_DIR'}:
                        env[key.decode()] = value.decode()
                if env.get('DISPLAY') or env.get('WAYLAND_DISPLAY'):
                    break
            except (OSError, UnicodeError):
                continue
    if not (env.get('DISPLAY') or env.get('WAYLAND_DISPLAY')):
        return 'There is no active Jarvis desktop to open the image on.'
    try:
        result = subprocess.run(['gio', 'open', str(path)], env=env,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=8)
        if result.returncode:
            return 'I could not open the image viewer on the Jarvis desktop.'
    except (OSError, subprocess.TimeoutExpired):
        return 'The image viewer did not open in time.'
    return ('Opening the latest completed masked image on the Jarvis desktop.' if masked
            else 'Opening the latest saved camera image on the Jarvis desktop.')
