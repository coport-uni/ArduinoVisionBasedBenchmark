"""T1 judge: Home Assistant + RGB LED, four stages (FR4).

Success requires all four stages. Judging relies only on board state,
the HA API (queried board-side), and host-camera frames -- never on
agent stdout (NFR1).

Stage 1  port 8123 answers 200/302/401/405 (board-internal curl)
Stage 2  token file exists and /api/states lists an RGB-capable light
Stage 3  polled states show red -> green -> blue -> off in order
Stage 4  a frame captured at each colour edge shows that hue on the LED
"""

import json
import threading
import time
from pathlib import Path

from harness.util import append_line, now_iso
from harness.vision import capture_frame, dominant_color_diff

ACCEPTED_HTTP = {"200", "302", "401", "405"}
# HA only exposes rgb_color while a light is on, so capability is also
# accepted via supported_color_modes (confirm against the real HA).
RGB_COLOR_MODES = {"rgb", "rgbw", "rgbww", "hs", "xy"}

# Colour classification of an rgb_color triple: dominant channel must
# lead each other channel by this factor.
DOMINANCE = 2.0

EXPECTED_SEQUENCE = ["red", "green", "blue", "off"]


def classify_rgb(rgb: list) -> str | None:
    """Map an HA rgb_color triple to red/green/blue, else None."""
    if not rgb or len(rgb) != 3:
        return None
    r, g, b = (float(v) for v in rgb)
    if r > DOMINANCE * g and r > DOMINANCE * b:
        return "red"
    if g > DOMINANCE * r and g > DOMINANCE * b:
        return "green"
    if b > DOMINANCE * r and b > DOMINANCE * g:
        return "blue"
    return None


class HaStatePoller(threading.Thread):
    """1 Hz light-state poller, started once stage 2 is met (FR4-3).

    Records (host_time, state, colour) transitions and fires an
    edge-triggered camera capture on every colour change so stage 4
    frames land inside the 3 s colour holds.
    """

    def __init__(self, board, config, entity_id, token, trial_dir: Path):
        super().__init__(daemon=True)
        self._board = board
        self._config = config
        self._entity = entity_id
        self._token = token
        self._trial_dir = trial_dir
        self._stop_event = threading.Event()
        self._csv_path = trial_dir / "ha_states.csv"
        self.observations: list[dict] = []
        self._obs_lock = threading.Lock()
        self._last_key = None
        self._capture_index = 0

    def stop(self) -> None:
        self._stop_event.set()

    def _poll_state(self) -> tuple[str, str | None] | None:
        port = self._config["ha"]["port"]
        result = self._board.shell(
            f"curl -s --max-time 5 -H 'Authorization: Bearer {self._token}'"
            f" http://127.0.0.1:{port}/api/states/{self._entity}",
            timeout=15,
        )
        if not result.ok:
            return None
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            return None
        state = payload.get("state", "unknown")
        colour = classify_rgb((payload.get("attributes") or {}).get("rgb_color"))
        return state, colour

    def _capture_edge(self, label: str) -> str | None:
        self._capture_index += 1
        frame = self._trial_dir / f"judge_t1_{self._capture_index}_{label}.jpg"
        try:
            capture_frame(
                self._config,
                frame,
                lock_dir=self._config.results_dir,
                lock_timeout_s=20.0,  # judge outlasts snap contention
            )
            return frame.name
        except Exception as exc:  # capture failure must not kill polling
            append_line(
                self._trial_dir / "judge.log",
                f"{now_iso()} edge capture failed ({label}): {exc}",
            )
            return None

    def run(self) -> None:
        append_line(self._csv_path, "timestamp,state,color,edge,frame")
        while not self._stop_event.is_set():
            started = time.monotonic()
            polled = self._poll_state()
            if polled is not None:
                state, colour = polled
                key = "off" if state == "off" else (colour or state)
                edge = key != self._last_key
                frame_name = None
                if edge and (colour in ("red", "green", "blue")):
                    frame_name = self._capture_edge(colour)
                elif edge and key == "off" and self._last_key is not None:
                    # Off edge after colours: the freshest possible
                    # LED-dark baseline for stage 4 (same ambient
                    # light as the colour frames seconds earlier).
                    frame_name = self._capture_edge("off")
                with self._obs_lock:
                    self.observations.append(
                        {
                            "time": now_iso(),
                            "epoch": time.time(),
                            "state": state,
                            "color": colour,
                            "edge": edge,
                            "frame": frame_name,
                        }
                    )
                append_line(
                    self._csv_path,
                    f"{now_iso()},{state},{colour or ''},{edge},{frame_name or ''}",
                )
                self._last_key = key
            elapsed = time.monotonic() - started
            self._stop_event.wait(max(0.0, 1.0 - elapsed))

    def observations_snapshot(self) -> list[dict]:
        with self._obs_lock:
            return list(self.observations)


class T1Judge:
    """Stage evaluator; call poll() from the runner loop."""

    def __init__(
        self,
        board,
        config,
        trial_dir: Path,
        baseline_frame: Path | None = None,
    ):
        self._board = board
        self._config = config
        self._trial_dir = trial_dir
        self._baseline_frame = baseline_frame
        self.stages: dict[str, str | None] = {
            "s1": None,
            "s2": None,
            "s3": None,
            "s4": None,
        }
        self.entity_id: str | None = None
        self._token: str | None = None
        self._poller: HaStatePoller | None = None
        self._log = trial_dir / "judge.log"

    # -- stages ----------------------------------------------------

    def _stage1(self) -> bool:
        result = self._board.curl_local(self._config["ha"]["port"])
        code = result.stdout.strip()
        if result.ok and code in ACCEPTED_HTTP:
            self.stages["s1"] = now_iso()
            append_line(self._log, f"{now_iso()} s1 met (HTTP {code})")
            return True
        return False

    def _stage2(self) -> bool:
        token_path = self._config["ha"]["token_path_on_board"]
        token = self._board.read_file(token_path)
        if token is None or not token.strip():
            return False  # token file missing -> stage unmet (FR4-2)
        token = token.strip()
        port = self._config["ha"]["port"]
        result = self._board.shell(
            f"curl -s --max-time 10 -H 'Authorization: Bearer {token}'"
            f" http://127.0.0.1:{port}/api/states",
            timeout=20,
        )
        if not result.ok:
            return False
        try:
            states = json.loads(result.stdout)
        except json.JSONDecodeError:
            return False
        hint = self._config["ha"]["light_entity_hint"]
        for entity in states if isinstance(states, list) else []:
            entity_id = entity.get("entity_id", "")
            if not entity_id.startswith(hint):
                continue
            attributes = entity.get("attributes") or {}
            modes = set(attributes.get("supported_color_modes") or [])
            if "rgb_color" in attributes or (modes & RGB_COLOR_MODES):
                self.entity_id = entity_id
                self._token = token
                self.stages["s2"] = now_iso()
                append_line(self._log, f"{now_iso()} s2 met (entity {entity_id})")
                self._poller = HaStatePoller(
                    self._board,
                    self._config,
                    entity_id,
                    token,
                    self._trial_dir,
                )
                self._poller.start()
                return True
        return False

    def _observed_sequence(self) -> list[dict]:
        """Colour/off edge observations in order, deduplicated."""
        if self._poller is None:
            return []
        sequence = []
        last = None
        for obs in self._poller.observations_snapshot():
            key = "off" if obs["state"] == "off" else (obs["color"] or None)
            if key in ("red", "green", "blue", "off") and key != last:
                sequence.append({**obs, "key": key})
                last = key
        return sequence

    def _stage3(self) -> bool:
        sequence = [o["key"] for o in self._observed_sequence()]
        # red, green, blue then off must appear as a subsequence.
        position = 0
        for key in sequence:
            if key == EXPECTED_SEQUENCE[position]:
                position += 1
                if position == len(EXPECTED_SEQUENCE):
                    self.stages["s3"] = now_iso()
                    append_line(
                        self._log,
                        f"{now_iso()} s3 met (sequence {sequence})",
                    )
                    return True
        return False

    def _stage4(self) -> bool:
        """Each colour edge frame must show the matching physical hue.

        Uses the baseline-differential classifier: the on-board LED3
        blows out to near-white, so absolute hue classification fails
        while the (frame - baseline) difference keeps the colour.
        """
        observed = self._observed_sequence()
        # Prefer the off-edge frame captured right after the demo as
        # the baseline: same ambient light as the colour frames. The
        # trial-start baseline drifts (lighting changes over minutes)
        # and can overwhelm the small LED difference.
        baseline = self._baseline_frame
        for obs in reversed(observed):
            if obs["key"] == "off" and obs.get("frame"):
                baseline = self._trial_dir / obs["frame"]
                break
        if baseline is None or not baseline.exists():
            append_line(self._log, f"{now_iso()} s4 blocked: no baseline")
            return False
        edges = [o for o in observed if o["key"] in ("red", "green", "blue")]
        if len(edges) < 3:
            return False
        verdicts = {}
        for obs in edges:
            if obs.get("frame") is None:
                return False
            frame = self._trial_dir / obs["frame"]
            result = dominant_color_diff(
                frame,
                baseline,
                self._config["led_regions"]["rgb_led"],
                self._config["hue_thresholds"],
            )
            verdicts[obs["key"]] = result["color"]
        if all(verdicts.get(c) == c for c in ("red", "green", "blue")):
            self.stages["s4"] = now_iso()
            append_line(self._log, f"{now_iso()} s4 met ({verdicts})")
            return True
        append_line(self._log, f"{now_iso()} s4 mismatch ({verdicts})")
        return False

    # -- driver ----------------------------------------------------

    def poll(self) -> bool:
        """Advance whichever stages are still unmet; True when all met."""
        if self.stages["s1"] is None and not self._stage1():
            return False
        if self.stages["s2"] is None and not self._stage2():
            return False
        if self.stages["s3"] is None and not self._stage3():
            return False
        if self.stages["s4"] is None and not self._stage4():
            return False
        return all(self.stages.values())

    def handle_key(self, key: str, epoch: float) -> None:
        """T1 needs no operator marks; present for runner symmetry."""

    def shutdown(self) -> None:
        if self._poller is not None:
            self._poller.stop()

    def summary(self) -> dict:
        return {"stages": dict(self.stages), "entity": self.entity_id}
