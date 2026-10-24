"""Face privacy checks use synthetic images and injected detection bounds."""
import importlib.util
from io import BytesIO
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np
from fastapi.testclient import TestClient
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from face_privacy import FacePrivacy, PrivacyUnavailable

spec = importlib.util.spec_from_file_location("privacy_test_server",
    Path(__file__).resolve().parents[1] / "backend/server.py")
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


class FacePrivacyTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.folder = self.root / "runs/synthetic"
        self.folder.mkdir(parents=True)
        pixels = np.indices((80, 100)).sum(axis=0) % 2 * 255
        self.image = Image.fromarray(np.repeat(pixels[:, :, None], 3, axis=2).astype("uint8"))
        self.original = self.folder / "original.png"
        self.image.save(self.original)
        self.image.save(self.folder / "combined_overlay.png")
        Image.new("L", self.image.size, 255).save(self.folder / "mask.png")
        (self.folder / "manifest.json").write_text(json.dumps({
            "saved_original": "original.png", "prompts": ["person"], "detections": [
                {"prompt": "person", "index": 0, "box": [0, 0, 99, 79],
                 "raw_mask": "mask.png", "score": .9}]}))
        self.engine = FacePrivacy(self.root / "fake-model.onnx")
        for target, name, value in [
            (self.engine, "_ready", (cv2, ("test-model",))),
            (self.engine, "_regions", (self.image.size, ((20, 15, 65, 65),)))]:
            mock = patch.object(target, name, return_value=value)
            mock.start()
            self.addCleanup(mock.stop)
        for name, value in [("RUNS_DIR", self.root / "runs"), ("FACE_PRIVACY", self.engine),
                            ("FACE_BLUR_ENABLED", True),
                            ("SAM3_SOURCE", self.root / "absent.py")]:
            mock = patch.object(server, name, value)
            mock.start()
            self.addCleanup(mock.stop)
        self.client = TestClient(server.app)

    def redacted(self, response):
        self.assertEqual(response.status_code, 200, response.text if response.status_code != 200 else "")
        self.assertEqual(response.headers["x-privacy-mode"], "faces-v1")
        self.assertIn("no-store", response.headers["cache-control"])
        pixels = np.asarray(Image.open(BytesIO(response.content)).convert("RGB"))
        self.assertLess(pixels[20:60, 25:60].std(), 10)
        return pixels

    def test_disabled_mode_returns_full_images_without_loading_detector(self):
        with patch.object(server, "FACE_BLUR_ENABLED", False):
            with patch.object(self.engine, "_ready", side_effect=AssertionError("Detector must stay off")):
                for filename in ("original.png", "combined_overlay.png"):
                    response = self.client.get("/runs/synthetic/" + filename)
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.content, (self.folder / filename).read_bytes())
                    self.assertEqual(response.headers["x-faces-blurred"], "0")
                for path in ("/api/overlay/synthetic?categories=", "/api/detections/synthetic/0/highlight"):
                    response = self.client.get(path)
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.headers["x-faces-blurred"], "0")
                    self.assertEqual(response.headers["x-privacy-mode"], "unblurred-v1")

    def test_photo_is_blurred_and_source_unchanged(self):
        before = self.original.read_bytes()
        image = self.redacted(self.client.get("/runs/synthetic/original.png"))
        self.assertEqual(tuple(image[5, 5]), self.image.getpixel((5, 5)))
        self.assertEqual(self.original.read_bytes(), before)

    def test_saved_overlay_is_also_blurred(self):
        self.redacted(self.client.get("/runs/synthetic/combined_overlay.png"))

    def test_filtering_all_masks_off_cannot_disable_face_blur(self):
        self.redacted(self.client.get("/api/overlay/synthetic?categories="))

    def test_selected_object_highlight_is_blurred(self):
        self.redacted(self.client.get("/api/detections/synthetic/0/highlight"))

    def test_raw_flags_do_not_bypass_privacy(self):
        self.redacted(self.client.get("/runs/synthetic/original.png?raw=true&privacy=off"))

    def test_raw_files_and_nested_paths_are_not_served(self):
        for path in ("manifest.json", "mask.png", "raw_masks/person.png",
                     "original.png.backup", "../outside.png"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get("/runs/synthetic/" + path).status_code, 404)

    def test_capture_symlink_outside_archive_is_not_served(self):
        (self.root / "runs/escape").symlink_to(self.folder.parent.parent, target_is_directory=True)
        self.assertEqual(self.client.get("/runs/escape/original.png").status_code, 404)

    def test_image_symlink_outside_capture_is_not_served(self):
        self.original.unlink()
        outside = self.root / "outside.png"
        self.image.save(outside)
        self.original.symlink_to(outside)
        self.assertEqual(self.client.get("/runs/synthetic/original.png").status_code, 404)

    def test_detector_failure_withholds_every_view(self):
        with patch.object(self.engine, "_regions", side_effect=RuntimeError("injected detector failure")):
            for path in ("/runs/synthetic/original.png", "/runs/synthetic/combined_overlay.png",
                         "/api/overlay/synthetic?categories=", "/api/detections/synthetic/0/highlight"):
                with self.subTest(path=path):
                    response = self.client.get(path)
                    self.assertEqual(response.status_code, 503)
                    self.assertNotIn(b"PNG", response.content)

    def test_missing_model_cannot_release_a_raw_image(self):
        with patch.object(server, "FACE_PRIVACY", FacePrivacy(self.root / "missing.onnx")):
            self.assertEqual(self.client.get("/runs/synthetic/original.png").status_code, 503)

    def test_view_with_mismatched_dimensions_is_withheld(self):
        Image.new("RGB", (3, 3)).save(self.folder / "combined_overlay.png")
        self.assertEqual(self.client.get("/runs/synthetic/combined_overlay.png").status_code, 503)

    def test_legacy_capture_without_manifest_still_blurs(self):
        (self.folder / "manifest.json").unlink()
        self.redacted(self.client.get("/runs/synthetic/original.png"))

    def test_overlay_without_source_is_withheld(self):
        self.original.unlink()
        self.assertEqual(self.client.get("/runs/synthetic/combined_overlay.png").status_code, 409)

    def test_cached_image_is_invalidated_when_source_changes(self):
        first = self.client.get("/runs/synthetic/original.png").content
        Image.new("RGB", (100, 80), "red").save(self.original)
        second = self.client.get("/runs/synthetic/original.png").content
        self.assertNotEqual(first, second)

    def test_image_cache_is_bounded(self):
        for index in range(36):
            path = self.folder / ("test-" + str(index) + ".png")
            self.image.save(path)
            self.engine.file(path, self.original)
        self.assertLessEqual(len(self.engine._images), 32)

    def test_model_hash_mismatch_is_rejected(self):
        path = self.root / "invalid.onnx"
        path.write_bytes(b"not a verified model")
        with self.assertRaises(PrivacyUnavailable):
            FacePrivacy(path).file(self.original, self.original)


if __name__ == "__main__":
    unittest.main()
