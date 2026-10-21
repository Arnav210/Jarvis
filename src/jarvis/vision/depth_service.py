
# Allow the dedicated runtime interpreters to execute this source file directly.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))

import os
import time
import glob
import cv2
import torch
import numpy as np
from depth_anything_3.api import DepthAnything3

RUNS_DIR = "Masks/runs"
EDGE_ERODE_PX = 3
MIN_PIXELS = 15
SAM3_CLASSES = ["bottle", "person", "chair", "laptop", "phone", "table", "screen"]

print("Initializing Depth-Anything-3 Service...", flush=True)
device = torch.device("cpu")  # Switch to "cuda" if using a GPU
print("Loading Depth Anything 3 model...", flush=True)
model = DepthAnything3.from_pretrained("depth-anything/DA3-SMALL").to(device)
model.eval()
print("Model loaded successfully. Watching for new runs...", flush=True)

processed_runs = set()

def read_mask(path):
    img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if img is None:
        return None
    if img.ndim == 3 and img.shape[2] == 4:
        return img[:, :, 3] > 0
    if img.ndim == 3:
        return img.max(axis=2) > 0
    return img > 0

def measure_object(depth, mask):
    mask = cv2.resize(mask.astype(np.uint8), (depth.shape[1], depth.shape[0]), interpolation=cv2.INTER_NEAREST).astype(bool)
    kernel = np.ones((2 * EDGE_ERODE_PX + 1, 2 * EDGE_ERODE_PX + 1), np.uint8)
    eroded = cv2.erode(mask.astype(np.uint8), kernel).astype(bool)
    if eroded.sum() >= MIN_PIXELS:
        mask = eroded

    values = depth[mask]
    values = values[np.isfinite(values) & (values > 0)]
    if values.size < MIN_PIXELS:
        return None
    return float(np.median(values)), float(np.percentile(values, 5)), int(values.size)

def process_runs():
    # Find all timestamped run directories
    run_folders = [f for f in glob.glob(os.path.join(RUNS_DIR, "*")) if os.path.isdir(f)]

    for run_folder in run_folders:
        if run_folder in processed_runs:
            continue

        original_img_path = os.path.join(run_folder, "original.jpg")
        raw_masks_dir = os.path.join(run_folder, "raw_masks")

        # Ensure SAM 3 has finished writing the files for this run
        if not os.path.exists(original_img_path) or not os.path.exists(raw_masks_dir):
            continue

        print(f"\n[Service] New SAM 3 run detected: {run_folder}", flush=True)

        image = cv2.imread(original_img_path)
        if image is None:
            print(f"Error: Could not read {original_img_path}")
            continue

        # Run Depth Anything 3 metric depth inference automatically
        print("Running Depth-Anything-3 inference...", flush=True)
        with torch.no_grad():
            prediction = model(image)

        if isinstance(prediction, dict):
            depth_map = prediction.get('depth', prediction.get('metric_depth'))
        else:
            depth_map = prediction

        if torch.is_tensor(depth_map):
            depth_map = depth_map.squeeze().cpu().numpy()

        # Process individual raw masks inside the run folder
        mask_paths = glob.glob(os.path.join(raw_masks_dir, "*.png"))
        for mask_path in mask_paths:
            mask_name = os.path.basename(mask_path)
            label, _, index = mask_name.rpartition("_")
            if label not in SAM3_CLASSES or not index.isdigit():
                continue

            mask = read_mask(mask_path)
            if mask is None:
                continue

            metrics = measure_object(depth_map, mask)
            if metrics:
                median_d, p5_d, count = metrics
                print(f" -> Object: {mask_name} | Median Depth: {median_d:.2f}m | Pixels: {count}")

        # Mark this run folder as processed so it doesn't repeat
        processed_runs.add(run_folder)

if __name__ == "__main__":
    try:
        while True:
            process_runs()
            time.sleep(2)  # Check for new runs every 2 seconds
    except KeyboardInterrupt:
        print("\nDepth service stopped.")
