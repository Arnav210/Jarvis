"""Mask controls use saved synthetic images; no model or camera is loaded."""
import importlib.util
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from fastapi import HTTPException
from PIL import Image

spec = importlib.util.spec_from_file_location("mask_test_server", Path(__file__).resolve().parents[1] / "backend" / "server.py")
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


class MaskTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        server.SAM3_SOURCE = self.root / "sam3_process.py"
        server.SAM3_SOURCE.write_text("raise RuntimeError('Do not execute SAM3')\nprompts=['person','phone','chair']\npalette=[(255,0,0),(0,255,0),(0,0,255)]\n")
        server.RUNS_DIR = self.root / "runs"
        self.run = server.RUNS_DIR / "synthetic"
        (self.run / "raw_masks").mkdir(parents=True)
        Image.new("RGB", (100, 80), (100, 100, 100)).save(self.run / "original.png")
        left, right = Image.new("L", (100, 80)), Image.new("L", (100, 80))
        left.paste(255, (0, 0, 50, 80)); right.paste(255, (50, 0, 100, 80))
        left.save(self.run / "raw_masks/person_0.png")
        right.save(self.run / "raw_masks/phone_0.png")
        self.manifest = {"saved_original":"original.png", "prompts":["person","phone","chair"], "detections":[
            {"prompt":"person","index":0,"raw_mask":"raw_masks/person_0.png","box":[0,0,48,78],"score":.9},
            {"prompt":"phone","index":0,"raw_mask":"raw_masks/phone_0.png","box":[51,0,99,78],"score":.8}]}
        self.save_manifest()

    def save_manifest(self):
        (self.run / "manifest.json").write_text(json.dumps(self.manifest))

    def render(self, categories):
        response = server.filtered_overlay("synthetic", categories)
        return Image.open(BytesIO(response.body)).convert("RGB")

    def test_categories_follow_source_without_executing_it(self):
        self.assertEqual(server.get_mask_categories()["categories"], ["person","phone","chair"])
        server.SAM3_SOURCE.write_text("prompts=['bottle','desk']\n")
        self.assertEqual(server.get_mask_categories()["categories"], ["bottle","desk"])

    def test_deselected_category_has_no_tint_or_box(self):
        image = self.render(["phone"])
        self.assertEqual(image.getpixel((20,40)), (100,100,100))
        self.assertEqual(image.getpixel((0,40)), (100,100,100))
        self.assertNotEqual(image.getpixel((70,40)), (100,100,100))
        self.assertNotEqual(image.getpixel((99,40)), (100,100,100))

    def test_none_selected_is_exact_original(self):
        self.assertEqual(self.render([""]).tobytes(), Image.open(self.run / "original.png").convert("RGB").tobytes())

    def test_all_categories_and_empty_category(self):
        image = self.render(None)
        self.assertNotEqual(image.getpixel((20,40)), (100,100,100))
        self.assertNotEqual(image.getpixel((70,40)), (100,100,100))
        self.assertEqual(self.render(["chair"]).getpixel((20,40)), (100,100,100))

    def test_unknown_categories_and_traversal_are_rejected(self):
        with self.assertRaises(HTTPException) as error:
            server.filtered_overlay("synthetic", ["invented"])
        self.assertEqual(error.exception.status_code, 400)
        with self.assertRaises(HTTPException) as error:
            server.filtered_overlay("..", ["person"])
        self.assertEqual(error.exception.status_code, 404)

    def test_missing_mask_does_not_fall_back_to_unfiltered_overlay(self):
        (self.run / "raw_masks/person_0.png").unlink()
        with self.assertRaises(HTTPException) as error:
            self.render(["person"])
        self.assertEqual(error.exception.status_code, 409)

    def test_manifest_cannot_read_files_outside_capture(self):
        Image.new("L", (100,80), 255).save(self.root / "outside.png")
        self.manifest["detections"][0]["raw_mask"] = "../../outside.png"
        self.save_manifest()
        with self.assertRaises(HTTPException):
            self.render(["person"])


if __name__ == "__main__":
    unittest.main()
