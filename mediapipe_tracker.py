import cv2
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

class HandTracker:
    def __init__(self, model_path="hand_landmarker.task"):
        # Configure MediaPipe Tasks API
        base_options = python.BaseOptions(model_asset_path=model_path)
        options = vision.HandLandmarkerOptions(
            base_options=base_options,
            num_hands=1,
            min_hand_detection_confidence=0.7,
            min_tracking_confidence=0.7
        )
        self.detector = vision.HandLandmarker.create_from_options(options)
        self.cap = None

    def start_camera(self, camera_index=0):
        self.cap = cv2.VideoCapture(camera_index)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    def get_landmarks(self):
        if not self.cap or not self.cap.isOpened():
            return None, None

        ret, frame = self.cap.read()
        if not ret:
            return None, None

        # Convert frame to MediaPipe Image format
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)

        # Process frame
        detection_result = self.detector.detect(mp_image)

        if detection_result.hand_landmarks:
            # Return landmarks array for the first hand detected
            hand_landmarks = detection_result.hand_landmarks[0]
            return hand_landmarks, frame
        
        return None, frame

    def stop_camera(self):
        if self.cap:
            self.cap.release()
            cv2.destroyAllWindows()

if __name__ == "__main__":
    print("Testing MediaPipe 1.0+ Hand Tracker...")
    tracker = HandTracker()
    tracker.start_camera()

    try:
        while True:
            landmarks, _ = tracker.get_landmarks()
            if landmarks:
                # Landmark 9 is the Middle Finger MCP (Palm Center)
                center_node = landmarks[9]
                print(f"Hand Detected! Center (X, Y): ({center_node.x:.2f}, {center_node.y:.2f})", end="\r")
            else:
                print("No hand detected...                            ", end="\r")
    except KeyboardInterrupt:
        print("\nStopping tracker...")
        tracker.stop_camera()
