"""Jarvis's read-only capture archive and paged object-monitoring history."""
from collections import deque
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
import ast
from io import BytesIO
import json
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageDraw

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
app.mount("/runs", StaticFiles(directory=str(RUNS_DIR), check_dir=False), name="runs")
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
        annotations = []
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
            tinted = Image.blend(canvas, Image.new("RGB", canvas.size, color), 0.45)
            canvas = Image.composite(tinted, canvas, mask)
            box = detection.get("box")
            if isinstance(box, list) and len(box) == 4 and all(isinstance(v, (int, float)) for v in box):
                score = detection.get("score")
                label = detection["prompt"] + (f" {score:.2f}" if isinstance(score, (int, float)) else "")
                annotations.append((box, label, color))
        draw = ImageDraw.Draw(canvas)
        for box, label, color in annotations:
            draw.rectangle(tuple(box), outline=color, width=3)
            draw.text((box[0] + 4, max(2, box[1] - 14)), label, fill=color, stroke_width=2, stroke_fill=(0, 0, 0))
        output = BytesIO()
        canvas.save(output, format="PNG")
        return Response(output.getvalue(), media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})
    except (OSError, ValueError) as error:
        raise HTTPException(409, "Saved mask data could not be rendered") from error


@app.get("/api/latest")
def get_latest_runs():
    if not RUNS_DIR.is_dir():
        return {"runs": []}
    folders = sorted((p for p in RUNS_DIR.iterdir() if p.is_dir()),
                     key=lambda p: p.stat().st_mtime, reverse=True)
    results = []
    for folder in folders[:46]:
        files = list(folder.iterdir())
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
        captured_at = None
        try:
            # Folder times are local to the camera host, not the visitor's browser.
            captured_at = datetime.strptime(folder.name[:19], "%Y-%m-%d_%H-%M-%S").astimezone().isoformat()
        except ValueError:
            pass
        manifest = run_manifest(folder)
        categories = manifest_categories(manifest) if manifest else []
        counts = {category: sum(1 for d in manifest["detections"] if isinstance(d, dict) and d.get("prompt") == category) for category in categories} if manifest else {}
        filterable = bool(manifest is not None and inside_file(folder, manifest.get("saved_original")) and all(isinstance(d, dict) and isinstance(d.get("prompt"), str) and inside_file(folder, d.get("raw_mask")) for d in manifest["detections"]))
        results.append({"folder": folder.name, "captured_at": captured_at,
                        "mask_categories": categories, "category_counts": counts,
                        "mask_filterable": filterable,
                        "change_log": change_log,
                        "original": f"/runs/{folder.name}/{original}" if original else None,
                        "overlay": f"/runs/{folder.name}/{overlay}" if overlay else None})
    return {"runs": results}


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
