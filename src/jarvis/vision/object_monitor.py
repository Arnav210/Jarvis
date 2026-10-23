
# Allow the dedicated runtime interpreters to execute this source file directly.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))


import json
from datetime import datetime, timezone
from pathlib import Path


# ============================================================
# PATHS
# ============================================================

JARVIS = Path.home() / "Jarvis"

LATEST_MANIFEST = (
    JARVIS
    / "Masks"
    / "latest"
    / "manifest.json"
)

MONITOR_DIR = JARVIS / "object_monitor" / "object_monitor"

STATE_FILE = MONITOR_DIR / "object_state.json"
EVENT_LOG = MONITOR_DIR / "events.jsonl"


# ============================================================
# SETTINGS
# ============================================================

MIN_SCORE = 0.50

# Number of consecutive processed images an object must be
# absent before it becomes officially MISSING.
MISSING_FRAMES_REQUIRED = 2

# How far outside the original bounding box an object may move
# and still count as being in its designated location.
ROI_MARGIN = 100

# Person is handled by COUNT rather than designated location.
PEOPLE_CLASS = "person"


# ============================================================
# HELPER FUNCTIONS
# ============================================================

RUN_EVENTS = []

def log_event(event_type, message, data=None):

    event = {
        "time": datetime.now(timezone.utc).isoformat(),
        "event": event_type,
        "message": message,
        "data": data or {},
    }

    with EVENT_LOG.open("a", encoding="utf-8") as file:
        file.write(json.dumps(event) + "\n")

    RUN_EVENTS.append(event)


def save_state(state):

    temp_file = STATE_FILE.with_suffix(".tmp")

    temp_file.write_text(
        json.dumps(state, indent=2) + "\n",
        encoding="utf-8",
    )

    temp_file.replace(STATE_FILE)


def center_of_box(box):

    x1, y1, x2, y2 = box

    return (
        (x1 + x2) / 2,
        (y1 + y2) / 2,
    )


def center_inside_roi(box, roi):

    cx, cy = center_of_box(box)

    rx1, ry1, rx2, ry2 = roi

    return (
        rx1 <= cx <= rx2
        and
        ry1 <= cy <= ry2
    )


def make_roi(box, image_width, image_height):

    x1, y1, x2, y2 = box

    return [
        max(0, x1 - ROI_MARGIN),
        max(0, y1 - ROI_MARGIN),
        min(image_width, x2 + ROI_MARGIN),
        min(image_height, y2 + ROI_MARGIN),
    ]


# ============================================================
# LOAD SAM3 RESULT
# ============================================================

if not LATEST_MANIFEST.exists():

    print(
        f"ERROR: SAM3 manifest not found:\n"
        f"{LATEST_MANIFEST}"
    )

    raise SystemExit(1)


manifest = json.loads(
    LATEST_MANIFEST.read_text(
        encoding="utf-8"
    )
)

run_id = manifest["run_id"]

image_width = manifest["image_size"]["width"]
image_height = manifest["image_size"]["height"]

raw_detections = manifest.get(
    "detections",
    []
)


# ============================================================
# FILTER + DEDUPLICATE DETECTIONS
# ============================================================

detections = [
    detection
    for detection in raw_detections
    if detection.get("score", 0) >= MIN_SCORE
]


def box_iou(box_a, box_b):
    ax1, ay1, ax2, ay2 = box_a
    bx1, by1, bx2, by2 = box_b

    intersection_x1 = max(ax1, bx1)
    intersection_y1 = max(ay1, by1)
    intersection_x2 = min(ax2, bx2)
    intersection_y2 = min(ay2, by2)

    intersection_width = max(0, intersection_x2 - intersection_x1)
    intersection_height = max(0, intersection_y2 - intersection_y1)

    intersection_area = intersection_width * intersection_height

    area_a = max(0, ax2 - ax1) * max(0, ay2 - ay1)
    area_b = max(0, bx2 - bx1) * max(0, by2 - by1)

    union_area = area_a + area_b - intersection_area

    if union_area == 0:
        return 0

    return intersection_area / union_area

def box_containment(box_a, box_b):
    ax1, ay1, ax2, ay2 = box_a
    bx1, by1, bx2, by2 = box_b

    intersection_x1 = max(ax1, bx1)
    intersection_y1 = max(ay1, by1)
    intersection_x2 = min(ax2, bx2)
    intersection_y2 = min(ay2, by2)

    intersection_width = max(0, intersection_x2 - intersection_x1)
    intersection_height = max(0, intersection_y2 - intersection_y1)

    intersection_area = intersection_width * intersection_height

    area_a = max(0, ax2 - ax1) * max(0, ay2 - ay1)
    area_b = max(0, bx2 - bx1) * max(0, by2 - by1)

    smaller_area = min(area_a, area_b)

    if smaller_area == 0:
        return 0

    return intersection_area / smaller_area

def deduplicate_detections(detections, iou_threshold=0.45):
    kept = []

    sorted_detections = sorted(
        detections,
        key=lambda d: d["score"],
        reverse=True
    )

    for detection in sorted_detections:
        duplicate = False

        for existing in kept:
            if detection["prompt"] != existing["prompt"]:
                continue

            overlap = box_iou(
                detection["box"],
                existing["box"]
            )

            containment = box_containment(
                detection["box"],
                existing["box"]
            )

            if overlap >= iou_threshold or containment >= 0.70:
                duplicate = True
                break

        if not duplicate:
            kept.append(detection)

    return kept


before_count = len(detections)

detections = deduplicate_detections(detections)

after_count = len(detections)

if before_count != after_count:
    print(
        f"Removed {before_count - after_count} duplicate detection(s)."
    )

# ============================================================
# LOAD PERSISTENT STATE
# ============================================================

if STATE_FILE.exists():

    try:

        state = json.loads(
            STATE_FILE.read_text(
                encoding="utf-8"
            )
        )

    except Exception:

        state = {}

else:

    state = {}


state.setdefault(
    "initialized",
    False
)

state.setdefault(
    "last_run_id",
    None
)

state.setdefault(
    "objects",
    {}
)

state.setdefault(
    "person_count",
    None
)


# ============================================================
# PREVENT PROCESSING SAME IMAGE TWICE
# ============================================================

previous_run_id = state["last_run_id"]

if state["last_run_id"] == run_id:

    print(
        "This SAM3 result has already "
        "been processed."
    )

    raise SystemExit(0)


# ============================================================
# PERSON MONITORING
# ============================================================

person_detections = [

    detection

    for detection in detections

    if detection["prompt"] == PEOPLE_CLASS
]


current_person_count = len(
    person_detections
)


if state["person_count"] is None:

    state["person_count"] = (
        current_person_count
    )

    print(
        f"People currently detected: "
        f"{current_person_count}"
    )

else:

    previous_person_count = (
        state["person_count"]
    )

    if (
        current_person_count
        != previous_person_count
    ):

        message = (
            f"PERSON COUNT CHANGED: "
            f"{previous_person_count} "
            f"-> "
            f"{current_person_count}"
        )

        print(
            f"\n⚠️ {message}"
        )

        log_event(
            "person_count_changed",
            message,
            {
                "previous":
                    previous_person_count,

                "current":
                    current_person_count,
            },
        )

    else:

        print(
            f"People detected: "
            f"{current_person_count}"
        )

    state["person_count"] = (
        current_person_count
    )


# ============================================================
# NON-PERSON OBJECT DETECTIONS
# ============================================================

object_detections = [

    detection

    for detection in detections

    if detection["prompt"]
    != PEOPLE_CLASS
]


# ============================================================
# FIRST RUN
#
# Everything visible becomes the initial inventory.
# ============================================================

if not state["initialized"]:

    counters = {}

    print(
        "\nCreating initial object inventory..."
    )

    for detection in object_detections:

        object_type = (
            detection["prompt"]
        )

        counters.setdefault(
            object_type,
            0
        )

        counters[object_type] += 1

        object_id = (
            f"{object_type}_"
            f"{counters[object_type]}"
        )

        box = detection["box"]

        roi = make_roi(
            box,
            image_width,
            image_height,
        )

        state["objects"][
            object_id
        ] = {

            "type":
                object_type,

            "roi":
                roi,

            "last_box":
                box,

            "last_score":
                detection["score"],

            "status":
                "present",

            "missing_count":
                0,

            "alerted":
                False,
        }

        print(
            f"REGISTERED: "
            f"{object_id} "
            f"score="
            f"{detection['score']:.2f}"
        )

    state["initialized"] = True

    log_event(
        "inventory_initialized",
        "Initial object inventory created.",
        {
            "object_count":
                len(state["objects"])
        },
    )


# ============================================================
# NORMAL MONITORING
# ============================================================

else:

    used_detection_indexes = set()

    # --------------------------------------------------------
    # CHECK EXISTING OBJECTS
    # --------------------------------------------------------

    for object_id, tracked in (
        state["objects"].items()
    ):

        object_type = (
            tracked["type"]
        )

        roi = tracked["roi"]

        matched_detection = None
        matched_index = None


        # Find an object of the same type
        # inside its designated region.
        for index, detection in enumerate(
            object_detections
        ):

            if (
                index
                in used_detection_indexes
            ):
                continue

            if (
                detection["prompt"]
                != object_type
            ):
                continue

            if center_inside_roi(
                detection["box"],
                roi,
            ):

                matched_detection = (
                    detection
                )

                matched_index = (
                    index
                )

                break


        # ----------------------------------------------------
        # OBJECT PRESENT
        # ----------------------------------------------------

        if matched_detection:

            used_detection_indexes.add(
                matched_index
            )

            was_missing = (
                tracked["status"]
                == "missing"
            )

            tracked["status"] = (
                "present"
            )

            tracked["missing_count"] = 0
            tracked["alerted"] = False

            tracked["last_box"] = (
                matched_detection["box"]
            )

            tracked["last_score"] = (
                matched_detection["score"]
            )


            if was_missing:

                message = (
                    f"{object_id} "
                    f"RETURNED TO "
                    f"DESIGNATED LOCATION"
                )

                print(
                    f"\n✅ {message}"
                )

                log_event(
                    "object_returned",
                    message,
                    {
                        "object":
                            object_id
                    },
                )

            else:

                print(
                    f"{object_id}: PRESENT"
                )


        # ----------------------------------------------------
        # OBJECT NOT DETECTED
        # ----------------------------------------------------

        else:

            tracked[
                "missing_count"
            ] += 1

            print(
                f"{object_id}: "
                f"not detected "
                f"("
                f"{tracked['missing_count']}"
                f"/"
                f"{MISSING_FRAMES_REQUIRED}"
                f")"
            )


            if (
                tracked[
                    "missing_count"
                ]
                >=
                MISSING_FRAMES_REQUIRED
            ):

                tracked["status"] = (
                    "missing"
                )


                if not tracked[
                    "alerted"
                ]:

                    message = (
                        f"{object_id.upper()} "
                        f"MISSING FROM "
                        f"DESIGNATED LOCATION"
                    )

                    print()
                    print(
                        "!!!!!!!!!!!!!!!!!!!!"
                        "!!!!!!!!!!!!!!!!!!!!"
                    )

                    print(
                        f"🚨 ALERT: "
                        f"{message}"
                    )

                    print(
                        "!!!!!!!!!!!!!!!!!!!!"
                        "!!!!!!!!!!!!!!!!!!!!"
                    )

                    print()

                    log_event(
                        "object_missing",
                        message,
                        {
                            "object":
                                object_id,

                            "type":
                                object_type,

                            "roi":
                                roi,
                        },
                    )

                    tracked[
                        "alerted"
                    ] = True


    # ========================================================
    # REGISTER NEW OBJECTS
    # ========================================================

    for index, detection in enumerate(
        object_detections
    ):

        if (
            index
            in used_detection_indexes
        ):
            continue


        object_type = (
            detection["prompt"]
        )


        existing_numbers = []

        for object_id, tracked in (
            state["objects"].items()
        ):

            if (
                tracked["type"]
                == object_type
            ):

                try:

                    existing_numbers.append(
                        int(
                            object_id.split(
                                "_"
                            )[-1]
                        )
                    )

                except ValueError:

                    pass


        next_number = (
            max(existing_numbers) + 1
            if existing_numbers
            else 1
        )


        object_id = (
            f"{object_type}_"
            f"{next_number}"
        )


        box = detection["box"]

        roi = make_roi(
            box,
            image_width,
            image_height,
        )


        state["objects"][
            object_id
        ] = {

            "type":
                object_type,

            "roi":
                roi,

            "last_box":
                box,

            "last_score":
                detection["score"],

            "status":
                "present",

            "missing_count":
                0,

            "alerted":
                False,
        }


        message = (
            f"NEW OBJECT DETECTED: "
            f"{object_id}"
        )


        print(
            f"\n🆕 {message}"
        )


        log_event(
            "new_object",
            message,
            {
                "object":
                    object_id,

                "type":
                    object_type,

                "box":
                    box,
            },
        )


# ============================================================
# SAVE STATE
# ============================================================

state["last_run_id"] = run_id

save_state(
    state
)



# ============================================================
# PER_CAPTURE_CHANGELOG_V1
# ============================================================

run_folder = JARVIS / "Masks" / "runs" / run_id

if run_folder.is_dir():
    changes_file = run_folder / "changes.json"

    change_types = {
        "new_object",
        "object_missing",
        "object_returned",
        "person_count_changed",
    }

    report = {
        "person_count": current_person_count,
        "observed_at": manifest.get("captured_at"),
        "current_capture": run_id,
        "previous_capture": previous_run_id,
        "changes": [
            event for event in RUN_EVENTS
            if event["event"] in change_types
        ],
    }

    temporary_file = run_folder / "changes.json.tmp"
    temporary_file.write_text(
        json.dumps(report, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_file.replace(changes_file)

    print(f"Capture change log saved: {changes_file}")
else:
    print(f"WARNING: Capture folder not found: {run_folder}")


# ============================================================
# SUMMARY
# ============================================================

print()
print(
    "============================="
)
print(
    "CURRENT SCENE STATUS"
)
print(
    "============================="
)

print(
    f"People: "
    f"{current_person_count}"
)

for object_id, tracked in sorted(
    state["objects"].items()
):

    print(
        f"{object_id}: "
        f"{tracked['status'].upper()}"
    )

print(
    "============================="
)
