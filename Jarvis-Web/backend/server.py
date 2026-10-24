"""Jarvis's read-only capture archive and paged object-monitoring history."""
from collections import deque
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
import ast
from io import BytesIO
import json
import math
import os
import re
import subprocess
import time as clock_time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageDraw
from face_privacy import FacePrivacy, PrivacyUnavailable

FACE_BLUR_ENABLED = False  # Paused at the user's request.
IMAGE_PRIVACY_VERSION = "faces-v1" if FACE_BLUR_ENABLED else "unblurred-v1"
FACE_PRIVACY = FacePrivacy()
PRIVACY_HEADERS = {"Cache-Control": "private, no-store", "X-Privacy-Mode": IMAGE_PRIVACY_VERSION, "X-Content-Type-Options": "nosniff"}

app = FastAPI()
# Preserve the existing dashboard access configuration.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])
BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"
JARVIS_DIR = BASE_DIR.parent
RUNS_DIR = JARVIS_DIR / "Masks" / "runs"
MONITOR_DIR = JARVIS_DIR / "object_monitor" / "object_monitor"
SAM3_SOURCE = JARVIS_DIR / "src" / "jarvis" / "vision" / "sam3_process.py"
EVENT_TYPES = {"new_object", "object_missing", "object_returned", "person_count_changed"}
# Keep image access allowlisted; optional face processing is currently paused.
def privacy_response(result):
    data, count = result
    return Response(data, media_type="image/png",
                    headers={**PRIVACY_HEADERS, "X-Privacy-Mode": "faces-v1" if FACE_BLUR_ENABLED else "unblurred-v1", "X-Faces-Blurred": str(count)})


def privacy_image_response(canvas, original):
    if not FACE_BLUR_ENABLED:
        output = BytesIO()
        canvas.save(output, format="PNG")
        return privacy_response((output.getvalue(), 0))
    try:
        return privacy_response(FACE_PRIVACY.render(canvas, original))
    except PrivacyUnavailable as error:
        raise HTTPException(503, "Image withheld: face privacy processing is unavailable",
                            headers={"Cache-Control": "no-store"}) from error


@app.get("/runs/{run_id}/{filename}")
def private_capture_image(run_id: str, filename: str):
    folder = (RUNS_DIR / run_id).resolve()
    if folder.parent != RUNS_DIR.resolve() or not folder.is_dir():
        raise HTTPException(404, "Capture not found")
    if not re.fullmatch(r"(?:original|combined_overlay)\.(?:jpg|jpeg|png|webp)", filename, re.I):
        raise HTTPException(404, "Image not found")
    path = inside_file(folder, filename)
    if path is None:
        raise HTTPException(404, "Image not found")
    if not FACE_BLUR_ENABLED:
        return FileResponse(path, headers={**PRIVACY_HEADERS, "X-Faces-Blurred": "0"})
    manifest = run_manifest(folder)
    original = inside_file(folder, manifest.get("saved_original")) if manifest else None
    if original is None:
        original = next((p for p in (inside_file(folder, "original." + ext)
                        for ext in ("png", "jpg", "jpeg", "webp")) if p is not None), None)
    if original is None:
        raise HTTPException(409, "Image withheld: its source photograph is unavailable")
    try:
        return privacy_response(FACE_PRIVACY.file(path, original))
    except PrivacyUnavailable as error:
        raise HTTPException(503, "Image withheld: face privacy processing is unavailable",
                            headers={"Cache-Control": "no-store"}) from error

app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


@app.get("/")
def read_root():
    return FileResponse(FRONTEND_DIR / "index.html")


def sam3_settings():
    """Read literal settings without importing SAM3 or running model inference."""
    settings = {}
    try:
        tree = ast.parse(SAM3_SOURCE.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id in {"prompts", "palette"}:
                        try:
                            settings[target.id] = ast.literal_eval(node.value)
                        except (ValueError, TypeError):
                            pass
    except (OSError, SyntaxError, UnicodeError):
        pass
    prompts = settings.get("prompts", [])
    prompts = list(dict.fromkeys(p for p in prompts if isinstance(p, str) and p)) if isinstance(prompts, (list, tuple)) else []
    palette = settings.get("palette", [])
    palette = [tuple(c) for c in palette if isinstance(c, (list, tuple)) and len(c) == 3 and all(isinstance(v, int) and 0 <= v <= 255 for v in c)] if isinstance(palette, (list, tuple)) else []
    return prompts, palette


@app.get("/api/mask-categories")
def get_mask_categories():
    prompts, _ = sam3_settings()
    return {"categories": prompts, "source_available": bool(prompts)}


def inside_file(folder, relative):
    if not isinstance(relative, str) or not relative:
        return None
    candidate = (folder / relative).resolve()
    return candidate if candidate.is_relative_to(folder.resolve()) and candidate.is_file() else None


def run_manifest(folder):
    try:
        value = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        if isinstance(value, dict) and isinstance(value.get("detections"), list):
            return value
    except (OSError, ValueError, UnicodeError):
        pass
    return None


def manifest_categories(manifest):
    prompts = manifest.get("prompts", [])
    prompts = prompts if isinstance(prompts, list) else []
    detected = [d.get("prompt") for d in manifest["detections"] if isinstance(d, dict)]
    return list(dict.fromkeys(p for p in [*prompts, *detected] if isinstance(p, str) and p))


def draw_mask_contours(canvas, outlines, width=1):
    """Draw the boundaries of every mask component and hole without changing masks."""
    import cv2
    import numpy as np
    pixels = np.array(canvas.convert("RGB"))
    for mask, color in outlines:
        binary = np.array(mask.convert("L"))
        contours, _ = cv2.findContours(binary, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(pixels, contours, -1, color, width, lineType=cv2.LINE_8)
    return Image.fromarray(pixels)


@app.get("/api/overlay/{run_id}")
def filtered_overlay(run_id: str, categories: list[str] | None = Query(None)):
    folder = (RUNS_DIR / run_id).resolve()
    if folder.parent != RUNS_DIR.resolve() or not folder.is_dir():
        raise HTTPException(404, "Capture not found")
    manifest = run_manifest(folder)
    if manifest is None:
        raise HTTPException(409, "This capture has no individual mask manifest")
    prompts = manifest_categories(manifest)
    requested = set(prompts if categories is None else (c for c in categories if c))
    configured, palette = sam3_settings()
    if not requested.issubset(set(prompts) | set(configured)):
        raise HTTPException(400, "Unknown mask category")
    original = inside_file(folder, manifest.get("saved_original"))
    if original is None:
        raise HTTPException(409, "The saved original is unavailable")
    try:
        with Image.open(original) as image:
            canvas = image.convert("RGB")
        annotations, outlines = [], []
        for detection in manifest["detections"]:
            if not isinstance(detection, dict) or not isinstance(detection.get("prompt"), str) or detection["prompt"] not in requested:
                continue
            mask_path = inside_file(folder, detection.get("raw_mask"))
            if mask_path is None:
                raise HTTPException(409, "An individual mask is unavailable for this capture")
            category_index = prompts.index(detection["prompt"])
            index = detection.get("index", 0)
            index = index if isinstance(index, int) else 0
            color = palette[(category_index * 7 + index) % len(palette)] if palette else (201, 237, 155)
            with Image.open(mask_path) as mask_image:
                mask = mask_image.convert("L").point(lambda value: 255 if value else 0)
            if mask.size != canvas.size:
                raise HTTPException(409, "The saved mask dimensions do not match the capture")
            tinted = Image.blend(canvas, Image.new("RGB", canvas.size, color), 0.22)
            canvas = Image.composite(tinted, canvas, mask)
            outlines.append((mask, color))
            box = mask.getbbox()
            if box is not None:
                score = detection.get("score")
                label = detection["prompt"] + (f" {score:.2f}" if isinstance(score, (int, float)) else "")
                annotations.append((box, label, color))
        canvas = draw_mask_contours(canvas, outlines)
        draw = ImageDraw.Draw(canvas)
        for box, label, color in annotations:
            draw.text((box[0] + 4, max(2, box[1] - 14)), label, fill=color, stroke_width=2, stroke_fill=(0, 0, 0))
        return privacy_image_response(canvas, original)
    except (OSError, ValueError) as error:
        raise HTTPException(409, "Saved mask data could not be rendered") from error


@app.get("/api/latest")
def get_latest_runs(day: str | None = None, limit: int = 46):
    zone, zone_name = room_timezone()
    if not 1 <= limit <= 200:
        raise HTTPException(400, "Limit must be between 1 and 200")
    if day is not None:
        try:
            if date.fromisoformat(day).isoformat() != day:
                raise ValueError("Use YYYY-MM-DD")
        except ValueError as error:
            raise HTTPException(400, "Choose a valid date in YYYY-MM-DD format") from error
    if not RUNS_DIR.is_dir():
        return {"runs": [], "day": day, "timezone": zone_name}
    folders = (p for p in RUNS_DIR.iterdir() if p.is_dir())
    results = []
    for folder in folders:
        try:
            files = list(folder.iterdir())
        except OSError:
            continue
        original = next((p.name for p in files if p.is_file() and p.name.lower().startswith("original.")), None)
        overlay = next((p.name for p in files if p.is_file() and p.name.lower().startswith("combined_overlay.")), None)
        if not (original or overlay):
            continue
        change_log = None
        try:
            value = json.loads((folder / "changes.json").read_text(encoding="utf-8"))
            if isinstance(value, dict):
                change_log = value
        except (OSError, ValueError, UnicodeError):
            pass
        manifest = run_manifest(folder)
        stamp = None
        if manifest and isinstance(manifest.get("captured_at"), str):
            try:
                stamp = datetime.fromisoformat(manifest["captured_at"].replace("Z", "+00:00"))
                if stamp.tzinfo is None:
                    stamp = stamp.replace(tzinfo=zone)
                stamp = stamp.astimezone(zone)
            except ValueError:
                pass
        if stamp is None:
            try:
                stamp = datetime.strptime(folder.name[:19], "%Y-%m-%d_%H-%M-%S").replace(tzinfo=zone)
            except ValueError:
                pass
        if day is not None and (stamp is None or stamp.date().isoformat() != day):
            continue
        captured_at = stamp.isoformat() if stamp else None
        categories = manifest_categories(manifest) if manifest else []
        counts = {category: sum(1 for d in manifest["detections"] if isinstance(d, dict) and d.get("prompt") == category) for category in categories} if manifest else {}
        filterable = bool(manifest is not None and inside_file(folder, manifest.get("saved_original")) and all(isinstance(d, dict) and isinstance(d.get("prompt"), str) and inside_file(folder, d.get("raw_mask")) for d in manifest["detections"]))
        results.append({"folder": folder.name, "captured_at": captured_at,
                        "mask_categories": categories, "category_counts": counts,
                        "mask_filterable": filterable,
                        "change_log": change_log,
                        "original": f"/runs/{folder.name}/{original}?privacy={IMAGE_PRIVACY_VERSION}" if original else None,
                        "overlay": f"/runs/{folder.name}/{overlay}?privacy={IMAGE_PRIVACY_VERSION}" if overlay else None})
    results.sort(key=lambda run: (run["captured_at"] or "", run["folder"]), reverse=True)
    # A selected day includes every saved frame, even when manual captures
    # take it beyond the 46 scheduled pictures. The default remains bounded.
    return {"runs": results if day is not None else results[:limit],
            "day": day, "timezone": zone_name}


@app.get("/api/object-monitor")
def get_object_monitor(limit: int = Query(50, ge=1, le=200),
                       before: int | None = Query(None, ge=1)):
    """Return the newest page before a stable line cursor, plus inventory state.

    A bounded deque avoids loading the entire event log into memory. Malformed
    lines, including a partially written final line, do not erase valid history.
    """
    state_path = MONITOR_DIR / "object_state.json"
    events_path = MONITOR_DIR / "events.jsonl"
    state, warnings = {}, []
    updated_at = None
    try:
        value = json.loads(state_path.read_text(encoding="utf-8"))
        if isinstance(value, dict) and isinstance(value.get("objects", {}), dict):
            state = value
            updated_at = datetime.fromtimestamp(state_path.stat().st_mtime, timezone.utc).isoformat()
        else:
            warnings.append("The saved inventory is not readable; history can still be explored.")
    except FileNotFoundError:
        pass
    except (OSError, ValueError, UnicodeError):
        warnings.append("The saved inventory is unavailable; history can still be explored.")

    page = deque(maxlen=limit)
    total, eligible, history_id = 0, 0, None
    try:
        with events_path.open(encoding="utf-8", errors="replace") as source:
            history_id = str(os.fstat(source.fileno()).st_ino)
            for sequence, line in enumerate(source, 1):
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(event, dict) or not isinstance(event.get("event"), str) or event["event"] not in EVENT_TYPES:
                    continue
                total += 1
                if before is None or sequence < before:
                    eligible += 1
                    page.append({**event, "sequence": sequence})
    except FileNotFoundError:
        pass
    except OSError:
        warnings.append("Monitoring history is temporarily unavailable. Try refreshing.")
    events = list(page)
    return {"last_run_id": state.get("last_run_id"), "person_count": state.get("person_count"),
            "objects": state.get("objects", {}), "state_available": bool(state),
            "updated_at": updated_at, "recent_events": events, "total_events": total,
            "has_more": eligible > len(events),
            "next_before": events[0]["sequence"] if events and eligible > len(events) else None,
            "history_id": history_id, "warnings": warnings}


def room_timezone():
    try:
        name = os.environ.get("TZ") or Path('/etc/timezone').read_text().strip()
        return ZoneInfo(name), name
    except (OSError, ValueError, KeyError):
        return timezone.utc, 'UTC'


def saved_json(path):
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, UnicodeError):
        return {}


def person_count(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


@app.get('/api/occupancy')
def get_occupancy(day: str | None = Query(None, max_length=10)):
    """Daily observed counts, without carrying old values across unobserved hours."""
    zone, zone_name = room_timezone()
    today = datetime.now(zone).date()
    try:
        selected_day = date.fromisoformat(day) if day else today
        if day and selected_day.isoformat() != day:
            raise ValueError('Use YYYY-MM-DD')
    except ValueError as error:
        raise HTTPException(400, 'Choose a valid date in YYYY-MM-DD format') from error
    start = datetime.combine(selected_day, time.min, zone)
    end = datetime.combine(selected_day + timedelta(days=1), time.min, zone)
    observations, represented_events, warnings = {}, set(), []

    def add(key, stamp, count, source, run_id=None):
        count = person_count(count)
        if count is None or not isinstance(stamp, str):
            return
        try:
            observed = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
            if observed.tzinfo is None:
                observed = observed.replace(tzinfo=zone)
            observed = observed.astimezone(zone)
        except ValueError:
            return
        observations[key] = {'time': observed.isoformat(), 'count': count,
                             'hour': observed.hour + observed.minute / 60 + observed.second / 3600,
                             'source': source, 'run_id': run_id}

    state = saved_json(MONITOR_DIR / 'object_state.json')
    try:
        folders = list(RUNS_DIR.iterdir()) if RUNS_DIR.is_dir() else []
        for folder in folders:
            if not folder.is_dir():
                continue
            manifest = saved_json(folder / 'manifest.json')
            report = saved_json(folder / 'changes.json')
            changes = report.get('changes', [])
            changes = changes if isinstance(changes, list) else []
            count = person_count(report.get('person_count'))
            last_change = None
            for event in changes:
                if not isinstance(event, dict) or event.get('event') != 'person_count_changed':
                    continue
                data = event.get('data', {})
                value = person_count(data.get('current')) if isinstance(data, dict) else None
                if value is not None:
                    last_change = event
                    if isinstance(event.get('time'), str):
                        represented_events.add((event['time'], value))
            if count is None and last_change:
                count = person_count(last_change['data'].get('current'))
            if count is None and state.get('last_run_id') == folder.name:
                count = person_count(state.get('person_count'))
            stamp = report.get('observed_at') or manifest.get('captured_at')
            if not stamp:
                try:
                    stamp = datetime.strptime(folder.name[:19], '%Y-%m-%d_%H-%M-%S').replace(tzinfo=zone).isoformat()
                except ValueError:
                    stamp = last_change.get('time') if last_change else None
            add('capture:' + folder.name, stamp, count, 'capture', folder.name)
    except OSError:
        warnings.append('Some saved captures are temporarily unavailable.')

    try:
        with (MONITOR_DIR / 'events.jsonl').open(encoding='utf-8', errors='replace') as source:
            for sequence, line in enumerate(source, 1):
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(event, dict) or event.get('event') != 'person_count_changed':
                    continue
                data = event.get('data', {})
                count = person_count(data.get('current')) if isinstance(data, dict) else None
                if isinstance(event.get('time'), str) and (event['time'], count) not in represented_events:
                    add('event:' + str(sequence), event.get('time'), count, 'monitor event')
    except FileNotFoundError:
        pass
    except OSError:
        warnings.append('Some saved count events are temporarily unavailable.')

    ordered = sorted(observations.values(), key=lambda point: datetime.fromisoformat(point['time']).timestamp())
    points = [point for point in ordered if start <= datetime.fromisoformat(point['time']) < end]
    return {'day': selected_day.isoformat(), 'today': today.isoformat(), 'timezone': zone_name,
            'start': start.isoformat(), 'end': end.isoformat(), 'observations': points,
            'peak': max((point['count'] for point in points), default=None),
            'latest_observation': ordered[-1] if ordered else None, 'warnings': warnings}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True,
                app_dir=str(BASE_DIR / "backend"), reload_dirs=[str(BASE_DIR)])


# Read-only scheduler telemetry; cache process queries across browser polls.
_runtime_cache = (0, {})


def capture_runtime():
    global _runtime_cache
    tick = clock_time.monotonic()
    if tick - _runtime_cache[0] < 10:
        return _runtime_cache[1]
    units = {}
    try:
        result = subprocess.run([
            "systemctl", "--user", "show", "jarvis-capture.timer",
            "jarvis-capture.service", "jarvis-sam3.service",
            "--property=Id,ActiveState,Result,NextElapseUSecRealtime,TimersCalendar"
        ], capture_output=True, text=True, timeout=3, check=True)
        for block in result.stdout.strip().split("\n\n"):
            unit = {"calendar": []}
            for line in block.splitlines():
                key, _, value = line.partition("=")
                if key == "TimersCalendar":
                    match = re.search(r"OnCalendar=(.*?) ; next_elapse=", value)
                    if match:
                        unit["calendar"].append(match.group(1).strip())
                else:
                    unit[key] = value
            if unit.get("Id"):
                units[unit["Id"]] = unit
        link = Path.home() / ".config/systemd/user/timers.target.wants/jarvis-capture.timer"
        if link.is_symlink():
            units["enabled_since"] = datetime.fromtimestamp(link.lstat().st_mtime, timezone.utc).isoformat()
    except (OSError, subprocess.SubprocessError):
        units = {}
    _runtime_cache = (tick, units)
    return units


def capture_slots(day, expressions):
    """Expand the supported daily timer rules; never guess an unknown schedule."""
    slots, zone_name = set(), None
    for expression in expressions:
        match = re.fullmatch(r"(?:(Mon\.\.Fri) )?\*-\*-\* (\d{2}(?:\.\.\d{2})?):([\d,/]+):00 ([A-Za-z_]+/[A-Za-z_/]+)", expression)
        if not match:
            raise ValueError("Unsupported capture timer rule")
        weekdays, hours, minutes, name = match.groups()
        if zone_name and zone_name != name:
            raise ValueError("Capture timer timezones disagree")
        zone_name = name
        zone = ZoneInfo(name)
        if ".." in hours:
            first, last = map(int, hours.split(".."))
            hours = range(first, last + 1)
        else:
            hours = [int(hours)]
        if "/" in minutes:
            first, step = map(int, minutes.split("/"))
            if not 1 <= step <= 60:
                raise ValueError("Invalid timer interval")
            minutes = range(first, 60, step)
        else:
            minutes = [int(value) for value in minutes.split(",")]
        if weekdays and day.weekday() >= 5:
            continue
        for hour in hours:
            for minute in minutes:
                slots.add(datetime.combine(day, time(hour, minute), zone))
    if zone_name is None:
        raise ValueError("No capture schedule")
    return sorted(slots), zone_name


def status_stamp(value, zone):
    if not isinstance(value, str):
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return stamp.replace(tzinfo=zone) if stamp.tzinfo is None else stamp.astimezone(zone)
    except ValueError:
        match = re.search(r"(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})", value)
        return datetime.fromisoformat("T".join(match.groups())).replace(tzinfo=zone) if match else None


def build_capture_status(now, runtime, footage_dir, runs_dir):
    timer = runtime.get("jarvis-capture.timer", {})
    zone, zone_name = room_timezone()
    try:
        expressions = timer.get("calendar", [])
        if expressions:
            zone = ZoneInfo(expressions[0].split()[-1])
        now = now.astimezone(zone)
        slots, zone_name = capture_slots(now.date(), expressions)
    except (ValueError, KeyError):
        return {"state": "unavailable", "message": "The capture schedule could not be verified.",
                "checked_at": now.isoformat(), "timezone": zone_name}
    photos = []
    try:
        for path in footage_dir.iterdir():
            if path.suffix.lower() not in (".jpg", ".jpeg") or not path.is_file() or not path.stat().st_size:
                continue
            stamp = None
            for pattern in ("%Y-%m-%d_%H-%M-%S_%f", "%Y-%m-%d_%H-%M-%S", "%Y-%m-%d-%H_%M_%S"):
                try:
                    stamp = datetime.strptime(path.stem, pattern).replace(tzinfo=zone)
                    break
                except ValueError:
                    pass
            if stamp is not None and stamp <= now:
                report = saved_json(runs_dir / path.stem / "changes.json")
                count = person_count(report.get("person_count"))
                photos.append({"time": stamp, "count": count, "complete": count is not None})
    except OSError:
        return {"state": "unavailable", "message": "The saved picture archive could not be checked.",
                "checked_at": now.isoformat(), "timezone": zone_name}
    photos.sort(key=lambda photo: photo["time"])
    today = [photo for photo in photos if photo["time"].date() == now.date()]
    # Match one picture during the minute after each scheduled trigger. Extra
    # manual pictures do not inflate scheduled-slot progress.
    matched = [(slot, next((photo for photo in today if slot <= photo["time"] < slot + timedelta(minutes=1)), None)) for slot in slots]
    enabled_since = status_stamp(runtime.get("enabled_since"), zone)
    due = [(slot, photo) for slot, photo in matched if slot + timedelta(minutes=1) <= now and (enabled_since is None or slot >= enabled_since)]
    missed = sum(photo is None for _, photo in due)
    latest = photos[-1] if photos else None
    analysis = "none"
    if latest:
        analysis = "complete" if latest["complete"] else "delayed" if now - latest["time"] > timedelta(minutes=15) else "processing"
    delayed_slots = any(photo and not photo["complete"] and now - photo["time"] > timedelta(minutes=15) for _, photo in matched)
    within_hours = bool(slots) and slots[0] <= now < slots[-1] + timedelta(minutes=1)
    watcher = runtime.get("jarvis-sam3.service", {}).get("ActiveState")
    capture = runtime.get("jarvis-capture.service", {})
    state, message = "waiting", "Waiting for the next scheduled picture."
    if timer.get("ActiveState") != "active":
        state, message = "paused", "Automatic capture is paused."
    elif not slots:
        state, message = "outside_hours", "Weekend photography is disabled. Capture resumes Monday."
    elif watcher != "active":
        state, message = "problem", "Picture analysis is not running."
    elif analysis == "delayed" or delayed_slots:
        state, message = "problem", "A saved picture has waited over 15 minutes for analysis."
    elif capture.get("ActiveState") == "activating":
        state, message = "capturing", "Taking the scheduled picture."
    elif within_hours and (missed or capture.get("Result", "success") != "success"):
        state, message = "problem", "A scheduled picture is missing or the last capture failed."
    elif analysis == "processing":
        state, message = "processing", "Picture saved; waiting for its people-count analysis."
    elif not within_hours:
        state, message = "outside_hours", "Outside scheduled capture hours."
    next_stamp = status_stamp(timer.get("NextElapseUSecRealtime"), zone) if timer.get("ActiveState") == "active" else None
    return {"state": state, "message": message, "checked_at": now.isoformat(),
            "timezone": zone_name, "window_start": slots[0].isoformat() if slots else None, "window_end": slots[-1].isoformat() if slots else None,
            "schedule_days": "Monday-Friday" if all(e.startswith("Mon..Fri ") for e in expressions) else "Every day",
            "next_capture": next_stamp.isoformat() if next_stamp else None,
            "last_capture": latest["time"].isoformat() if latest else None,
            "analysis": analysis, "people_count": latest["count"] if latest else None,
            "planned_today": len(slots), "captured_today": sum(photo is not None for _, photo in matched),
            "processed_today": sum(photo is not None and photo["complete"] for _, photo in matched),
            "other_pictures_today": len(today) - sum(photo is not None for _, photo in matched),
            "missed_today": missed}


@app.get("/api/capture-status")
def get_capture_status():
    return build_capture_status(datetime.now(timezone.utc), capture_runtime(), JARVIS_DIR / "Footage", RUNS_DIR)


def inspection_capture(run_id):
    folder = (RUNS_DIR / run_id).resolve()
    if folder.parent != RUNS_DIR.resolve() or not folder.is_dir():
        raise HTTPException(404, "Capture not found")
    manifest = run_manifest(folder)
    if manifest is None:
        raise HTTPException(409, "Individual detections are unavailable for this older capture")
    original = inside_file(folder, manifest.get("saved_original"))
    if original is None:
        raise HTTPException(409, "The saved original is unavailable")
    try:
        with Image.open(original) as image:
            size = image.size
    except (OSError, ValueError) as error:
        raise HTTPException(409, "The saved original could not be read") from error
    detections = []
    for ordinal, value in enumerate(manifest['detections']):
        if not isinstance(value, dict) or not isinstance(value.get('prompt'), str):
            continue
        box = value.get('box')
        if not isinstance(box, list) or len(box) != 4 or not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in box):
            continue
        box = [max(0, min(float(v), size[i % 2])) for i, v in enumerate(box)]
        if box[2] <= box[0] or box[3] <= box[1]:
            continue
        score = value.get('score')
        score = score if isinstance(score, (int, float)) and not isinstance(score, bool) and math.isfinite(score) and 0 <= score <= 1 else None
        index = value.get('index', 0)
        index = index if isinstance(index, int) and not isinstance(index, bool) and index >= 0 else ordinal
        detections.append({'id': ordinal, 'category': value['prompt'], 'number': index + 1,
                           'score': score, 'box': box,
                           'mask_available': inside_file(folder, value.get('raw_mask')) is not None})
    return folder, manifest, original, size, detections


@app.get('/api/detections/{run_id}')
def get_detections(run_id: str):
    folder, manifest, original, size, detections = inspection_capture(run_id)
    return {'run_id': run_id, 'width': size[0], 'height': size[1], 'detections': detections}


def inspection_mask(folder, value, size):
    path = inside_file(folder, value.get('raw_mask'))
    if path is None:
        raise HTTPException(409, 'The selected individual mask is unavailable')
    try:
        with Image.open(path) as image:
            mask = image.convert('L').point(lambda value: 255 if value else 0)
        if mask.size != size:
            raise HTTPException(409, 'The saved mask dimensions do not match the picture')
        return mask
    except (OSError, ValueError) as error:
        raise HTTPException(409, 'The saved mask could not be read') from error


@app.get('/api/detections/{run_id}/hit')
def hit_detection(run_id: str, x: int, y: int, categories: list[str] | None = Query(None)):
    folder, manifest, original, size, detections = inspection_capture(run_id)
    if not (0 <= x < size[0] and 0 <= y < size[1]):
        raise HTTPException(400, 'Choose a point inside the picture')
    requested = set(manifest_categories(manifest) if categories is None else categories)
    if not requested.issubset(set(manifest_categories(manifest)) | set(sam3_settings()[0]) | {''}):
        raise HTTPException(400, 'Unknown mask category')
    hits = []
    for detection in detections:
        if detection['category'] not in requested or not detection['mask_available']:
            continue
        mask = inspection_mask(folder, manifest['detections'][detection['id']], size)
        if mask.getpixel((x, y)):
            hits.append(detection)
    hits.sort(key=lambda detection: ((detection['box'][2] - detection['box'][0]) * (detection['box'][3] - detection['box'][1]), -(detection['score'] or 0), detection['id']))
    return {'selected_id': hits[0]['id'] if hits else None, 'hit_ids': [item['id'] for item in hits]}


@app.get('/api/detections/{run_id}/{detection_id}/highlight')
def highlight_detection(run_id: str, detection_id: int):
    folder, manifest, original, size, detections = inspection_capture(run_id)
    detection = next((item for item in detections if item['id'] == detection_id), None)
    if detection is None:
        raise HTTPException(404, 'Detection not found in this picture')
    mask = inspection_mask(folder, manifest['detections'][detection_id], size)
    try:
        with Image.open(original) as image:
            original_image = image.convert('RGB')
        dimmed = Image.blend(original_image, Image.new('RGB', size, (0, 0, 0)), .63)
        tinted = Image.blend(original_image, Image.new('RGB', size, (199, 180, 139)), .30)
        canvas = Image.composite(tinted, dimmed, mask)
        canvas = draw_mask_contours(canvas, [(mask, (235, 216, 174))], width=2)
        draw = ImageDraw.Draw(canvas)
        label = f"{detection['category']} {detection['number']}"
        box = mask.getbbox()
        if box is not None:
            draw.text((box[0] + 3, max(2, box[1] - 14)), label, fill=(255, 239, 206), stroke_width=2, stroke_fill=(0, 0, 0))
        return privacy_image_response(canvas, original)
    except (OSError, ValueError) as error:
        raise HTTPException(409, 'The selected mask could not be highlighted') from error
