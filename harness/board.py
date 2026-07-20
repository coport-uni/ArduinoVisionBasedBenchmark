"""Board access layer: SSH transport, safety guard, FR2 reset.

All board access goes through this module so that NFR4 (command scope)
and the Wi-Fi / SSH preservation rule are enforced in exactly one
place. The harness's own SSH calls use the system ssh binary directly,
never the per-trial ssh.bat wrapper, so agent call counts stay clean.
"""

import re
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from harness.errors import BoardConnectionError, UnsafeCommandError
from harness.util import append_line, now_iso


@dataclass
class ShellResult:
    """Outcome of one remote command."""

    code: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.code == 0


class Board:
    """Base board interface; per-board constants live in subclasses.

    SPEC 9 asks for board constants split into classes so the harness
    can extend to more boards later without touching call sites.
    """

    # Patterns that would break Wi-Fi or SSH access (the only state the
    # reset must preserve) or reboot the board. Checked on every
    # harness-issued command; the agent's own commands are NOT filtered
    # (its wrapper only logs).
    FORBIDDEN_PATTERNS = (
        r"\bnmcli\b",
        r"NetworkManager",
        r"/etc/network",
        r"\bsshd\b",
        r"authorized_keys",
        r"/etc/ssh/",
        r"\breboot\b",
        r"\bshutdown\b",
        r"\bpoweroff\b",
        r"\bhalt\b",
    )

    HOME_DIR = "/home/arduino"
    BENCH_DIR = "/home/arduino/benchmark"
    APPS_DIR = "/home/arduino/ArduinoApps"

    CONNECT_RETRIES = 3
    RETRY_BACKOFF_S = 5

    def __init__(self, config, log_path: Path | None = None):
        self._config = config
        self._ssh = config.get("ssh_path", "ssh")
        self._scp = config.get("scp_path", "scp")
        self._target = f"{config['board_user']}@{config['board_ip']}"
        self._lock = threading.Lock()
        self._log_path = log_path
        self._compiled = [re.compile(p) for p in self.FORBIDDEN_PATTERNS]

    # -- transport -------------------------------------------------

    def _base_ssh_cmd(self) -> list[str]:
        return [
            self._ssh,
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=10",
            self._target,
        ]

    def _log(self, message: str) -> None:
        if self._log_path is not None:
            append_line(self._log_path, f"{now_iso()} {message}")

    def _check_safety(self, command: str) -> None:
        for pattern in self._compiled:
            if pattern.search(command):
                raise UnsafeCommandError(
                    f"command matches forbidden pattern {pattern.pattern!r}: {command}"
                )

    def shell(
        self,
        command: str,
        timeout: int = 60,
        sudo: bool = False,
        check_safety: bool = True,
    ) -> ShellResult:
        """Run *command* on the board over SSH.

        @param command       Remote shell command line.
        @param timeout       Seconds before the SSH call is killed.
        @param sudo          Prefix with passwordless sudo -n.
        @param check_safety  Screen against FORBIDDEN_PATTERNS (NFR4).
        @return              ShellResult with exit code and output.
        """
        if check_safety:
            self._check_safety(command)
        remote = f"sudo -n {command}" if sudo else command
        with self._lock:
            self._log(f"shell: {remote}")
            try:
                proc = subprocess.run(
                    [*self._base_ssh_cmd(), remote],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=timeout,
                    stdin=subprocess.DEVNULL,
                )
            except subprocess.TimeoutExpired:
                return ShellResult(code=124, stdout="", stderr="timeout")
        return ShellResult(
            code=proc.returncode,
            stdout=proc.stdout or "",
            stderr=proc.stderr or "",
        )

    def ensure_connected(self) -> None:
        """Verify SSH reachability, retrying with backoff (FT7 basis)."""
        last = ""
        for attempt in range(1, self.CONNECT_RETRIES + 1):
            result = self.shell("true", timeout=15)
            if result.ok:
                return
            last = result.stderr.strip()
            self._log(f"connect attempt {attempt} failed: {last}")
            time.sleep(self.RETRY_BACKOFF_S * attempt)
        raise BoardConnectionError(f"board unreachable over SSH: {last}")

    def push(self, local: Path, remote: str, timeout: int = 120) -> bool:
        """Copy a local file to the board via scp."""
        with self._lock:
            self._log(f"push: {local} -> {remote}")
            proc = subprocess.run(
                [
                    self._scp,
                    "-o",
                    "BatchMode=yes",
                    str(local),
                    f"{self._target}:{remote}",
                ],
                capture_output=True,
                timeout=timeout,
                stdin=subprocess.DEVNULL,
            )
        return proc.returncode == 0

    def pull(self, remote: str, local: Path, timeout: int = 120) -> bool:
        """Copy a board file to the host via scp."""
        with self._lock:
            self._log(f"pull: {remote} -> {local}")
            proc = subprocess.run(
                [
                    self._scp,
                    "-o",
                    "BatchMode=yes",
                    f"{self._target}:{remote}",
                    str(local),
                ],
                capture_output=True,
                timeout=timeout,
                stdin=subprocess.DEVNULL,
            )
        return proc.returncode == 0

    def read_file(self, remote: str, timeout: int = 30) -> str | None:
        """Return a board file's contents, or None when absent."""
        result = self.shell(f"cat {remote}", timeout=timeout)
        return result.stdout if result.ok else None

    def curl_local(
        self, port: int, path: str = "/", headers: dict | None = None
    ) -> ShellResult:
        """Board-internal curl (judging must not depend on host network)."""
        header_args = ""
        for key, value in (headers or {}).items():
            header_args += f" -H '{key}: {value}'"
        return self.shell(
            "curl -s -o /dev/null -w '%{http_code}'"
            f"{header_args} --max-time 10 http://127.0.0.1:{port}{path}",
            timeout=20,
        )

    def measure_clock_skew(self) -> float | None:
        """Return board_time - host_time in seconds, or None on failure.

        T2 latency subtracts board log timestamps from host mark times,
        so the skew must be measured and applied per trial.
        """
        t0 = time.time()
        result = self.shell("date +%s.%N", timeout=15)
        t1 = time.time()
        if not result.ok:
            return None
        try:
            board_time = float(result.stdout.strip())
        except ValueError:
            return None
        midpoint = (t0 + t1) / 2
        return board_time - midpoint

    # -- FR2 reset -------------------------------------------------

    def reset_steps(self) -> list[tuple[str, str]]:
        """Ordered (description, command) pairs for the FR2 reset.

        Only touches the areas SPEC FR2 names; Wi-Fi and SSH state are
        additionally protected by FORBIDDEN_PATTERNS.
        """
        bench = self.BENCH_DIR
        return [
            (
                # Agents install HA either as a Docker container or as
                # a host systemd venv service; catch both. The name
                # variants (home-assistant, homeassistant, hass) must
                # all be matched -- an earlier grep missed the
                # hyphenated form and left a systemd HA answering 8123.
                "stop and disable host Home Assistant services",
                "sh -c 'for u in $(systemctl list-unit-files"
                ' --no-legend 2>/dev/null | awk "{print \\$1}" |'
                ' grep -Ei "home-?assistant|hass");'
                ' do systemctl disable --now "$u" 2>/dev/null;'
                ' rm -f "/etc/systemd/system/$u"; done;'
                " systemctl daemon-reload 2>/dev/null; true'",
            ),
            (
                "kill any stray Home Assistant processes",
                'sh -c \'pkill -f "[h]omeassistant" 2>/dev/null;'
                ' pkill -f "[h]ass" 2>/dev/null; true\'',
            ),
            (
                "stop and remove Home Assistant containers",
                "docker ps -aq --filter name=homeassistant | xargs -r docker rm -f",
            ),
            (
                "remove Home Assistant images",
                "docker images -q '*homeassistant*' | xargs -r docker rmi -f",
            ),
            (
                "remove Home Assistant data + venv directories",
                f"rm -rf {self.HOME_DIR}/homeassistant"
                f" {self.HOME_DIR}/.homeassistant /opt/homeassistant"
                f" {self.HOME_DIR}/hass {self.HOME_DIR}/.config/homeassistant",
            ),
            # SPEC FR2 says to purge the Docker engine, but the UNO Q
            # ships with Docker as part of the stock image and the
            # Arduino App Lab runtime (app containers) requires it.
            # Factory state therefore KEEPS the engine and the
            # ghcr.io/arduino/app-bricks base images; everything an
            # agent might have added (HA etc.) is still removed.
            (
                "ensure Docker engine is running",
                "sh -c 'systemctl start docker 2>/dev/null; true'",
            ),
            (
                "remove all containers (apps are recreated on demand)",
                "sh -c 'docker ps -aq | xargs -r docker rm -f; true'",
            ),
            (
                "remove non-App-Lab images",
                "sh -c 'docker images --format"
                ' "{{.Repository}}:{{.Tag}} {{.ID}}" |'
                ' grep -v "arduino/app-bricks" | awk "{print \\$2}" |'
                " xargs -r docker rmi -f; true'",
            ),
            (
                "purge MQTT brokers",
                "apt-get purge -y mosquitto mosquitto-clients 2>/dev/null; true",
            ),
            (
                "recreate benchmark directory",
                f"rm -rf {bench} && mkdir -p {bench}"
                f" && chown {self._config['board_user']}: {bench}",
            ),
            (
                "remove benchmark-created systemd units",
                "sh -c 'for u in $(ls /etc/systemd/system/ 2>/dev/null |"
                " grep -Ei"
                ' "benchmark|home-?assistant|hass|person|yolo|clock|led");'
                ' do systemctl disable --now "$u" 2>/dev/null;'
                ' rm -f "/etc/systemd/system/$u"; done;'
                " systemctl daemon-reload'",
            ),
        ]

    BLANK_APP = "qtest_blank"

    def flash_blank_sketch(self) -> bool:
        """Flash the blank sketch so no prior trial's MCU code keeps
        driving the LEDs or matrix into the next trial's judgment.

        Stopping an app only kills its Linux container; the sketch
        runs on the STM32 until overwritten, so the reset must
        actively reflash. The qtest_blank app lives in APPS_DIR and
        belongs to the apps baseline.
        """
        app_path = f"{self.APPS_DIR}/{self.BLANK_APP}"
        if not self.shell(f"test -d {app_path}", timeout=15).ok:
            self._log("flash_blank_sketch: blank app missing")
            return False
        restart = self.shell(f"arduino-app-cli app restart {app_path}", timeout=420)
        self.shell(f"arduino-app-cli app stop {app_path}", timeout=60)
        ok = restart.ok and "successfully" in restart.stdout
        self._log(f"flash_blank_sketch: ok={ok}")
        return ok

    def reset(self, apps_baseline: list[str] | None = None) -> list[dict]:
        """Run the FR2 reset; log every step, never abort (SPEC FR2).

        @param apps_baseline  App names captured at first preflight;
                              newer apps are stopped and removed.
        @return               Per-step dicts with ok flag and output.
        """
        outcomes = []
        for description, command in self.reset_steps():
            result = self.shell(command, timeout=300, sudo=True)
            outcomes.append(
                {
                    "step": description,
                    "ok": result.ok,
                    "output": (result.stdout + result.stderr).strip()[:500],
                }
            )
            self._log(f"reset [{description}]: ok={result.ok}")

        if apps_baseline is not None:
            current = self.list_apps()
            for app in current:
                if app not in apps_baseline:
                    result = self.shell(
                        f"rm -rf '{self.APPS_DIR}/{app}'",
                        timeout=60,
                        sudo=True,
                    )
                    outcomes.append(
                        {
                            "step": f"remove new app {app}",
                            "ok": result.ok,
                            "output": result.stderr.strip()[:200],
                        }
                    )

        flashed = self.flash_blank_sketch()
        outcomes.append(
            {
                "step": "flash blank sketch (clear MCU state)",
                "ok": flashed,
                "output": "",
            }
        )
        return outcomes

    def verify_reset(self) -> dict:
        """Post-reset checks: port 8123 dead, events.log absent (FR2)."""
        port = self._config["ha"]["port"]
        curl = self.curl_local(port)
        port_dead = (not curl.ok) or curl.stdout.strip() in ("", "000")
        event_log = self._config["t2"]["event_log_on_board"]
        log_absent = not self.shell(f"test -f {event_log}").ok
        return {"port_8123_dead": port_dead, "events_log_absent": log_absent}

    def list_apps(self) -> list[str]:
        """Names under APPS_DIR, for the baseline snapshot comparison."""
        result = self.shell(f"ls -1 {self.APPS_DIR} 2>/dev/null")
        if not result.ok:
            return []
        return [line for line in result.stdout.splitlines() if line.strip()]


class UnoQBoard(Board):
    """Arduino UNO Q (Debian aarch64, user arduino)."""


BOARD_TYPES = {"unoq": UnoQBoard}


def make_board(config, log_path: Path | None = None) -> Board:
    """Instantiate the Board subclass named by config board_type."""
    board_cls = BOARD_TYPES[config.get("board_type", "unoq")]
    return board_cls(config, log_path=log_path)
