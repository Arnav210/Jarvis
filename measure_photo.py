import sys
import os
import glob

print("Starting script execution...", flush=True)

import cv2
import torch
import numpy as np
from depth_anything_3.api import DepthAnything3

print("Imports completed successfully.", flush=True)

MASK_DIR = "Masks"        # change to "Masks/latest" if that's where the newest masks are
EDGE_ERODE_PX = 3         # trim mask edges so background pixels don't leak in
MIN_PIXELS = 15           # low enough for small objects (phone, bottle) at depth-map resolution

# Must match the prompts list in sam3_process.py
SAM3_CLASSES = ["bottle", "person", "chair", "laptop", "phone", "table", "screen"]

# 1. Setup device and load Depth Anything 3
device = torch.device("cpu")
print("Loading Depth Anything 3 (DA3-SMALL) model on CPU (this may take a moment)...", flush=True)

model = DepthAnything3.from_pretrained("depth-anything/DA3-SMALL")
model = model.to(device)
model.eval()

print("Model loaded successfully!", flush=True)

# 2. Load the most recent image from Footage
footage_dir = "Footage"
candidates = sorted(glob.glob(os.path.join(footage_dir, "20*.jpg")))
if not candidates:
    print(f"Error: No timestamped images found in '{footage_dir}'.", flush=True)
    sys.exit(1)
image_path = candidates[-1]
image = cv2.imread(image_path)

if image is None:
    print(f"Error: Could not find '{image_path}'. Check path and filename.", flush=True)
    sys.exit(1)

h, w, _ = image.shape
print(f"Loaded image '{image_path}' with resolution {w}x{h}.", flush=True)

# 3. Run metric depth inference
print("Running metric depth estimation...", flush=True)
prediction = model.inference([image_path])
depth_map = prediction.depth[0]  # 2D NumPy array with distances in meters

# Depth map comes out at the model's resolution (e.g. 504x378), not the photo's
dh, dw = depth_map.shape

# 4. Extract whole-frame distance data
center_y, center_x = dh // 2, dw // 2
center_distance = depth_map[center_y, center_x]
min_distance = np.min(depth_map[depth_map > 0])
max_distance = np.max(depth_map)

print("\n================ RESULTS ================")
print(f"Distance at center of photo: {center_distance:.2f} meters")
print(f"Closest point in frame:      {min_distance:.2f} meters")
print(f"Farthest point in frame:     {max_distance:.2f} meters")


# 5. Per-object distances using SAM3 masks
def load_mask(path):
    """Read a mask PNG as a boolean array (object pixels = True)."""
    img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if img is None:
        return None
    if img.ndim == 3 and img.shape[2] == 4:   # RGBA: alpha channel is the mask
        return img[:, :, 3] > 0
    if img.ndim == 3:                         # colour image
        return img.max(axis=2) > 0
    return img > 0                            # grayscale 0/1 or 0/255


def measure_object(depth, mask):
    """Median distance inside the mask, or None if too few valid pixels."""
    # Nearest-neighbour keeps the mask binary when scaling to depth resolution
    mask = cv2.resize(mask.astype(np.uint8), (depth.shape[1], depth.shape[0]),
                      interpolation=cv2.INTER_NEAREST).astype(bool)

    kernel = np.ones((2 * EDGE_ERODE_PX + 1, 2 * EDGE_ERODE_PX + 1), np.uint8)
    eroded = cv2.erode(mask.astype(np.uint8), kernel).astype(bool)
    if eroded.sum() >= MIN_PIXELS:   # small objects keep their full mask
        mask = eroded

    values = depth[mask]
    values = values[np.isfinite(values) & (values > 0)]
    if values.size < MIN_PIXELS:
        return None
    # Median resists outliers; 5th percentile approximates the object's nearest surface
    return float(np.median(values)), float(np.percentile(values, 5)), int(values.size)


def parse_mask_name(name):
    """'chair_0' -> ('chair', 0); returns None for files that aren't SAM3 object masks."""
    label, _, index = name.rpartition("_")
    if label not in SAM3_CLASSES or not index.isdigit():
        return None
    return label, int(index)


mask_paths = [p for p in sorted(glob.glob(os.path.join(MASK_DIR, "*.png")))
              if not p.endswith("_overlay.png")
              and not os.path.basename(p).startswith("combined")]

print("\n============ OBJECT DISTANCES ============")
if not mask_paths:
    print(f"No object masks found in '{MASK_DIR}'.")
    sys.exit(0)

# Masks older than the photo belong to a different frame
if max(map(os.path.getmtime, mask_paths)) < os.path.getmtime(image_path):
    print("[WARN] Masks are older than the latest footage image - rerun SAM3 first.")

results = []
for path in mask_paths:
    name = os.path.splitext(os.path.basename(path))[0]
    parsed = parse_mask_name(name)
    if parsed is None:
        continue  # not a SAM3 object mask (e.g. test.png)
    label, index = parsed

    mask = load_mask(path)
    if mask is None:
        print(f"{label} #{index}: could not read mask")
        continue
    stats = measure_object(depth_map, mask)
    if stats is None:
        print(f"{label} #{index}: too small / no valid depth")
        continue
    distance, nearest, pixels = stats
    results.append((label, index, distance, nearest, pixels))

if not results:
    print("No measurable objects found.")
    sys.exit(0)

# Group by class in the same order as the SAM3 prompts, closest first within each class
for label in SAM3_CLASSES:
    objects = sorted((r for r in results if r[0] == label), key=lambda r: r[2])
    if not objects:
        continue
    print(f"\n{label.upper()} ({len(objects)})")
    for _, index, distance, nearest, pixels in objects:
        print(f"  {label} #{index:<3} {distance:.2f} meters  "
              f"(nearest part {nearest:.2f} m, {pixels} px)")

closest = min(results, key=lambda r: r[2])
print(f"\nClosest object overall: {closest[0]} #{closest[1]} at {closest[2]:.2f} meters")


