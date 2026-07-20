# Purpose: locate the LED matrix (lit only during the red phase) and
# verify differential R/G/B classification of LED3 over 12 frames.
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.config import load_config
from harness.vision import capture_frame

OUT = Path(__file__).resolve().parent / "verify_burst"
OUT.mkdir(exist_ok=True)
N = 12
LED_REGION = (434, 233, 460, 258)  # x1, y1, x2, y2

config = load_config()
frames = []
for i in range(N):
    path = OUT / f"v_{i}.jpg"
    capture_frame(config, path, lock_dir=config.results_dir)
    frames.append(np.asarray(Image.open(path).convert("RGB"), dtype=np.float64))
    print(f"captured {path.name}")
    time.sleep(1.2)

stack = np.stack(frames)

# LED3 differential classification per frame.
x1, y1, x2, y2 = LED_REGION
region = stack[:, y1:y2, x1:x2]
dark = region.min(axis=0)
print("\nper-frame LED classification:")
led_sequence = []
for i in range(N):
    diff = (region[i] - dark).reshape(-1, 3)
    top = diff[np.argsort(diff.sum(axis=1))[-25:]].mean(axis=0)
    if top.max() < 25:
        label = "off"
    else:
        label = ["red", "green", "blue"][int(np.argmax(top))]
    led_sequence.append(label)
    print(f"  {i}: diff RGB {top.round(0)} -> {label}")

# Matrix location: brightness change between red-phase and other
# frames, using LED sequence as the phase key.
red_idx = [i for i, c in enumerate(led_sequence) if c == "red"]
other_idx = [i for i, c in enumerate(led_sequence) if c in ("green", "blue")]
if red_idx and other_idx:
    red_mean = stack[red_idx].mean(axis=0).sum(axis=-1)
    other_mean = stack[other_idx].mean(axis=0).sum(axis=-1)
    bright_diff = red_mean - other_mean
    ys, xs = np.nonzero(bright_diff > 90)
    # Keep the cluster on/near the board (y < 320 excludes monitor glow).
    keep = ys < 320
    if keep.any():
        print(
            f"\nmatrix bbox: [{xs[keep].min()}, {ys[keep].min()},"
            f" {xs[keep].max()}, {ys[keep].max()}] n={keep.sum()}"
        )
    else:
        print("\nno matrix cluster found above monitor line")
else:
    print("\nnot enough phase coverage to locate matrix")
