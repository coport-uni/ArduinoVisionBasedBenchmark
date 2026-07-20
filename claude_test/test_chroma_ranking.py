# Purpose: test chroma-ranked pixel selection for the diff classifier
# against the replay frames where sum-ranked selection grabs only the
# blown-out white core (green/blue -> achromatic).
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.config import load_config
from harness.vision import _hue_in_range, _rgb_to_hsv

config = load_config()
x1, y1, x2, y2 = config["led_regions"]["rgb_led"]
thresholds = config["hue_thresholds"]
d = Path(sys.argv[1])

base = np.asarray(Image.open(d / "replay_off.jpg").convert("RGB"), dtype=np.float64)[
    y1:y2, x1:x2
]


def classify(diff_flat: np.ndarray, top_k: int = 25) -> tuple[str, float, float]:
    """Rank by per-pixel chroma of the positive diff, then classify."""
    positive = np.clip(diff_flat, 0, None)
    chroma_px = positive.max(axis=-1) - positive.min(axis=-1)
    # Require some magnitude so pure noise chroma does not rank.
    magnitude_px = positive.max(axis=-1)
    score = np.where(magnitude_px >= 15, chroma_px, 0.0)
    order = np.argsort(score)
    top = positive[order[-top_k:]].mean(axis=0)
    magnitude = float(top.max())
    chroma = float(top.max() - top.min())
    if magnitude < thresholds.get("diff_min_delta", 25):
        return "none(mag)", magnitude, chroma
    if chroma < thresholds.get("diff_min_chroma", 15):
        return "none(chroma)", magnitude, chroma
    hue, _, _ = _rgb_to_hsv(np.clip(top, 0, 255)[None, None, :])
    hue_value = float(hue[0, 0])
    for color in ("red", "green", "blue"):
        low, high = thresholds[color]
        if bool(_hue_in_range(np.array([hue_value]), low, high)[0]):
            return f"{color}(h={hue_value:.0f})", magnitude, chroma
    return f"none(h={hue_value:.0f})", magnitude, chroma


for name in ("red", "green", "blue"):
    frame = np.asarray(
        Image.open(d / f"replay_{name}.jpg").convert("RGB"), dtype=np.float64
    )[y1:y2, x1:x2]
    diff = (frame - base).reshape(-1, 3)
    verdict, mag, chroma = classify(diff)
    print(f"{name}: {verdict} mag={mag:.0f} chroma={chroma:.0f}")
