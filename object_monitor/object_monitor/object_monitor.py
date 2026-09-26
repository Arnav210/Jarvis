
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

MONITOR_DIR = Path(__file__).parent

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

def log_event(event_type, message, data=None):

    event = {
        "time": datetime.now(timezone.utc).isoformat(),
        "event": event_type,
        "message": message,
        "data": data or {},
    }

    with EVENT_LOG.open("a", encoding="utf-8") as file:
        file.write(json.dumps(event) + "\n")


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
# FILTER DETECTIONS
# ============================================================

detections = [

    detection

    for detection in raw_detections

    if detection.get(
        "score",
        0
    ) >= MIN_SCORE
]


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
