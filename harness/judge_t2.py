"""T2 judge: LED-clock detection -> LED matrix, four stages (FR5).

Task variant (operator decision 2026-07-20): the board camera watches
an LED desk clock and the agent detects it with YOLOv8 nano (COCO
class "clock"), replacing SPEC's person detection. The stage logic is
unchanged; only the trigger event differs.

Stage 1  events.log contains a clock_detected line
Stage 2  matrix_draw_o within detect_window_s after clock_detected
         (board timestamps corrected by the measured clock skew)
Stage 3  operator presses m (clock placed in view) -> 10 s capture
         burst shows the matrix lit ratio rising above baseline
Stage 4  operator presses c (clock removed) -> lit ratio returns to
         baseline within clear_window_s

t2_latency_s = (matrix_draw_o board time + skew correction) - m mark.
"""

import re
import threading
import time
from datetime import datetime
from pathlib import Path

from harness.util import append_line, now_iso
from harness.vision import brightness_delta, capture_frame

# Tolerant event-line pattern: ISO timestamp then the event name
# somewhere on the line (prompt fixes the contract as ISO8601<TAB>event).
_EVENT_RE = re.compile(
    r"(?P<ts>\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?"
    r"(?:[+-]\d{2}:?\d{2}|Z)?).*?(?P<event>clock_detected|matrix_draw_o)"
)

BURST_DURATION_S = 10.0
BURST_INTERVAL_S = 2.0


def parse_event_log(text: str) -> list[tuple[float, str]]:
    """(epoch_seconds, event_name) rows from an events.log body."""
    events = []
    for line in text.splitlines():
        match = _EVENT_RE.search(line)
        if not match:
            continue
        stamp = match.group("ts").replace(" ", "T")
        try:
            parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.astimezone()
        events.append((parsed.timestamp(), match.group("event")))
    return events


class T2Judge:
    """Stage evaluator driven by runner poll() plus m/c key marks."""

    def __init__(
        self,
        board,
        config,
        trial_dir: Path,
        clock_skew_s: float = 0.0,
        baseline_frame: Path | None = None,
    ):
        self._board = board
        self._config = config
        self._trial_dir = trial_dir
        self._skew = clock_skew_s
        self.stages: dict[str, str | None] = {
            "s1": None,
            "s2": None,
            "s3": None,
            "s4": None,
        }
        self.t2_latency_s: float | None = None
        self.m_mark_epoch: float | None = None
        self.c_mark_epoch: float | None = None
        self._log = trial_dir / "judge.log"
        self._region = config["led_regions"]["matrix"]
        self._thresholds = config["hue_thresholds"]
        self._lit_delta = config["t2"]["matrix_lit_delta"]
        self._baseline_tol = config["t2"]["matrix_baseline_tolerance"]
        # The white matrix housing defeats absolute lit ratios; all
        # stage 3/4 measurements are brightness deltas against this
        # trial's baseline frame (captured post-reset, matrix dark).
        self._baseline_frame = (
            baseline_frame
            if baseline_frame is not None and baseline_frame.exists()
            else None
        )
        self._burst_thread: threading.Thread | None = None
        self._clear_thread: threading.Thread | None = None

    # -- log stages ------------------------------------------------

    def _read_events(self) -> list[tuple[float, str]]:
        body = self._board.read_file(self._config["t2"]["event_log_on_board"])
        if body is None:
            return []
        # Correct board clock to host clock.
        return [(ts - self._skew, name) for ts, name in parse_event_log(body)]

    def _stage12(self) -> None:
        events = self._read_events()
        detections = [ts for ts, name in events if name == "clock_detected"]
        draws = [ts for ts, name in events if name == "matrix_draw_o"]
        if detections and self.stages["s1"] is None:
            self.stages["s1"] = now_iso()
            append_line(self._log, f"{now_iso()} s1 met (clock_detected)")
        if self.stages["s2"] is None:
            window = self._config["t2"]["detect_window_s"]
            for detected_at in detections:
                if any(0 <= draw - detected_at <= window for draw in draws):
                    self.stages["s2"] = now_iso()
                    append_line(
                        self._log,
                        f"{now_iso()} s2 met (draw within {window}s)",
                    )
                    break
        # Reaction latency: first matrix_draw_o at/after the m mark.
        if self.t2_latency_s is None and self.m_mark_epoch is not None and draws:
            after = [d for d in draws if d >= self.m_mark_epoch - 1.0]
            if after:
                self.t2_latency_s = after[0] - self.m_mark_epoch

    # -- physical stages -------------------------------------------

    def _capture(self, label: str) -> Path | None:
        path = self._trial_dir / f"judge_t2_{label}.jpg"
        try:
            capture_frame(
                self._config,
                path,
                lock_dir=self._config.results_dir,
                lock_timeout_s=20.0,
            )
            return path
        except Exception as exc:
            append_line(self._log, f"{now_iso()} capture failed ({label}): {exc}")
            return None

    def _matrix_delta(self, frame: Path) -> float | None:
        if self._baseline_frame is None:
            return None
        return brightness_delta(frame, self._baseline_frame, self._region)

    def _run_burst(self, mark_epoch: float) -> None:
        """Stage 3: 10 s / 2 s burst; brightness delta must rise."""
        deadline = mark_epoch + BURST_DURATION_S
        index = 0
        while time.time() < deadline:
            index += 1
            frame = self._capture(f"m{index}")
            if frame is not None:
                delta = self._matrix_delta(frame)
                append_line(
                    self._log,
                    f"{now_iso()} burst frame {frame.name}"
                    f" delta={delta if delta is None else round(delta, 3)}",
                )
                if delta is not None and delta >= self._lit_delta:
                    if self.stages["s3"] is None:
                        self.stages["s3"] = now_iso()
                        append_line(self._log, f"{now_iso()} s3 met")
                    return
            time.sleep(BURST_INTERVAL_S)

    def _run_clear_watch(self, mark_epoch: float) -> None:
        """Stage 4: delta back near baseline within clear_window_s."""
        deadline = mark_epoch + self._config["t2"]["clear_window_s"]
        index = 0
        while time.time() < deadline:
            index += 1
            frame = self._capture(f"c{index}")
            if frame is not None:
                delta = self._matrix_delta(frame)
                append_line(
                    self._log,
                    f"{now_iso()} clear frame {frame.name}"
                    f" delta={delta if delta is None else round(delta, 3)}",
                )
                if delta is not None and delta <= self._baseline_tol:
                    if self.stages["s4"] is None:
                        self.stages["s4"] = now_iso()
                        append_line(self._log, f"{now_iso()} s4 met")
                    return
            time.sleep(BURST_INTERVAL_S)

    # -- runner interface ------------------------------------------

    def handle_key(self, key: str, epoch: float) -> None:
        """Operator marks: m = person staged, c = person left (FR5)."""
        if key == "m" and self._burst_thread is None:
            self.m_mark_epoch = epoch
            append_line(self._log, f"{now_iso()} m mark at {epoch:.3f}")
            self._burst_thread = threading.Thread(
                target=self._run_burst, args=(epoch,), daemon=True
            )
            self._burst_thread.start()
        elif key == "c" and self._clear_thread is None:
            self.c_mark_epoch = epoch
            append_line(self._log, f"{now_iso()} c mark at {epoch:.3f}")
            self._clear_thread = threading.Thread(
                target=self._run_clear_watch, args=(epoch,), daemon=True
            )
            self._clear_thread.start()

    def poll(self) -> bool:
        self._stage12()
        return all(self.stages.values())

    def shutdown(self) -> None:
        pass

    def summary(self) -> dict:
        return {
            "stages": dict(self.stages),
            "t2_latency_s": self.t2_latency_s,
            "m_mark": self.m_mark_epoch,
            "c_mark": self.c_mark_epoch,
        }
