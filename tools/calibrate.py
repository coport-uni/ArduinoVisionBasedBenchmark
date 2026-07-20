"""Camera calibration: locate LED regions in a live frame (Phase 3).

Captures a frame, then either reports hue statistics for the currently
configured regions (--verify) or helps the operator pick new
coordinates by probing a grid of candidate windows for saturated
pixels (--suggest). Output is pasteable config JSON; this tool never
edits config.json itself.

Usage:
    python tools/calibrate.py --capture out.jpg
    python tools/calibrate.py --verify [--frame out.jpg]
    python tools/calibrate.py --suggest [--frame out.jpg]
"""

import argparse
import json
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.config import load_config  # noqa: E402
from harness.vision import (  # noqa: E402
    _rgb_to_hsv,
    capture_frame,
    dominant_color,
    frame_resolution,
    lit_ratio,
)

WINDOW = 40  # probe window size in pixels
STRIDE = 20


def _load_frame(config, frame_arg: str | None) -> Path:
    if frame_arg:
        return Path(frame_arg)
    out = Path(tempfile.mkdtemp(prefix="calibrate_")) / "frame.jpg"
    capture_frame(config, out, lock_dir=config.results_dir)
    print(f"captured {out}")
    return out


def verify(config, frame: Path) -> None:
    print(f"frame resolution: {frame_resolution(frame)}")
    for name, region in config["led_regions"].items():
        color = dominant_color(frame, region, config["hue_thresholds"])
        ratio = lit_ratio(frame, region, config["hue_thresholds"])
        print(
            f"{name} {region}: dominant={color['color']}"
            f" fraction={color['fraction']:.2f}"
            f" counted={color['counted_pixels']} lit_ratio={ratio:.3f}"
        )


def suggest(config, frame: Path) -> None:
    """Rank probe windows by saturated-bright pixel share."""
    with Image.open(frame) as img:
        rgb = np.asarray(img.convert("RGB"))
    hue, saturation, value = _rgb_to_hsv(rgb)
    thresholds = config["hue_thresholds"]
    active = (saturation >= thresholds["min_saturation"]) & (
        value >= thresholds["min_value"]
    )
    height, width = active.shape
    scored = []
    for y in range(0, height - WINDOW, STRIDE):
        for x in range(0, width - WINDOW, STRIDE):
            share = float(active[y : y + WINDOW, x : x + WINDOW].mean())
            if share > 0.05:
                scored.append((share, x, y))
    scored.sort(reverse=True)
    print("top saturated windows (share, [x1, y1, x2, y2]):")
    for share, x, y in scored[:10]:
        print(f"  {share:.2f}  [{x}, {y}, {x + WINDOW}, {y + WINDOW}]")
    if scored:
        share, x, y = scored[0]
        print("\npasteable config snippet:")
        print(
            json.dumps(
                {"led_regions": {"rgb_led": [x, y, x + WINDOW, y + WINDOW]}},
                indent=2,
            )
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", help="capture a frame to this path")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--suggest", action="store_true")
    parser.add_argument("--frame", help="reuse an existing frame")
    args = parser.parse_args()

    config = load_config()
    if args.capture:
        out = Path(args.capture)
        capture_frame(config, out, lock_dir=config.results_dir)
        print(f"captured {out} at {frame_resolution(out)}")
        return 0

    frame = _load_frame(config, args.frame)
    if args.verify:
        verify(config, frame)
    if args.suggest:
        suggest(config, frame)
    if not (args.verify or args.suggest):
        verify(config, frame)
    return 0


if __name__ == "__main__":
    sys.exit(main())
