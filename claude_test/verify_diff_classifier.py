# Purpose: verify dominant_color_diff accuracy on the 12-frame LED3
# burst using a per-pixel-min pseudo-baseline (LED-off approximation).
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.config import load_config
from harness.vision import dominant_color_diff

BURST = Path(__file__).resolve().parent / "verify_burst"
EXPECTED = [
    "blue",
    "red",
    "blue",
    "red",
    "blue",
    "red",
    "green",
    "red",
    "green",
    "blue",
    "green",
    "blue",
]

stack = np.stack(
    [
        np.asarray(Image.open(BURST / f"v_{i}.jpg").convert("RGB"), dtype=np.float64)
        for i in range(12)
    ]
)
baseline_path = BURST / "pseudo_baseline.jpg"
Image.fromarray(stack.min(axis=0).astype(np.uint8)).save(baseline_path)

config = load_config()
correct = 0
for i in range(12):
    result = dominant_color_diff(
        BURST / f"v_{i}.jpg",
        baseline_path,
        config["led_regions"]["rgb_led"],
        config["hue_thresholds"],
    )
    ok = result["color"] == EXPECTED[i]
    correct += ok
    hue = round(result["hue"]) if result["hue"] is not None else None
    print(
        f"{i}: {result['color']:<6} hue={hue} "
        f"mag={result['magnitude']:.0f} expected={EXPECTED[i]}"
        f" {'OK' if ok else 'MISS'}"
    )
print(f"{correct}/12 correct")
