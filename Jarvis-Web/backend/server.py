import json
import os
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")
JARVIS_DIR = os.path.dirname(BASE_DIR)

# Point directly to the runs directory
RUNS_DIR = os.path.join(JARVIS_DIR, "Masks", "runs")
os.makedirs(RUNS_DIR, exist_ok=True)

# Mount the runs folder under /runs
app.mount("/runs", StaticFiles(directory=RUNS_DIR), name="runs")

# Mount frontend static assets
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

@app.get("/")
def read_root():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))

@app.get("/api/latest")
def get_latest_runs():
    if not os.path.exists(RUNS_DIR):
        return {"runs": []}

    # Retrieve timestamp subdirectories
    subdirs = [
        d for d in os.listdir(RUNS_DIR)
        if os.path.isdir(os.path.join(RUNS_DIR, d))
    ]

    # Sort folders by modification time (newest first)
    subdirs.sort(
        key=lambda d: os.path.getmtime(os.path.join(RUNS_DIR, d)),
        reverse=True
    )

    results = []
    for d in subdirs[:10]:
        folder_path = os.path.join(RUNS_DIR, d)
        files_in_dir = os.listdir(folder_path)

        # Locate original image (supports .jpg, .jpeg, .png)
        orig_file = next((f for f in files_in_dir if f.lower().startswith("original.")), None)
        # Locate combined overlay (supports .png, .jpg, .jpeg)
        overlay_file = next((f for f in files_in_dir if f.lower().startswith("combined_overlay.")), None)

        if orig_file or overlay_file:
            change_log = None
            change_log_path = os.path.join(folder_path, "changes.json")

            if os.path.isfile(change_log_path):
                try:
                    with open(change_log_path, "r", encoding="utf-8") as f:
                        change_log = json.load(f)
                except (OSError, json.JSONDecodeError):
                    change_log = None

            results.append({
                "folder": d,
                "change_log": change_log,
                "original": f"/runs/{d}/{orig_file}" if orig_file else None,
                "overlay": f"/runs/{d}/{overlay_file}" if overlay_file else None
            })

    return {"runs": results}

# ============================================================
# JARVIS OBJECT MONITOR API
# ============================================================

MONITOR_DIR = os.path.join(JARVIS_DIR, "object_monitor", "object_monitor")

@app.get("/api/object-monitor")
def get_object_monitor():

    state_path = os.path.join(
        MONITOR_DIR, "object_state.json"
    )

    events_path = os.path.join(
        MONITOR_DIR, "events.jsonl"
    )

    state = {}
    events = []

    if os.path.exists(state_path):
        with open(state_path, "r") as f:
            state = json.load(f)

    if os.path.exists(events_path):
        with open(events_path, "r") as f:
            for line in f:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    return {
        "last_run_id": state.get("last_run_id"),
        "person_count": state.get("person_count"),
        "objects": state.get("objects", {}),
        "recent_events": events[-20:]
    }
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True,
                app_dir=os.path.dirname(os.path.abspath(__file__)),
                reload_dirs=[BASE_DIR])
