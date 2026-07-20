"""Host-camera capture and LED hue judgment.

The dshow device admits a single opener, so every capture -- the
judge's and the agent's snap.bat -- goes through a cross-process lock
file. Judge captures take priority simply by using a longer retry
budget than snap.

Hue analysis is hand-rolled RGB->HSV over Pillow + numpy because SPEC 2
allows only those two packages beyond the standard library.
"""

import os
import subprocess
import time
from pathlib import Path

import numpy as np
from PIL import Image

from harness.errors import CaptureError

LOCK_STALE_S = 30.0


class CameraLock:
    """Cross-process exclusive lock around the single dshow camera."""

    def __init__(self, lock_path: Path, timeout_s: float = 15.0):
        self._path = lock_path
        self._timeout = timeout_s
        self._acquired = False

    def __enter__(self):
        deadline = time.monotonic() + self._timeout
        while True:
            try:
                fd = os.open(self._path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
                self._acquired = True
                return self
            except FileExistsError:
                # Break stale locks left by a crashed holder.
                try:
                    age = time.time() - self._path.stat().st_mtime
                    if age > LOCK_STALE_S:
                        self._path.unlink(missing_ok=True)
                        continue
                except OSError:
                    continue
                if time.monotonic() > deadline:
                    raise CaptureError(
                        f"camera lock busy for {self._timeout}s: {self._path}"
                    ) from None
                time.sleep(0.25)

    def __exit__(self, *exc_info):
        if self._acquired:
            self._path.unlink(missing_ok=True)
        return False


def capture_frame(
    config,
    out_path: Path,
    lock_dir: Path,
    retries: int = 2,
    lock_timeout_s: float = 15.0,
) -> Path:
    """Capture one frame from the host camera to *out_path*.

    @param config          Harness config (ffmpeg path, device name).
    @param out_path        Destination JPEG path.
    @param lock_dir        Directory holding the shared .camera.lock.
    @param retries         ffmpeg attempts before giving up.
    @param lock_timeout_s  How long to wait for the camera lock.
    @return                out_path on success.
    """
    lock_dir.mkdir(parents=True, exist_ok=True)
    device = config["camera_device_name"]
    cmd = [
        config["ffmpeg_path"],
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "dshow",
        "-i",
        f"video={device}",
        "-frames:v",
        "1",
        "-y",
        str(out_path),
    ]
    last_error = ""
    with CameraLock(lock_dir / ".camera.lock", timeout_s=lock_timeout_s):
        for _ in range(retries + 1):
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
                stdin=subprocess.DEVNULL,
            )
            if proc.returncode == 0 and out_path.exists():
                return out_path
            last_error = (proc.stderr or "").strip()
            time.sleep(0.5)
    raise CaptureError(f"ffmpeg capture failed: {last_error}")


def _rgb_to_hsv(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Vectorized RGB(0-255) -> (hue degrees, saturation, value)."""
    arr = rgb.astype(np.float64) / 255.0
    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
    maxc = np.max(arr, axis=-1)
    minc = np.min(arr, axis=-1)
    delta = maxc - minc
    hue = np.zeros_like(maxc)
    mask = delta > 0
    rm = mask & (maxc == r)
    gm = mask & (maxc == g) & ~rm
    bm = mask & (maxc == b) & ~rm & ~gm
    hue[rm] = (60.0 * ((g[rm] - b[rm]) / delta[rm])) % 360.0
    hue[gm] = 60.0 * ((b[gm] - r[gm]) / delta[gm]) + 120.0
    hue[bm] = 60.0 * ((r[bm] - g[bm]) / delta[bm]) + 240.0
    saturation = np.where(maxc > 0, delta / np.where(maxc > 0, maxc, 1), 0.0)
    return hue, saturation, maxc


def _hue_in_range(hue: np.ndarray, low: float, high: float) -> np.ndarray:
    """Boolean mask for hue within [low, high], wrapping at 360."""
    if low <= high:
        return (hue >= low) & (hue <= high)
    return (hue >= low) | (hue <= high)  # wraparound band such as red


def dominant_color(image_path: Path, region: list[int], thresholds: dict) -> dict:
    """Classify the dominant hue inside *region* of an image.

    Pixels below the saturation/value floors are excluded (SPEC FR4-4),
    so a dark or washed-out region classifies as "none".

    @param image_path  Captured frame.
    @param region      [x1, y1, x2, y2] in pixels.
    @param thresholds  config hue_thresholds mapping.
    @return            {color, fraction, counted_pixels} where color is
                       red/green/blue/none.
    """
    with Image.open(image_path) as img:
        rgb = np.asarray(img.convert("RGB"))
    x1, y1, x2, y2 = region
    crop = rgb[y1:y2, x1:x2]
    if crop.size == 0:
        return {"color": "none", "fraction": 0.0, "counted_pixels": 0}
    hue, saturation, value = _rgb_to_hsv(crop)
    valid = (saturation >= thresholds["min_saturation"]) & (
        value >= thresholds["min_value"]
    )
    counted = int(valid.sum())
    if counted == 0:
        return {"color": "none", "fraction": 0.0, "counted_pixels": 0}
    best_color, best_fraction = "none", 0.0
    for color in ("red", "green", "blue"):
        low, high = thresholds[color]
        fraction = float((_hue_in_range(hue, low, high) & valid).sum() / counted)
        if fraction > best_fraction:
            best_color, best_fraction = color, fraction
    if best_fraction < 0.5:
        return {
            "color": "none",
            "fraction": best_fraction,
            "counted_pixels": counted,
        }
    return {
        "color": best_color,
        "fraction": best_fraction,
        "counted_pixels": counted,
    }


def lit_ratio(image_path: Path, region: list[int], thresholds: dict) -> float:
    """Fraction of region pixels that are lit (T2 matrix judgment).

    A pixel counts as lit when its value clears the floor; the matrix
    LEDs are white-ish so saturation is not required.
    """
    with Image.open(image_path) as img:
        rgb = np.asarray(img.convert("RGB"))
    x1, y1, x2, y2 = region
    crop = rgb[y1:y2, x1:x2]
    if crop.size == 0:
        return 0.0
    _, _, value = _rgb_to_hsv(crop)
    return float((value >= thresholds["min_value"]).mean())


def frame_resolution(image_path: Path) -> tuple[int, int]:
    """Return (width, height) of a captured frame."""
    with Image.open(image_path) as img:
        return img.size


def validate_regions(config, image_path: Path) -> list[str]:
    """Return error strings for regions outside the frame (FR1-6)."""
    width, height = frame_resolution(image_path)
    problems = []
    for name, (x1, y1, x2, y2) in config["led_regions"].items():
        if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
            problems.append(
                f"led_regions.{name}=[{x1},{y1},{x2},{y2}] exceeds"
                f" frame {width}x{height}"
            )
    return problems
