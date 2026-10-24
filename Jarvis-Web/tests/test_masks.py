"""Mask controls use saved synthetic images; no model or camera is loaded."""
import importlib.util
import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1] / "backend"))
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

    def test_irregular_mask_outline_follows_shape_instead_of_box(self):
        mask = Image.new("L", (100, 80))
        mask.paste(255, (20, 25, 35, 70))
        mask.paste(255, (20, 55, 80, 70))
        path = self.run / "raw_masks/person_0.png"
        mask.save(path)
        self.manifest["detections"][0]["box"] = [20, 25, 80, 70]
        self.save_manifest()
        before = path.read_bytes()
        image = self.render(["person"])
        self.assertEqual(image.getpixel((34, 45)), (255, 0, 0))
        self.assertEqual(image.getpixel((80, 40)), (100, 100, 100))
        self.assertNotEqual(image.getpixel((25, 45)), (255, 0, 0))
        self.assertEqual(path.read_bytes(), before)

    def test_contours_preserve_holes_and_disconnected_components(self):
        mask = Image.new("L", (100, 80))
        mask.paste(255, (20, 20, 60, 60))
        mask.paste(0, (30, 30, 50, 50))
        mask.paste(255, (75, 70, 80, 75))
        base = Image.new("RGB", mask.size, (100, 100, 100))
        before = mask.tobytes()
        image = server.draw_mask_contours(base, [(mask, (255, 0, 0))])
        self.assertEqual(image.getpixel((20, 40)), (255, 0, 0))
        self.assertEqual(image.getpixel((29, 40)), (255, 0, 0))
        self.assertEqual(image.getpixel((40, 40)), (100, 100, 100))
        self.assertEqual(image.getpixel((75, 70)), (255, 0, 0))
        self.assertEqual(mask.tobytes(), before)

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


class InspectionTests(unittest.TestCase):
    setUp = MaskTests.setUp
    save_manifest = MaskTests.save_manifest

    def test_metadata_has_stable_frame_ids_and_detection_scores(self):
        data = server.get_detections('synthetic')
        self.assertEqual((data['width'], data['height']), (100, 80))
        self.assertEqual([d['id'] for d in data['detections']], [0, 1])
        self.assertEqual(data['detections'][0]['score'], .9)
        self.assertEqual(data['detections'][0]['number'], 1)
        self.assertTrue(all(d['mask_available'] for d in data['detections']))

    def test_hit_uses_mask_pixels_instead_of_bounding_box(self):
        self.assertEqual(server.hit_detection('synthetic', 49, 79, None)['selected_id'], 0)
        mask = Image.open(self.run / 'raw_masks/person_0.png').convert('L')
        mask.paste(0, (20, 30, 30, 50));mask.save(self.run / 'raw_masks/person_0.png')
        self.assertIsNone(server.hit_detection('synthetic', 25, 40, None)['selected_id'])

    def test_overlap_prefers_smaller_object_and_preserves_all_hits(self):
        self.manifest['detections'][1]['box'] = [10, 10, 20, 20]
        self.save_manifest()
        mask = Image.new('L', (100, 80));mask.paste(255, (8, 8, 22, 22));mask.save(self.run / 'raw_masks/phone_0.png')
        data = server.hit_detection('synthetic', 15, 15, None)
        self.assertEqual(data['selected_id'], 1)
        self.assertEqual(data['hit_ids'], [1, 0])

    def test_hit_respects_hidden_categories_and_empty_selection(self):
        self.assertIsNone(server.hit_detection('synthetic', 20, 40, ['phone'])['selected_id'])
        self.assertIsNone(server.hit_detection('synthetic', 20, 40, [''])['selected_id'])
        with self.assertRaises(HTTPException):
            server.hit_detection('synthetic', 20, 40, ['invented'])

    def test_highlight_follows_mask_without_drawing_box(self):
        mask = Image.new("L", (100, 80))
        mask.paste(255, (20, 25, 35, 70))
        mask.paste(255, (20, 55, 80, 70))
        mask.save(self.run / "raw_masks/person_0.png")
        self.manifest["detections"][0]["box"] = [20, 25, 80, 70]
        self.save_manifest()
        response = server.highlight_detection("synthetic", 0)
        image = Image.open(BytesIO(response.body)).convert("RGB")
        self.assertEqual(image.getpixel((34, 45)), (235, 216, 174))
        self.assertEqual(image.getpixel((80, 40)), (37, 37, 37))

    def test_highlight_dims_background_and_preserves_source_files(self):
        original = (self.run / 'original.png').read_bytes()
        mask = (self.run / 'raw_masks/person_0.png').read_bytes()
        response = server.highlight_detection('synthetic', 0)
        image = Image.open(BytesIO(response.body)).convert('RGB')
        self.assertLess(image.getpixel((70, 40))[0], 50)
        self.assertGreater(image.getpixel((20, 40))[0], 100)
        self.assertEqual(original, (self.run / 'original.png').read_bytes())
        self.assertEqual(mask, (self.run / 'raw_masks/person_0.png').read_bytes())

    def test_traversal_and_outside_coordinates_are_rejected(self):
        with self.assertRaises(HTTPException):
            server.get_detections('..')
        for x, y in [(-1, 0), (100, 40), (20, 80)]:
            with self.assertRaises(HTTPException) as error:
                server.hit_detection('synthetic', x, y, None)
            self.assertEqual(error.exception.status_code, 400)
        with self.assertRaises(HTTPException):
            server.highlight_detection('synthetic', -1)
        self.manifest['detections'][0]['raw_mask'] = '../../outside.png';self.save_manifest()
        self.assertFalse(server.get_detections('synthetic')['detections'][0]['mask_available'])
        with self.assertRaises(HTTPException):
            server.highlight_detection('synthetic', 0)

    def test_missing_legacy_manifest_and_mismatched_mask_are_unavailable(self):
        Image.new('L', (3, 3), 255).save(self.run / 'raw_masks/person_0.png')
        with self.assertRaises(HTTPException) as error:
            server.highlight_detection('synthetic', 0)
        self.assertEqual(error.exception.status_code, 409)
        (self.run / 'manifest.json').unlink()
        with self.assertRaises(HTTPException) as error:
            server.get_detections('synthetic')
        self.assertEqual(error.exception.status_code, 409)

    def test_invalid_boxes_and_scores_do_not_reach_the_inspector(self):
        self.manifest['detections'][0]['score'] = float('nan')
        self.manifest['detections'][1]['box'] = [0, 0, float('nan'), 10]
        self.save_manifest()
        data = server.get_detections('synthetic')['detections']
        self.assertEqual(len(data), 1)
        self.assertIsNone(data[0]['score'])
