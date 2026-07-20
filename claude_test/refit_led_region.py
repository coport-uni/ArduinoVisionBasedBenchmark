# Purpose: re-fit the rgb_led region / baseline strategy against the
# T1_CLD_VP_r1 judge frames where the wide region + stale baseline
# misclassified green->none and blue->red.
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.config import load_config
from harness.vision import dominant_color_diff

config = load_config()
trial = Path("results/T1_CLD_VP_r1")
FRAMES = {
    "judge_t1_1_red": "red",
    "judge_t1_2_green": "green",
    "judge_t1_3_blue": "blue",
}

# Pseudo-baseline: per-pixel min across the three colour frames --
# same ambient light, LED colour removed by the min.
stack = np.stack(
    [
        np.asarray(Image.open(trial / f"{n}.jpg").convert("RGB"), dtype=np.float64)
        for n in FRAMES
    ]
)
min_base = Path("claude_test/rgb_burst/edge_min_baseline.jpg")
Image.fromarray(stack.min(axis=0).astype(np.uint8)).save(min_base)

for region_name, region in (
    ("wide-current", config["led_regions"]["rgb_led"]),
    ("tight", [438, 234, 454, 250]),
):
    for base_name, base in (
        ("trial-baseline", trial / "baseline.jpg"),
        ("edge-min", min_base),
    ):
        verdicts = []
        for frame_name, expected in FRAMES.items():
            r = dominant_color_diff(
                trial / f"{frame_name}.jpg",
                base,
                region,
                config["hue_thresholds"],
            )
            verdicts.append(
                f"{expected}->{r['color']}"
                f"(h={r['hue'] and round(r['hue'])},m={r['magnitude']:.0f})"
            )
        print(f"{region_name:13} {base_name:15} {'  '.join(verdicts)}")
