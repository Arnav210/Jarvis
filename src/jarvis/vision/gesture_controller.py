
# Allow the dedicated runtime interpreters to execute this source file directly.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))

import os
os.environ['GLOG_minloglevel'] = '2'
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'

import time
import subprocess
from jarvis.vision import config
from jarvis.vision.mediapipe_tracker import HandTracker
from jarvis.vision.gesture_analyzer import GestureAnalyzer

class GestureController:
    def __init__(self):
        self.tracker = HandTracker()
        self.analyzer = GestureAnalyzer()

    def handle_action(self, action):
        if action is None or action == "STATE_PAUSED":
            return None

        msg = None
        if action == "ACTION_VOLUME_UP":
            subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", "+15%"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            msg = "[ACTION] Volume Up (+15%)"

        elif action == "ACTION_VOLUME_DOWN":
            subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", "-15%"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            msg = "[ACTION] Volume Down (-15%)"

        elif action == "ACTION_MUTE":
            subprocess.run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "1"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            msg = "[ACTION] System Muted"

        elif action == "ACTION_UNMUTE":
            subprocess.run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "0"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            msg = "[ACTION] System Unmuted"

        elif action == "ACTION_NEXT_TRACK":
            subprocess.run(["playerctl", "next"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            msg = "[ACTION] Track: Next"

        elif action == "ACTION_PREV_TRACK":
            subprocess.run(["playerctl", "previous"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            msg = "[ACTION] Track: Previous"

        return msg

    def run(self):
        print(f"Starting Gesture Controller on Camera Index {config.CAMERA_INDEX}...")
        self.tracker.start_camera(config.CAMERA_INDEX)

        try:
            while True:
                landmarks, _, hand_side = self.tracker.get_landmarks()
                action, status_str = self.analyzer.process_frame(landmarks, hand_side)

                action_msg = self.handle_action(action)
                if action_msg:
                    # Print action on its own new line above the active tracking line
                    print(f"\n{action_msg}")

                print(f"{status_str:<95}\r", end="", flush=True)
                time.sleep(0.03)

        except KeyboardInterrupt:
            print("\nStopping Gesture Controller...")
        finally:
            self.tracker.stop_camera()

if __name__ == "__main__":
    controller = GestureController()
    controller.run()
