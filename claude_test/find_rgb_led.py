# Purpose: locate the cycling RGB LED in the camera frame by capturing
# a burst over one full R/G/B cycle and ranking pixels by color change.
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.config import load_config
from harness.vision import capture_frame

OUT = Path(__file__).resolve().parent / "rgb_burst"
OUT.mkdir(exist_ok=True)
N_FRAMES = 8
INTERVAL_S = 1.4  # 8 x 1.4s > one 9s cycle

config = load_config()
frames = []
for i in range(N_FRAMES):
    path = OUT / f"burst_{i}.jpg"
    capture_frame(config, path, lock_dir=config.results_dir)
    frames.append(np.asarray(Image.open(path).convert("RGB"), dtype=np.float64))
    print(f"captured {path.name}")
    time.sleep(INTERVAL_S)

stack = np.stack(frames)  # (n, h, w, 3)
# Per-pixel per-channel range across time: the LED area changes color
# dramatically while the rest of the scene is static.
change = (stack.max(axis=0) - stack.min(axis=0)).sum(axis=-1)  # (h, w)
threshold = np.percentile(change, 99.8)
ys, xs = np.nonzero(change >= max(threshold, 60.0))
if len(xs) == 0:
    print("no changing pixels found -- is the LED cycling?")
    sys.exit(1)

# Dense cluster around the strongest change.
peak_idx = np.argmax(change)
py, px = np.unravel_index(peak_idx, change.shape)
near = (np.abs(ys - py) < 60) & (np.abs(xs - px) < 60)
x1, x2 = int(xs[near].min()), int(xs[near].max())
y1, y2 = int(ys[near].min()), int(ys[near].max())
pad = 6
x1, y1 = max(0, x1 - pad), max(0, y1 - pad)
x2, y2 = min(stack.shape[2], x2 + pad), min(stack.shape[1], y2 + pad)
print(f"peak change at ({px},{py}), max change {change.max():.0f}")
print(f"suggested rgb_led region: [{x1}, {y1}, {x2}, {y2}]")
print(f"changing pixels in cluster: {int(near.sum())}")
