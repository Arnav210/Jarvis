
# Allow the dedicated runtime interpreters to execute this source file directly.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))

import time
import numpy as np
from collections import deque
from jarvis.vision import config

class GestureAnalyzer:
    def __init__(self):
        self.prev_x = None
        self.prev_y = None
        self.orientation_history = deque(maxlen=5)

        # Persistence Caching
        self.missing_frames_count = 0
        self.last_valid_landmarks = None
        self.last_valid_hand_side = None

        # State Tracking
        self.last_volume_time = 0.0
        self.last_track_time = 0.0
        self.last_mute_time = 0.0
        self.prev_finger_state = None
        self.is_muted = False

    def calculate_triangle_area(self, p1, p2, p3):
        return 0.5 * abs(p1.x * (p2.y - p3.y) + p2.x * (p3.y - p1.y) + p3.x * (p1.y - p2.y))

    def get_raw_orientation(self, landmarks, hand_side, finger_state):
        # Do not calculate PALM_DOWN/UP for a curled fist to prevent clutch override
        if finger_state == "FIST_CURLED":
            return "FIST_POSE"

        thumb_mcp = landmarks[2]
        middle_tip = landmarks[12]
        pinky_pip = landmarks[18]
        index_mcp = landmarks[5]
        thumb_tip = landmarks[4]

        area = self.calculate_triangle_area(thumb_mcp, middle_tip, pinky_pip)
        base_width = np.sqrt((thumb_mcp.x - pinky_pip.x) ** 2 + (thumb_mcp.y - pinky_pip.y) ** 2) + 1e-6
        area_ratio = area / (base_width ** 2)

        if area_ratio < 0.22:
            thumb_is_higher = thumb_tip.y < index_mcp.y
            return "PALM_UP" if thumb_is_higher else "PALM_DOWN"

        w = np.array([landmarks[0].x, landmarks[0].y, landmarks[0].z])
        i = np.array([index_mcp.x, index_mcp.y, index_mcp.z])
        p = np.array([landmarks[17].x, landmarks[17].y, landmarks[17].z])

        normal = np.cross(i - w, p - w)
        z_norm = -normal[2] if hand_side == "Right" else normal[2]

        return "PALM_FACING_CAMERA" if z_norm > 0.0 else "PALM_FACING_AWAY"

    def get_smoothed_orientation(self, raw_orientation):
        self.orientation_history.append(raw_orientation)
        return max(set(self.orientation_history), key=self.orientation_history.count)

    def get_finger_state(self, landmarks):
        index_open = landmarks[8].y < landmarks[6].y
        middle_open = landmarks[12].y < landmarks[10].y
        ring_open = landmarks[16].y < landmarks[14].y
        pinky_open = landmarks[20].y < landmarks[18].y

        if index_open and middle_open and ring_open and pinky_open:
            return "HAND_OPEN"
        elif not index_open and not middle_open and not ring_open and not pinky_open:
            return "FIST_CURLED"
        else:
            return "PARTIAL_POSE"

    def get_motions(self, current_x, current_y):
        v_motion = "STATIONARY"
        h_motion = "STATIONARY"

        if self.prev_y is not None:
            delta_y = current_y - self.prev_y
            if delta_y < -0.018:
                v_motion = "MOVING_UP"
            elif delta_y > 0.018:
                v_motion = "MOVING_DOWN"

        if self.prev_x is not None:
            delta_x = current_x - self.prev_x
            if delta_x > 0.020:
                h_motion = "MOVING_RIGHT"
            elif delta_x < -0.020:
                h_motion = "MOVING_LEFT"

        self.prev_x = current_x
        self.prev_y = current_y

        return v_motion, h_motion

    def evaluate_gestures(self, orientation, finger_state, v_motion, h_motion):
        now = time.time()
        action = None

        # 1. MUTE / UNMUTE (Open -> Fist = Mute | Fist -> Open = Unmute)
        if self.prev_finger_state is not None and (now - self.last_mute_time > 0.6):
            if self.prev_finger_state == "HAND_OPEN" and finger_state == "FIST_CURLED":
                if not self.is_muted:
                    action = "ACTION_MUTE"
                    self.is_muted = True
                    self.last_mute_time = now
            elif self.prev_finger_state == "FIST_CURLED" and finger_state == "HAND_OPEN":
                if self.is_muted:
                    action = "ACTION_UNMUTE"
                    self.is_muted = False
                    self.last_mute_time = now

        self.prev_finger_state = finger_state
        if action:
            return action

        # 2. MEDIA TRACK CONTROL (Swipe Left/Right while palm facing away/camera)
        if finger_state == "HAND_OPEN" and (now - self.last_track_time > 1.0):
            if orientation in ["PALM_FACING_AWAY", "PALM_UP"] and h_motion == "MOVING_RIGHT":
                self.last_track_time = now
                return "ACTION_NEXT_TRACK"
            elif orientation in ["PALM_FACING_CAMERA", "PALM_UP"] and h_motion == "MOVING_LEFT":
                self.last_track_time = now
                return "ACTION_PREV_TRACK"

        # 3. VOLUME CONTROL (+/- 15%)
        if orientation == "PALM_FACING_CAMERA" and finger_state == "HAND_OPEN":
            if now - self.last_volume_time > config.VOLUME_COOLDOWN:
                if v_motion == "MOVING_UP":
                    self.last_volume_time = now
                    return "ACTION_VOLUME_UP"
                elif v_motion == "MOVING_DOWN":
                    self.last_volume_time = now
                    return "ACTION_VOLUME_DOWN"

        return None

    def process_frame(self, raw_landmarks, raw_hand_side):
        if raw_landmarks:
            self.last_valid_landmarks = raw_landmarks
            self.last_valid_hand_side = raw_hand_side
            self.missing_frames_count = 0
        else:
            if self.last_valid_landmarks and self.missing_frames_count < config.MAX_MISSING_FRAMES:
                raw_landmarks = self.last_valid_landmarks
                raw_hand_side = self.last_valid_hand_side
                self.missing_frames_count += 1
            else:
                self.last_valid_landmarks = None
                self.last_valid_hand_side = None
                self.prev_x = None
                self.prev_y = None
                self.prev_finger_state = None
                self.orientation_history.clear()
                return None, f"{'No hand detected...':<95}"

        curr_x = raw_landmarks[9].x
        curr_y = raw_landmarks[9].y

        finger_state = self.get_finger_state(raw_landmarks)
        raw_orient = self.get_raw_orientation(raw_landmarks, raw_hand_side, finger_state)
        orientation = self.get_smoothed_orientation(raw_orient)
        v_motion, h_motion = self.get_motions(curr_x, curr_y)

        # PALM_DOWN engages the Clutch
        if orientation == "PALM_DOWN":
            action = "STATE_PAUSED"
            clutch_tag = " [CLUTCH ENGAGED]"
        else:
            action = self.evaluate_gestures(orientation, finger_state, v_motion, h_motion)
            clutch_tag = ""

        held_tag = f" [HELD {self.missing_frames_count}f]" if self.missing_frames_count > 0 else ""
        mute_tag = " [MUTED]" if self.is_muted else ""
        state_summary = f"Hand: {raw_hand_side} | Orient: {orientation} | Pose: {finger_state} | V:{v_motion} H:{h_motion}{held_tag}{clutch_tag}{mute_tag}"

        return action, state_summary
