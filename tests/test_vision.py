"""Hue classification tests over synthetic fixtures (Phase 3 logic).

Fixtures are generated with Pillow: solid colour patches at a known
region, plus dim / desaturated negatives, including the wraparound
red band (345-15 degrees).
"""

import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.vision import dominant_color, lit_ratio

THRESHOLDS = {
    "red": [345, 15],
    "green": [90, 150],
    "blue": [200, 260],
    "min_saturation": 0.35,
    "min_value": 0.25,
}
REGION = [10, 10, 50, 50]


def make_frame(patch_rgb, background=(20, 20, 20)) -> Path:
    frame = np.full((100, 100, 3), background, dtype=np.uint8)
    x1, y1, x2, y2 = REGION
    frame[y1:y2, x1:x2] = patch_rgb
    path = Path(tempfile.mkdtemp()) / "frame.png"
    Image.fromarray(frame).save(path)
    return path


class DominantColorTest(unittest.TestCase):
    def test_pure_primaries(self):
        for rgb, expected in (
            ((220, 30, 30), "red"),
            ((30, 220, 30), "green"),
            ((30, 60, 220), "blue"),
        ):
            result = dominant_color(make_frame(rgb), REGION, THRESHOLDS)
            self.assertEqual(result["color"], expected, rgb)

    def test_wraparound_red_below_360(self):
        # Hue ~350 degrees: red via the wraparound band.
        result = dominant_color(make_frame((220, 20, 50)), REGION, THRESHOLDS)
        self.assertEqual(result["color"], "red")

    def test_dim_pixel_rejected(self):
        result = dominant_color(make_frame((40, 5, 5)), REGION, THRESHOLDS)
        self.assertEqual(result["color"], "none")

    def test_desaturated_rejected(self):
        result = dominant_color(make_frame((200, 190, 195)), REGION, THRESHOLDS)
        self.assertEqual(result["color"], "none")

    def test_off_led_dark_region(self):
        result = dominant_color(make_frame((20, 20, 20)), REGION, THRESHOLDS)
        self.assertEqual(result["color"], "none")


class LitRatioTest(unittest.TestCase):
    def test_lit_versus_dark(self):
        lit = lit_ratio(make_frame((240, 240, 240)), REGION, THRESHOLDS)
        dark = lit_ratio(make_frame((10, 10, 10)), REGION, THRESHOLDS)
        self.assertGreater(lit, 0.9)
        self.assertLess(dark, 0.05)


if __name__ == "__main__":
    unittest.main()
