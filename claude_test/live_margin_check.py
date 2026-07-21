# Purpose: measure per-colour expected-channel margin against the
# free-running qtest_rgb cycle sketch at the current camera position,
# using the config led_regions. Confirms optical separation before a
# production run.
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.config import load_config
from harness.vision import (
    capture_frame,
    dominant_color_diff,
    expected_channel_margin,
    region_brightness,
)

config = load_config()
region = config["led_regions"]["rgb_led"]
out = Path("claude_test/live_burst")
out.mkdir(exist_ok=True)

N = 16
frames = []
for i in range(N):
    p = out / f"m_{i}.jpg"
    capture_frame(config, p, lock_dir=config.results_dir)
    frames.append(p)
    time.sleep(1.0)

# Pseudo-off baseline: per-pixel min across the burst (LED colour
# removed; the dark plateau of the cycle).
stack = np.stack(
    [np.asarray(Image.open(f).convert("RGB"), dtype=np.float64) for f in frames]
)
base_path = out / "pseudo_off.jpg"
Image.fromarray(stack.min(axis=0).astype(np.uint8)).save(base_path)
off_level = region_brightness(base_path, region)
print(f"region {region}  pseudo-off region brightness {off_level:.1f}")

for i, f in enumerate(frames):
    result = dominant_color_diff(f, base_path, region, config["hue_thresholds"])
    rise = region_brightness(f, region) - off_level
    margins = {
        c: round(
            expected_channel_margin(
                f, base_path, region, c, config["hue_thresholds"]
            ),
            1,
        )
        for c in ("red", "green", "blue")
    }
    print(
        f"{i:2d} rise={rise:+5.1f} verdict={result['color']:<5}"
        f" margins R{margins['red']:+.0f} G{margins['green']:+.0f}"
        f" B{margins['blue']:+.0f}"
    )
