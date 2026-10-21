
# Allow the dedicated runtime interpreters to execute this source file directly.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))

# System & Camera Configuration
CAMERA_INDEX = 0
FRAME_WIDTH = 640
FRAME_HEIGHT = 480

# Tracking Thresholds
MIN_DETECTION_CONFIDENCE = 0.5
MIN_TRACKING_CONFIDENCE = 0.5
MAX_MISSING_FRAMES = 3

# Gesture Cooldown Timers (seconds)
VOLUME_COOLDOWN = 0.12
UNDO_COOLDOWN = 1.5
FIST_HOLD_DURATION = 0.4
