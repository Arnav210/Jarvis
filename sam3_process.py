import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import torch
from PIL import Image, ImageDraw

from sam3.model_builder import build_sam3_image_model
from sam3.model.sam3_image_processor import Sam3Processor


if len(sys.argv) < 2:
    print("Usage: python sam3_process.py <image_path>")
    sys.exit(1)

image_path = Path(sys.argv[1]).expanduser().resolve()
if not image_path.is_file():
    print(f"Image not found: {image_path}")
    sys.exit(1)


print("Loading SAM 3...")
model = build_sam3_image_model(device="cpu")
resolution = int(os.getenv("SAM3_RESOLUTION", "1008"))
processor = Sam3Processor(model, resolution=resolution, device="cpu")
print(f"SAM 3 inference resolution: {resolution}x{resolution}")
print("SAM 3 loaded.")


print(f"Opening image: {image_path}")
image = Image.open(image_path).convert("RGB")
state = processor.set_image(image)

prompts = [
    "person",
    "laptop",
    "phone",
    "monitor",
    "chair",
]


# Name each immutable result folder for when the image was captured. Images from
# jarvis-camera carry that local timestamp in their filename; imported images
# fall back to their file modification time.
def get_capture_timestamp(path):
    filename_match = re.fullmatch(
        r"(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})(?:_(\d{6}))?",
        path.stem,
    )
    if filename_match:
        timestamp_text = filename_match.group(1)
        timestamp_format = "%Y-%m-%d_%H-%M-%S"
        if filename_match.group(2):
            timestamp_text += f"_{filename_match.group(2)}"
            timestamp_format += "_%f"
        captured_at = datetime.strptime(timestamp_text, timestamp_format).astimezone()
        return captured_at, "filename"

    return datetime.fromtimestamp(path.stat().st_mtime).astimezone(), "file_mtime"


masks_root = Path.home() / "Jarvis" / "Masks"
runs_root = masks_root / "runs"
runs_root.mkdir(parents=True, exist_ok=True)

captured_at, capture_timestamp_source = get_capture_timestamp(image_path)
processed_at = datetime.now(timezone.utc)
run_base = captured_at.strftime("%Y-%m-%d_%H-%M-%S_%f")
output_folder = runs_root / run_base
suffix = 1
while output_folder.exists():
    output_folder = runs_root / f"{run_base}_{suffix:02d}"
    suffix += 1

raw_folder = output_folder / "raw_masks"
overlay_folder = output_folder / "overlays"
raw_folder.mkdir(parents=True)
overlay_folder.mkdir(parents=True)

original_name = f"original{image_path.suffix.lower() or '.jpg'}"
shutil.copy2(image_path, output_folder / original_name)

base_image = np.asarray(image).copy()
combined_overlay = base_image.copy()
palette = [
    (255, 80, 80),
    (80, 200, 255),
    (120, 255, 120),
    (255, 200, 80),
    (200, 120, 255),
    (255, 120, 200),
]
annotations = []
detections = []


for prompt_index, prompt in enumerate(prompts):
    print(f"\nLooking for: {prompt}")
    output = processor.set_text_prompt(state=state, prompt=prompt)
    masks = output["masks"]
    boxes = output["boxes"]
    scores = output["scores"]

    print("Detections:", len(scores))
    print("Scores:", scores)
    print("Boxes:", boxes)

    if len(masks) == 0:
        print(f"No {prompt} detected.")
        continue

    for index, mask_tensor in enumerate(masks):
        mask_array = mask_tensor.squeeze(0).detach().cpu().numpy()
        mask_bool = mask_array.astype(bool)
        mask_image = Image.fromarray(mask_bool.astype(np.uint8) * 255)

        mask_name = f"{prompt}_{index}.png"
        mask_path = raw_folder / mask_name
        mask_image.save(mask_path)

        color = palette[(prompt_index * 7 + index) % len(palette)]
        alpha = 0.45
        overlay_array = base_image.copy()
        overlay_array[mask_bool] = (
            overlay_array[mask_bool] * (1.0 - alpha) + np.array(color) * alpha
        ).astype(np.uint8)
        combined_overlay[mask_bool] = (
            combined_overlay[mask_bool] * (1.0 - alpha) + np.array(color) * alpha
        ).astype(np.uint8)

        box = tuple(int(value) for value in boxes[index].detach().cpu().tolist())
        score = float(scores[index].detach().cpu().item())
        label = f"{prompt} {score:.2f}"

        overlay_image = Image.fromarray(overlay_array)
        overlay_draw = ImageDraw.Draw(overlay_image)
        overlay_draw.rectangle(box, outline=color, width=3)
        overlay_draw.text(
            (box[0] + 4, max(2, box[1] - 14)),
            label,
            fill=color,
            stroke_width=2,
            stroke_fill=(0, 0, 0),
        )
        overlay_path = overlay_folder / mask_name
        overlay_image.save(overlay_path)

        annotations.append((box, label, color))
        detections.append(
            {
                "prompt": prompt,
                "index": index,
                "score": round(score, 6),
                "box": list(box),
                "raw_mask": str(mask_path.relative_to(output_folder)),
                "overlay": str(overlay_path.relative_to(output_folder)),
            }
        )
        print(f"Saved mask: {mask_path}")


combined_image = Image.fromarray(combined_overlay)
combined_draw = ImageDraw.Draw(combined_image)
for box, label, color in annotations:
    combined_draw.rectangle(box, outline=color, width=3)
    combined_draw.text(
        (box[0] + 4, max(2, box[1] - 14)),
        label,
        fill=color,
        stroke_width=2,
        stroke_fill=(0, 0, 0),
    )

combined_path = output_folder / "combined_overlay.png"
combined_image.save(combined_path)

manifest = {
    "schema_version": 1,
    "run_id": output_folder.name,
    "captured_at": captured_at.isoformat(),
    "capture_timestamp_source": capture_timestamp_source,
    "processed_at": processed_at.isoformat(),
    "source_image": str(image_path),
    "saved_original": original_name,
    "resolution": resolution,
    "image_size": {"width": image.width, "height": image.height},
    "prompts": prompts,
    "detection_count": len(detections),
    "detections": detections,
}
manifest_temp = output_folder / ".manifest.json.tmp"
manifest_temp.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
manifest_temp.replace(output_folder / "manifest.json")

# Update the pointer only after every result and the manifest have been saved.
latest_link = masks_root / "latest"
temporary_link = masks_root / f".latest-{os.getpid()}"
temporary_link.symlink_to(output_folder.relative_to(masks_root), target_is_directory=True)
temporary_link.replace(latest_link)

print(f"Saved combined overlay: {combined_path}")
print(f"Saved manifest: {output_folder / 'manifest.json'}")
print(f"Latest result: {latest_link} -> {output_folder.relative_to(masks_root)}")
print("\nFinished processing image.")
