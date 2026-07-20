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


def dominant_color_diff(
    image_path: Path,
    baseline_path: Path,
    region: list[int],
    thresholds: dict,
) -> dict:
    """Classify the LED colour from the difference against a baseline.

    Built for tiny on-board LEDs whose core blows out to white: the
    (frame - baseline) difference of the brightest pixels keeps the
    emitted colour even when absolute pixels are desaturated. The
    mean difference is classified by hue band; magnitudes below
    diff_min_delta count as off.

    @param image_path     Frame with the LED in an unknown state.
    @param baseline_path  Frame of the same scene with the LED off.
    @param region         [x1, y1, x2, y2] around the LED.
    @param thresholds     config hue_thresholds mapping.
    @return               {color, hue, magnitude} with color in
                          red/green/blue/none.
    """
    with Image.open(image_path) as img:
        frame = np.asarray(img.convert("RGB"), dtype=np.float64)
    with Image.open(baseline_path) as img:
        base = np.asarray(img.convert("RGB"), dtype=np.float64)
    x1, y1, x2, y2 = region
    diff = (frame[y1:y2, x1:x2] - base[y1:y2, x1:x2]).reshape(-1, 3)
    if diff.size == 0:
        return {"color": "none", "hue": None, "magnitude": 0.0}
    top_k = int(thresholds.get("diff_top_pixels", 25))
    top = diff[np.argsort(diff.sum(axis=-1))[-top_k:]].mean(axis=0)
    magnitude = float(top.max())
    if magnitude < thresholds.get("diff_min_delta", 25):
        return {"color": "none", "hue": None, "magnitude": magnitude}
    # Achromatic guard: exposure drift lifts all channels equally and
    # would otherwise land on an arbitrary hue. A real LED colour has
    # clearly unequal channels in the difference.
    chroma = float(top.max() - top.min())
    if chroma < thresholds.get("diff_min_chroma", 15):
        return {"color": "none", "hue": None, "magnitude": magnitude}
    hue, _, _ = _rgb_to_hsv(np.clip(top, 0, 255)[None, None, :])
    hue_value = float(hue[0, 0])
    for color in ("red", "green", "blue"):
        low, high = thresholds[color]
        if bool(_hue_in_range(np.array([hue_value]), low, high)[0]):
            return {
                "color": color,
                "hue": hue_value,
                "magnitude": magnitude,
            }
    return {"color": "none", "hue": hue_value, "magnitude": magnitude}


def expected_channel_margin(
    image_path: Path,
    baseline_path: Path,
    region: list[int],
    expected: str,
    thresholds: dict,
) -> float:
    """How strongly the expected colour channel leads the others.

    Over the brightest top-K diff pixels, returns
    mean(expected channel) - mean(other two channels). A correctly
    coloured LED yields a clearly positive margin even when bright
    ambient light thins the fringe chroma below the achromatic guard;
    a white (miswired/misdriven) LED stays near zero or negative.
    """
    channel = {"red": 0, "green": 1, "blue": 2}[expected]
    with Image.open(image_path) as img:
        frame = np.asarray(img.convert("RGB"), dtype=np.float64)
    with Image.open(baseline_path) as img:
        base = np.asarray(img.convert("RGB"), dtype=np.float64)
    x1, y1, x2, y2 = region
    diff = (frame[y1:y2, x1:x2] - base[y1:y2, x1:x2]).reshape(-1, 3)
    if diff.size == 0:
        return 0.0
    top_k = int(thresholds.get("diff_top_pixels", 25))
    top = diff[np.argsort(diff.sum(axis=-1))[-top_k:]].mean(axis=0)
    others = [top[i] for i in range(3) if i != channel]
    return float(top[channel] - (others[0] + others[1]) / 2.0)


def lit_ratio(image_path: Path, region: list[int], thresholds: dict) -> float:
    """Fraction of region pixels that are lit (absolute variant).

    A pixel counts as lit when its value clears the floor. Note the
    UNO Q matrix housing is white, so this absolute metric cannot
    tell a dark matrix from a lit one in daylight -- the judge uses
    brightness_delta against the trial baseline instead.
    """
    with Image.open(image_path) as img:
        rgb = np.asarray(img.convert("RGB"))
    x1, y1, x2, y2 = region
    crop = rgb[y1:y2, x1:x2]
    if crop.size == 0:
        return 0.0
    _, _, value = _rgb_to_hsv(crop)
    return float((value >= thresholds["min_value"]).mean())


def brightness_delta(image_path: Path, baseline_path: Path, region: list[int]) -> float:
    """Mean per-pixel brightness increase over a baseline, 0..1.

    Robust matrix-lit metric for the white-housing 8x13 matrix: lit
    blue LEDs add channel energy on top of whatever ambient the
    housing reflects, so the mean (frame - baseline) sum over the
    region rises sharply when the matrix is on.
    """
    with Image.open(image_path) as img:
        frame = np.asarray(img.convert("RGB"), dtype=np.float64)
    with Image.open(baseline_path) as img:
        base = np.asarray(img.convert("RGB"), dtype=np.float64)
    x1, y1, x2, y2 = region
    diff = frame[y1:y2, x1:x2] - base[y1:y2, x1:x2]
    if diff.size == 0:
        return 0.0
    return float(np.clip(diff.sum(axis=-1), 0, None).mean() / 765.0)


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
