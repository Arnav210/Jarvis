
# Allow the dedicated runtime interpreters to execute this source file directly.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))

import cv2
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

class HandTracker:
    def __init__(self, model_path="hand_landmarker.task"):
        base_options = python.BaseOptions(model_asset_path=model_path)
        options = vision.HandLandmarkerOptions(
            base_options=base_options,
            num_hands=1,
            min_hand_detection_confidence=0.5,  # Lowered threshold for better edge framing
            min_tracking_confidence=0.5          # Lowered threshold to prevent dropouts
        )
        self.detector = vision.HandLandmarker.create_from_options(options)
        self.cap = None

    def start_camera(self, camera_index=0):
        self.cap = cv2.VideoCapture(camera_index)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    def get_landmarks(self):
        if not self.cap or not self.cap.isOpened():
            return None, None, None

        ret, frame = self.cap.read()
        if not ret:
            return None, None, None

        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)

        detection_result = self.detector.detect(mp_image)

        if detection_result.hand_landmarks:
            hand_landmarks = detection_result.hand_landmarks[0]
            # Extract dynamic Left/Right hand label from MediaPipe detection
            handedness_label = detection_result.handedness[0][0].category_name
            return hand_landmarks, frame, handedness_label
        
        return None, frame, None

    def stop_camera(self):
        if self.cap:
            self.cap.release()
            cv2.destroyAllWindows()
