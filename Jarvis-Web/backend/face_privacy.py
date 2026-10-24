"""Local face redaction for web images; never writes over source captures."""
from collections import OrderedDict
from functools import lru_cache
from io import BytesIO
import hashlib
import math
from pathlib import Path
from threading import RLock

import numpy as np
from PIL import Image

MODEL = Path(__file__).resolve().parents[2] / "models/face-privacy/face_detection_yunet_2023mar.onnx"
MODEL_SHA256 = "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"


class PrivacyUnavailable(RuntimeError):
    pass


class FacePrivacy:
    """One locked CPU detector, bounded in-memory caches, and no raw-image fallback."""
    def __init__(self, model=MODEL):
        self.model = Path(model)
        self._lock = RLock()
        self._detector = None
        self._model_key = None
        self._images = OrderedDict()
        self._image_bytes = 0

    @staticmethod
    def _key(path):
        path = Path(path).resolve()
        stat = path.stat()
        return str(path), stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size

    def _ready(self):
        import cv2
        key = self._key(self.model)
        if key != self._model_key:
            if hashlib.sha256(self.model.read_bytes()).hexdigest() != MODEL_SHA256:
                raise PrivacyUnavailable("The face detector model could not be verified")
            detector = cv2.FaceDetectorYN.create(str(self.model), "", (320, 320),
                                                0.45, 0.3, 5000)
            if detector is None:
                raise PrivacyUnavailable("The face detector could not be loaded")
            self._detector, self._model_key = detector, key
            self._regions.cache_clear()
            self._images.clear()
            self._image_bytes = 0
        return cv2, key

    @lru_cache(maxsize=256)
    def _regions(self, source_key, model_key):
        import cv2
        with Image.open(source_key[0]) as image:
            rgb = image.convert("RGB")
        width, height = rgb.size
        if width < 1 or height < 1:
            raise PrivacyUnavailable("The source picture has invalid dimensions")
        # Upscale small room captures to improve sensitivity to distant faces.
        scale = min(2.0, 1280.0 / max(width, height))
        scaled = cv2.resize(np.asarray(rgb)[:, :, ::-1],
                            (max(1, round(width * scale)), max(1, round(height * scale))))
        sx, sy = scaled.shape[1] / width, scaled.shape[0] / height
        boxes = set()
        self._detector.setInputSize((scaled.shape[1], scaled.shape[0]))
        # A mirrored pass improves coverage of angled faces.
        for mirrored in (False, True):
            frame = cv2.flip(scaled, 1) if mirrored else scaled
            _, faces = self._detector.detect(frame)
            if faces is None:
                continue
            for face in faces:
                if len(face) < 15 or not np.isfinite(face).all():
                    raise PrivacyUnavailable("The face detector returned invalid results")
                x, y, w, h = map(float, face[:4])
                if w <= 0 or h <= 0:
                    raise PrivacyUnavailable("The face detector returned invalid bounds")
                if mirrored:
                    x = scaled.shape[1] - x - w
                x, y, w, h = x / sx, y / sy, w / sx, h / sy
                # Include forehead, jaw, and a margin beyond the detected face.
                box = (max(0, math.floor(x - .3 * w)),
                       max(0, math.floor(y - .4 * h)),
                       min(width, math.ceil(x + 1.3 * w)),
                       min(height, math.ceil(y + 1.3 * h)))
                if box[2] > box[0] and box[3] > box[1]:
                    boxes.add(box)
        if self._key(source_key[0]) != source_key:
            raise PrivacyUnavailable("The source picture changed during processing")
        return (width, height), tuple(sorted(boxes))

    def render(self, image, original):
        """Blur original-derived face bounds on any same-size rendered view."""
        try:
            with self._lock:
                cv2, model_key = self._ready()
                source_key = self._key(original)
                size, boxes = self._regions(source_key, model_key)
                if image.size != size:
                    raise PrivacyUnavailable("Image dimensions do not match its source")
                pixels = np.array(image.convert("RGB"))
                for x1, y1, x2, y2 in boxes:
                    region = pixels[y1:y2, x1:x2]
                    pixels[y1:y2, x1:x2] = cv2.GaussianBlur(
                        region, (0, 0), sigmaX=max(12.0, min(region.shape[:2]) / 3))
                output = BytesIO()
                Image.fromarray(pixels).save(output, format="PNG")
                return output.getvalue(), len(boxes)
        except PrivacyUnavailable:
            raise
        except Exception as error:
            raise PrivacyUnavailable("Face privacy processing is unavailable") from error

    def file(self, path, original):
        try:
            with self._lock:
                _, model_key = self._ready()
                key = (self._key(path), self._key(original), model_key)
                if key in self._images:
                    self._images.move_to_end(key)
                    return self._images[key]
                with Image.open(path) as image:
                    result = self.render(image.convert("RGB"), original)
                if self._key(path) != key[0] or self._key(original) != key[1]:
                    raise PrivacyUnavailable("The picture changed during processing")
                self._images[key] = result
                self._image_bytes += len(result[0])
                while len(self._images) > 32 or self._image_bytes > 32 * 1024 * 1024:
                    _, removed = self._images.popitem(last=False)
                    self._image_bytes -= len(removed[0])
                return result
        except PrivacyUnavailable:
            raise
        except Exception as error:
            raise PrivacyUnavailable("Face privacy processing is unavailable") from error
