#!/bin/bash

FOOTAGE="$HOME/Jarvis/Footage"

PYTHON_SCRIPT="$HOME/Jarvis/src/jarvis/vision/sam3_process.py"

MONITOR_SCRIPT="$HOME/Jarvis/src/jarvis/vision/object_monitor.py"

PYTHON_BIN="$HOME/miniconda3/envs/sam3/bin/python"


echo "Watching $FOOTAGE for new images..."


inotifywait -m -e close_write --format '%w%f' "$FOOTAGE" |
while read IMAGE
do
    # Only process JPG/JPEG files
    if [[ "$IMAGE" == *.jpg || "$IMAGE" == *.jpeg ]]; then

        echo
        echo "=========================================="
        echo "New image detected: $IMAGE"
        echo "=========================================="

        # First run SAM3 object detection
        if "$PYTHON_BIN" -u "$PYTHON_SCRIPT" "$IMAGE"; then

            echo
            echo "Running object inventory monitor..."

            # Then compare objects with previous scene
            "$PYTHON_BIN" -u "$MONITOR_SCRIPT"

        else

            echo "ERROR: SAM3 processing failed."
            echo "Object monitor skipped."

        fi
    fi
done
