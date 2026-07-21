"""T1 judge: Home Assistant + RGB LED, four stages (FR4).

Success requires all four stages. Judging relies only on board state,
the HA API (queried board-side), and host-camera frames -- never on
agent stdout (NFR1).

Stage 1  port 8123 answers 200/302/401/405 (board-internal curl)
Stage 2  token file exists and /api/states lists an RGB-capable light
Stage 3+4  ONE verification replay: the judge drives the agent-created
         entity through red -> green -> blue itself (via the agent-
         saved token) and checks each colour physically on camera.
         s3 is set once RED is verified in order (entity controllable,
         LED physically responds); s4 once all three pass.

Operator-approved deviation from SPEC FR4-3/4-4 (passively observe the
agent's own demo at its colour edges): passive observation is timing-
fragile because the agent's one-shot R/G/B/off demo usually finishes
before the state poller starts (the poller needs the token, i.e.
stage 2), so the judge would miss it and false-negative. The replay
exercises the full agent deliverable -- token, entity, sketch, wiring
-- with judge-controlled timing, uses only the HA API and the camera
(NFR1), and archives every frame plus a note when the demo *was*
caught passively.
"""

import json
import threading
import time
from pathlib import Path

from harness.util import append_line, now_iso
from harness.vision import (
    capture_frame,
    dominant_color_diff,
    expected_channel_margin,
    region_brightness,
)

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

    def _passive_sequence_seen(self) -> bool:
        """Whether the poller happened to catch the agent's own demo.

        Logged as supporting evidence only. s3/s4 no longer gate on
        this -- the agent's one-shot demo often runs before the poller
        starts (poller needs the token, met at s2), so passive
        observation is timing-fragile. The verification replay in
        _stage34 is the authoritative check.
        """
        sequence = [o["key"] for o in self._observed_sequence()]
        position = 0
        for key in sequence:
            if position < len(EXPECTED_SEQUENCE) and key == EXPECTED_SEQUENCE[position]:
                position += 1
        return position == len(EXPECTED_SEQUENCE)

    REPLAY_COLORS = {
        "red": [255, 0, 0],
        "green": [0, 255, 0],
        "blue": [0, 0, 255],
    }
    # Post-readback settle: the HA -> MQTT -> bridge-RPC -> sketch
    # chain has VARIABLE latency (fixed delays of 1.5-3.5 s were both
    # beaten intermittently), so captures are gated on the entity
    # state reflecting the commanded colour, plus this short settle
    # for the physical LED/camera exposure.
    REPLAY_SETTLE_S = 1.0
    READBACK_TIMEOUT_S = 12.0

    def _call_light_service(self, service: str, payload: dict) -> bool:
        port = self._config["ha"]["port"]
        body = json.dumps(payload)
        result = self._board.shell(
            f"curl -s -o /dev/null -w '%{{http_code}}' --max-time 10"
            f" -X POST -H 'Authorization: Bearer {self._token}'"
            f" -H 'Content-Type: application/json' -d '{body}'"
            f" http://127.0.0.1:{port}/api/services/light/{service}",
            timeout=20,
        )
        return result.ok and result.stdout.strip() in ("200", "201")

    def _replay_capture(self, name: str) -> Path | None:
        path = self._trial_dir / f"replay_{name}.jpg"
        try:
            capture_frame(
                self._config,
                path,
                lock_dir=self._config.results_dir,
                lock_timeout_s=20.0,
            )
            return path
        except Exception as exc:
            append_line(self._log, f"{now_iso()} replay capture failed ({name}): {exc}")
            return None

    def _stage34(self) -> bool:
        """Verification replay driving stages 3 AND 4.

        The judge commands the agent-created entity through
        red -> green -> blue itself (agent-saved token) and verifies
        each physically on camera. Setting s3 after RED confirms the
        entity is RGB-controllable and the LED physically responds in
        order; s4 after all three confirms the full sequence. This
        replaces the timing-fragile passive observation of the agent's
        one-shot demo. Colour classification is the baseline-
        differential (the on-board LED3 blows out to near-white, so
        absolute hue fails while frame-minus-off keeps the colour).
        """
        if self._token is None or self.entity_id is None:
            return False
        # Record whether the poller passively caught the demo (evidence
        # only; not a gate).
        if self._passive_sequence_seen():
            append_line(self._log, f"{now_iso()} note: agent demo observed passively")
        # Freeze the poller so its edge captures cannot interleave
        # with the replay's own captures.
        if self._poller is not None:
            self._poller.stop()

        margin_floor = self._config["hue_thresholds"].get("diff_expected_margin", 4.0)
        rise_min = self._config["hue_thresholds"].get("replay_rise_min", 6.0)
        region = self._config["led_regions"]["rgb_led"]
        payload_off = {"entity_id": self.entity_id}

        verdicts = {}
        for color, rgb in self.REPLAY_COLORS.items():
            # Adjacent-pair differential: a fresh OFF frame right
            # before each colour, so ambient light and auto-exposure
            # are identical within the pair and the diff isolates the
            # LED. Both frames are gated on region brightness -- OFF
            # must be at the dark plateau, ON must show a rise -- which
            # also absorbs the variable HA -> MQTT -> RPC latency.
            # turn_off is issued twice (the first can be lost in the
            # variable HA -> MQTT -> RPC chain, leaving the LED lit into
            # the baseline capture) and we wait for the region to reach
            # a STABLE dark reading: two consecutive frames within
            # off_stable_tol of each other. A mid-transition still-lit
            # frame is thus never accepted as the baseline.
            self._call_light_service("turn_off", payload_off)
            time.sleep(self.REPLAY_SETTLE_S)
            self._call_light_service("turn_off", payload_off)
            time.sleep(self.REPLAY_SETTLE_S)
            off_stable_tol = self._config["hue_thresholds"].get("off_stable_tol", 4.0)
            off_frame = None
            off_level = None
            prev_level = None
            deadline = time.monotonic() + self.READBACK_TIMEOUT_S
            shot = 0
            while time.monotonic() < deadline:
                shot += 1
                candidate = self._replay_capture(f"{color}_off{shot}")
                if candidate is None:
                    return False
                level = region_brightness(candidate, region)
                if off_frame is None or level < off_level:
                    off_frame, off_level = candidate, level
                if prev_level is not None and abs(level - prev_level) <= off_stable_tol:
                    break  # stable dark reading reached
                prev_level = level
                time.sleep(0.6)
            if off_frame is None or off_level is None:
                return False
            append_line(
                self._log,
                f"{now_iso()} replay {color} off baseline:"
                f" {off_frame.name} level={off_level:.1f}",
            )

            ok = self._call_light_service(
                "turn_on",
                {
                    "entity_id": self.entity_id,
                    "rgb_color": rgb,
                    "brightness": 255,
                },
            )
            if not ok:
                append_line(self._log, f"{now_iso()} s4 replay: turn_on {color} failed")
                return False
            deadline = time.monotonic() + self.READBACK_TIMEOUT_S
            history = []
            hits = 0
            matched = False
            shot = 0
            while time.monotonic() < deadline:
                shot += 1
                frame = self._replay_capture(f"{color}_on{shot}")
                if frame is None:
                    return False
                rise = region_brightness(frame, region) - off_level
                if rise < rise_min:
                    history.append(f"unlit({rise:+.1f})")
                    time.sleep(0.4)
                    continue
                result = dominant_color_diff(
                    frame, off_frame, region, self._config["hue_thresholds"]
                )
                margin = expected_channel_margin(
                    frame,
                    off_frame,
                    region,
                    color,
                    self._config["hue_thresholds"],
                )
                hit = result["color"] == color or margin >= margin_floor
                history.append(f"{margin:+.1f}{'*' if hit else ''}")
                hits = hits + 1 if hit else 0
                if hits >= 2:
                    matched = True
                    break
                time.sleep(0.4)
            verdicts[color] = color if matched else "none"
            append_line(
                self._log,
                f"{now_iso()} replay {color}:"
                f" off_level={off_level:.1f} history={history}"
                f" -> {'OK' if matched else 'MISS'}",
            )
            if not matched:
                # A wrong colour terminates the sequence: the ordered
                # demo requirement is not satisfiable.
                break
            # First colour verified in order -> stage 3; all three ->
            # stage 4.
            if color == "red" and self.stages["s3"] is None:
                self.stages["s3"] = now_iso()
                append_line(self._log, f"{now_iso()} s3 met (entity controllable, red)")
        self._call_light_service("turn_off", payload_off)

        if all(verdicts.get(c) == c for c in self.REPLAY_COLORS):
            self.stages["s4"] = now_iso()
            append_line(self._log, f"{now_iso()} s4 met ({verdicts})")
            return True
        append_line(self._log, f"{now_iso()} replay incomplete ({verdicts})")
        return False

    # -- driver ----------------------------------------------------

    def poll(self) -> bool:
        """Advance whichever stages are still unmet; True when all met."""
        if self.stages["s1"] is None and not self._stage1():
            return False
        if self.stages["s2"] is None and not self._stage2():
            return False
        # One replay pass sets both s3 (red controllable) and s4 (all
        # three verified); it returns True only when s4 is met.
        if (self.stages["s3"] is None or self.stages["s4"] is None) and (
            not self._stage34()
        ):
            return False
        return all(self.stages.values())

    def handle_key(self, key: str, epoch: float) -> None:
        """T1 needs no operator marks; present for runner symmetry."""

    def shutdown(self) -> None:
        if self._poller is not None:
            self._poller.stop()

    def summary(self) -> dict:
        return {"stages": dict(self.stages), "entity": self.entity_id}
