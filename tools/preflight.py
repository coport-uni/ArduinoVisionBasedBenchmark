"""Per-run preflight gate (FR1): verify board, camera, and agent CLI.

Every check declares which condition IDs it blocks; the run is refused
only when a failing check blocks a condition that is actually selected.
That single rule lets a Claude-only run proceed while the GLM endpoint
and nvidia-smi are absent.

Usage:
    python tools/preflight.py [--tasks T1,T2] [--json out.json]
"""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.board import make_board  # noqa: E402
from harness.config import ALL_CONDITIONS, load_config  # noqa: E402
from harness.errors import CaptureError  # noqa: E402
from harness.vision import capture_frame, validate_regions  # noqa: E402

GLM_CONDITIONS = frozenset(c for c in ALL_CONDITIONS if c.startswith("GLM"))
GLM_VISION_CONDITIONS = frozenset({"GLM_VP"})
EVERY_CONDITION = frozenset(ALL_CONDITIONS)


class Check:
    """One preflight item: run() -> (ok, detail)."""

    def __init__(self, name, blocks, tasks, func):
        self.name = name
        self.blocks = blocks  # condition IDs this failure would block
        self.tasks = tasks  # task filter; None = always relevant
        self.func = func

    def relevant(self, selected_conditions, selected_tasks) -> bool:
        if self.tasks is not None and not (set(self.tasks) & set(selected_tasks)):
            return False
        return bool(self.blocks & selected_conditions)


def _run(cmd, timeout=30, input_text=None):
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            input=input_text,
            stdin=subprocess.DEVNULL if input_text is None else None,
        )
        out = ((proc.stdout or "") + (proc.stderr or "")).strip()
        return proc.returncode, out
    except FileNotFoundError:
        return 127, f"not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return 124, "timeout"


def build_checks(config, board, workdir: Path) -> list[Check]:
    """Assemble the FR1 check list against live config."""

    def ssh_connected():
        result = board.shell("true", timeout=15)
        return result.ok, "SSH key auth OK" if result.ok else result.stderr

    def passwordless_sudo():
        result = board.shell("true", timeout=15, sudo=True)
        return result.ok, (
            "passwordless sudo OK" if result.ok else result.stderr.strip()
        )

    def board_internet():
        result = board.shell(
            "curl -sI --max-time 10 https://deb.debian.org", timeout=20
        )
        return result.ok, (
            "board internet OK" if result.ok else "board cannot reach internet"
        )

    def port_8123_silent():
        result = board.curl_local(config["ha"]["port"])
        silent = (not result.ok) or result.stdout.strip() in ("", "000")
        return silent, (
            "port 8123 silent"
            if silent
            else f"port 8123 answered: {result.stdout.strip()}"
        )

    def host_camera():
        frame = workdir / "preflight_frame.jpg"
        try:
            capture_frame(config, frame, lock_dir=config.results_dir)
            return True, f"captured {frame.name}"
        except CaptureError as exc:
            return False, str(exc)

    def regions_in_frame():
        frame = workdir / "preflight_frame.jpg"
        if not frame.exists():
            return False, "no frame captured (camera check failed first)"
        problems = validate_regions(config, frame)
        return not problems, "; ".join(problems) or "regions inside frame"

    def claude_cli():
        code, out = _run([config["claude_path"], "--version"], timeout=60)
        detail = out.splitlines()[0] if out else "no output"
        return code == 0, detail

    def glm_health():
        base_url = config["models"]["glm"]["env"].get("ANTHROPIC_BASE_URL")
        if not base_url:
            return False, "glm env has no ANTHROPIC_BASE_URL"
        payload = json.dumps(
            {
                "model": config["models"]["glm"]["env"].get("ANTHROPIC_MODEL", "glm"),
                "max_tokens": 16,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/png",
                                    # 1x1 white PNG
                                    "data": (
                                        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAA"
                                        "fFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQ"
                                        "AAAABJRU5ErkJggg=="
                                    ),
                                },
                            },
                            {"type": "text", "text": "ping"},
                        ],
                    }
                ],
            }
        )
        code, out = _run(
            [
                "curl",
                "-s",
                "-o",
                "NUL",
                "-w",
                "%{http_code}",
                "--max-time",
                "15",
                "-X",
                "POST",
                f"{base_url}/v1/messages",
                "-H",
                "content-type: application/json",
                "-d",
                payload,
            ],
            timeout=30,
        )
        ok = code == 0 and out.strip() == "200"
        return ok, f"image-message probe HTTP {out.strip() or 'n/a'}"

    def board_video_devices():
        result = board.shell("ls /dev/video* 2>/dev/null", timeout=15)
        found = result.ok and result.stdout.strip()
        return bool(found), (
            result.stdout.strip().replace("\n", " ")
            if found
            else "no /dev/video* on board"
        )

    def nvidia_smi():
        code, out = _run(
            [
                "nvidia-smi",
                "--query-gpu=index,power.draw,utilization.gpu",
                "--format=csv,noheader",
            ]
        )
        return code == 0, out.replace("\n", " | ") if out else "missing"

    return [
        Check("1 SSH connection", EVERY_CONDITION, None, ssh_connected),
        Check("2 passwordless sudo", EVERY_CONDITION, None, passwordless_sudo),
        Check("3 board internet", EVERY_CONDITION, None, board_internet),
        Check("4 port 8123 silent", EVERY_CONDITION, None, port_8123_silent),
        Check("5 host camera capture", EVERY_CONDITION, None, host_camera),
        Check("6 led_regions in frame", EVERY_CONDITION, None, regions_in_frame),
        Check("7 claude CLI", EVERY_CONDITION, None, claude_cli),
        Check("8 GLM endpoint + image", GLM_CONDITIONS, None, glm_health),
        Check("9 board /dev/video*", EVERY_CONDITION, ("T2",), board_video_devices),
        Check("10 nvidia-smi", GLM_CONDITIONS, None, nvidia_smi),
        # (former check 11, console TTY, removed: T2 judging is fully
        # automatic now that the clock sits permanently in view)
    ]


def snapshot_apps_baseline(config, board) -> Path:
    """Store the ArduinoApps baseline on first preflight (FR2 input)."""
    baseline_dir = config.results_dir / "_baseline"
    baseline_dir.mkdir(parents=True, exist_ok=True)
    baseline_path = baseline_dir / "apps.json"
    if not baseline_path.exists():
        apps = board.list_apps()
        baseline_path.write_text(json.dumps({"apps": apps}, indent=2), encoding="utf-8")
    return baseline_path


def run_preflight(config, selected_tasks=("T1", "T2"), json_out=None) -> int:
    """Run all relevant checks; nonzero exit only on a blocking failure."""
    selected_conditions = frozenset(config["enabled_conditions"])
    board = make_board(config)
    workdir = Path(tempfile.mkdtemp(prefix="preflight_"))
    checks = build_checks(config, board, workdir)

    rows = []
    blocking_failure = False
    for check in checks:
        if not check.relevant(selected_conditions, selected_tasks):
            rows.append((check.name, "SKIP", "not relevant to this run"))
            continue
        ok, detail = check.func()
        rows.append((check.name, "PASS" if ok else "FAIL", detail))
        if not ok:
            blocking_failure = True

    width = max(len(name) for name, _, _ in rows)
    print(f"{'check':<{width}}  result  detail")
    print("-" * (width + 50))
    for name, status, detail in rows:
        print(f"{name:<{width}}  {status:<6}  {detail}")

    if not blocking_failure:
        snapshot_apps_baseline(config, board)

    if json_out:
        Path(json_out).write_text(
            json.dumps(
                [{"check": n, "status": s, "detail": d} for n, s, d in rows],
                indent=2,
            ),
            encoding="utf-8",
        )
    return 1 if blocking_failure else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tasks",
        default="T1,T2",
        help="comma-separated tasks planned for this run",
    )
    parser.add_argument("--json", help="also write results as JSON")
    args = parser.parse_args()
    config = load_config()
    tasks = tuple(t.strip() for t in args.tasks.split(",") if t.strip())
    return run_preflight(config, selected_tasks=tasks, json_out=args.json)


if __name__ == "__main__":
    sys.exit(main())
