"""Backend for the agent-facing snap.bat wrapper (V+ trials only).

Captures one frame from the host camera into the trial folder as
snapshot_<n>.jpg and prints that path to stdout (SPEC FR3). Index
allocation is atomic via O_EXCL file creation, and the capture shares
the judge's camera lock with a short retry budget so judge captures
win contention.
"""

import argparse
import sys
from pathlib import Path

from harness.config import load_config
from harness.errors import CaptureError
from harness.vision import capture_frame

MAX_SNAPSHOTS = 9999


def next_snapshot_path(trial_dir: Path) -> Path:
    """Reserve the next free snapshot_<n>.jpg path atomically."""
    for index in range(1, MAX_SNAPSHOTS + 1):
        candidate = trial_dir / f"snapshot_{index}.jpg"
        try:
            candidate.touch(exist_ok=False)
            return candidate
        except FileExistsError:
            continue
    raise CaptureError("snapshot index space exhausted")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trial-dir", required=True)
    parser.add_argument("--repo", required=True)
    args = parser.parse_args()

    trial_dir = Path(args.trial_dir)
    config = load_config(Path(args.repo))
    out_path = next_snapshot_path(trial_dir)
    try:
        capture_frame(
            config,
            out_path,
            lock_dir=config.results_dir,
            lock_timeout_s=8.0,  # shorter than the judge's budget
        )
    except CaptureError as exc:
        out_path.unlink(missing_ok=True)
        print(f"snap failed: {exc}", file=sys.stderr)
        return 1
    print(out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
