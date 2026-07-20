"""Sampling threads: board resources and (GLM-only) GPU power (FR6).

Board sampling combines all probes into one SSH round trip per
interval to keep transport load negligible against 15 s spacing.
"""

import csv
import subprocess
import threading
import time
from pathlib import Path

from harness.util import now_iso

# One remote command returning four labelled lines per sample.
_BOARD_PROBE = (
    "free -m | awk '/^Mem:/{print \"MEM \" $3}';"
    " cat /proc/loadavg | awk '{print \"LOAD \" $1}';"
    " df -P / | awk 'NR==2{print \"DISK \" $5}';"
    " echo \"HTTP $(curl -s -o /dev/null -w '%{http_code}'"
    ' --max-time 5 http://127.0.0.1:{port}/ 2>/dev/null || echo 000)"'
)


class SamplerThread(threading.Thread):
    """Base periodic sampler writing CSV rows until stopped."""

    def __init__(self, csv_path: Path, interval_s: float, header: list[str]):
        super().__init__(daemon=True)
        self._csv_path = csv_path
        self._interval = interval_s
        self._header = header
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def sample(self) -> list | None:
        raise NotImplementedError

    def run(self) -> None:
        is_new = not self._csv_path.exists()
        with self._csv_path.open("a", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            if is_new:
                writer.writerow(self._header)
            while not self._stop.is_set():
                row = self.sample()
                if row is not None:
                    writer.writerow(row)
                    fh.flush()
                self._stop.wait(self._interval)


class ResourceMonitor(SamplerThread):
    """Board memory / load / disk / HA port sampler -> resources.csv."""

    def __init__(self, board, config, csv_path: Path):
        super().__init__(
            csv_path,
            config["monitor_interval_s"],
            ["timestamp", "mem_used_mb", "load1", "disk_used_pct", "http_8123"],
        )
        self._board = board
        self._probe = _BOARD_PROBE.replace("{port}", str(config["ha"]["port"]))
        self.peak_mem_mb = 0.0
        self.peak_load = 0.0

    def sample(self) -> list | None:
        result = self._board.shell(self._probe, timeout=20)
        if not result.ok:
            return [now_iso(), "", "", "", "unreachable"]
        values = {"MEM": "", "LOAD": "", "DISK": "", "HTTP": ""}
        for line in result.stdout.splitlines():
            parts = line.split(None, 1)
            if len(parts) == 2 and parts[0] in values:
                values[parts[0]] = parts[1].strip()
        try:
            self.peak_mem_mb = max(self.peak_mem_mb, float(values["MEM"]))
        except ValueError:
            pass
        try:
            self.peak_load = max(self.peak_load, float(values["LOAD"]))
        except ValueError:
            pass
        return [
            now_iso(),
            values["MEM"],
            values["LOAD"],
            values["DISK"].rstrip("%"),
            values["HTTP"],
        ]


class GpuMonitor(SamplerThread):
    """nvidia-smi power/util sampler -> gpu.csv (GLM trials only).

    Keeps (monotonic_s, power_w, util_pct) tuples for the formula-B
    integration in cost.py. gpu_index selects one GPU on multi-GPU
    hosts; "all" sums power across GPUs.
    """

    def __init__(self, config, csv_path: Path):
        super().__init__(
            csv_path,
            config["gpu_power_poll_s"],
            ["timestamp", "power_w", "util_pct"],
        )
        self._index = config.get("gpu_index", 0)
        self.samples: list[tuple[float, float, float]] = []

    def sample(self) -> list | None:
        cmd = [
            "nvidia-smi",
            "--query-gpu=index,power.draw,utilization.gpu",
            "--format=csv,noheader,nounits",
        ]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10,
                stdin=subprocess.DEVNULL,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return None
        if proc.returncode != 0:
            return None
        power_total = 0.0
        util_max = 0.0
        matched = False
        for line in proc.stdout.strip().splitlines():
            fields = [f.strip() for f in line.split(",")]
            if len(fields) < 3:
                continue
            index = int(fields[0])
            if self._index != "all" and index != self._index:
                continue
            matched = True
            power_total += float(fields[1])
            util_max = max(util_max, float(fields[2]))
        if not matched:
            return None
        self.samples.append((time.monotonic(), power_total, util_max))
        return [now_iso(), f"{power_total:.1f}", f"{util_max:.0f}"]
