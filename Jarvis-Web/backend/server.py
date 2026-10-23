"""Jarvis's read-only capture archive and paged object-monitoring history."""
from collections import deque
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI()
# Preserve the existing dashboard access configuration.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])
BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"
JARVIS_DIR = BASE_DIR.parent
RUNS_DIR = JARVIS_DIR / "Masks" / "runs"
MONITOR_DIR = JARVIS_DIR / "object_monitor" / "object_monitor"
EVENT_TYPES = {"new_object", "object_missing", "object_returned", "person_count_changed"}
app.mount("/runs", StaticFiles(directory=str(RUNS_DIR), check_dir=False), name="runs")
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


@app.get("/")
def read_root():
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/api/latest")
def get_latest_runs():
    if not RUNS_DIR.is_dir():
        return {"runs": []}
    folders = sorted((p for p in RUNS_DIR.iterdir() if p.is_dir()),
                     key=lambda p: p.stat().st_mtime, reverse=True)
    results = []
    for folder in folders[:10]:
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
        results.append({"folder": folder.name, "captured_at": captured_at,
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True,
                app_dir=str(BASE_DIR / "backend"), reload_dirs=[str(BASE_DIR)])
