# Purpose: numeric diff analysis of the replay test frames to see why
# green/blue fail the chroma gate while red passes.
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.config import load_config

config = load_config()
x1, y1, x2, y2 = config["led_regions"]["rgb_led"]
d = Path(sys.argv[1])

base = np.asarray(Image.open(d / "replay_off.jpg").convert("RGB"), dtype=np.float64)[
    y1:y2, x1:x2
]

for name in ("red", "green", "blue"):
    frame = np.asarray(
        Image.open(d / f"replay_{name}.jpg").convert("RGB"), dtype=np.float64
    )[y1:y2, x1:x2]
    diff = (frame - base).reshape(-1, 3)
    order = np.argsort(diff.sum(axis=-1))
    for k in (10, 25, 50):
        top = diff[order[-k:]].mean(axis=0)
        chroma = top.max() - top.min()
        print(
            f"{name} top-{k}: RGB={top.round(1)} mag={top.max():.0f}"
            f" chroma={chroma:.0f}"
        )
    print()
