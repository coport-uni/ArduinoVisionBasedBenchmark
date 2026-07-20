"""T2 judge: LED-clock detection -> LED matrix, four stages (FR5).

Task variant (operator decisions 2026-07-20): the board camera watches
an LED desk clock and the agent detects it with YOLOv8 nano (COCO
class "clock"), replacing SPEC's person detection. The clock sits
PERMANENTLY in the board camera's view, so judging is fully automatic
-- no operator m/c marking is required and T2 runs unattended like T1.

Stage 1  events.log contains a clock_detected line
Stage 2  matrix_draw_o within detect_window_s after clock_detected
         (board timestamps corrected by the measured clock skew)
Stage 3  physical: the matrix brightness rises above the trial
         baseline (checked on every judge poll -- with the clock
         always in view, a working pipeline keeps the matrix lit)
Stage 4  physical: the lit state is stable -- lit again on a second
         check at least stability_gap_s after stage 3

The prompt still requires matrix-off when no clock is in view, but
that path goes physically unverified in the automatic flow (the
harness cannot remove the clock). Operator keys remain as an optional
bonus: press c after removing the clock to run the clear-watch, whose
outcome is logged as evidence but not required for success.

t2_latency_s = matrix_draw_o - clock_detected (board-internal, from
the first detection pair; immune to board/host clock skew).
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
        self._clear_thread: threading.Thread | None = None
        self._lit_check_index = 0
        self._first_lit_epoch: float | None = None
        self._stability_gap_s = config["t2"].get("stability_gap_s", 10.0)

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
        # Reaction latency: first detection -> first draw at/after it,
        # board-internal so clock skew cancels out.
        if self.t2_latency_s is None and detections and draws:
            first_detected = min(detections)
            after = [d for d in draws if d >= first_detected]
            if after:
                self.t2_latency_s = after[0] - first_detected

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

    def _check_lit_stages(self) -> None:
        """Stages 3/4, automatic: matrix lit now, and lit stably.

        With the clock permanently in view a working pipeline keeps
        the matrix on, so each judge poll simply measures the
        brightness delta. Stage 3 is the first lit observation;
        stage 4 requires a second lit observation at least
        stability_gap_s later.
        """
        # Only worth capturing once the log stages show a pipeline.
        if self.stages["s1"] is None:
            return
        if self.stages["s3"] is not None and self.stages["s4"] is not None:
            return
        self._lit_check_index += 1
        frame = self._capture(f"lit{self._lit_check_index}")
        if frame is None:
            return
        delta = self._matrix_delta(frame)
        append_line(
            self._log,
            f"{now_iso()} lit check {frame.name}"
            f" delta={delta if delta is None else round(delta, 3)}",
        )
        if delta is None or delta < self._lit_delta:
            return
        now = time.time()
        if self.stages["s3"] is None:
            self.stages["s3"] = now_iso()
            self._first_lit_epoch = now
            append_line(self._log, f"{now_iso()} s3 met (matrix lit)")
        elif (
            self.stages["s4"] is None
            and self._first_lit_epoch is not None
            and now - self._first_lit_epoch >= self._stability_gap_s
        ):
            self.stages["s4"] = now_iso()
            append_line(self._log, f"{now_iso()} s4 met (lit stable)")

    def _run_clear_watch(self, mark_epoch: float) -> None:
        """Optional evidence run: delta back near baseline after the
        operator removes the clock (c key). Logged only -- not part of
        the automatic success criteria."""
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
                    append_line(
                        self._log,
                        f"{now_iso()} clear-watch: matrix returned to"
                        " baseline (off-path evidence)",
                    )
                    return
            time.sleep(BURST_INTERVAL_S)
        append_line(
            self._log,
            f"{now_iso()} clear-watch: matrix did NOT return to baseline",
        )

    # -- runner interface ------------------------------------------

    def handle_key(self, key: str, epoch: float) -> None:
        """Optional operator keys; judging no longer requires them.

        c = clock removed: runs the off-path clear-watch as logged
        evidence. m is accepted and recorded for provenance only.
        """
        if key == "m":
            self.m_mark_epoch = epoch
            append_line(self._log, f"{now_iso()} m mark at {epoch:.3f}")
        elif key == "c" and self._clear_thread is None:
            self.c_mark_epoch = epoch
            append_line(self._log, f"{now_iso()} c mark at {epoch:.3f}")
            self._clear_thread = threading.Thread(
                target=self._run_clear_watch, args=(epoch,), daemon=True
            )
            self._clear_thread.start()

    def poll(self) -> bool:
        self._stage12()
        self._check_lit_stages()
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
