# Purpose: drive set_rgb through the agent's Bridge RPC directly
# (bypassing HA/MQTT) and classify each state on camera, to find the
# link where green/blue become white.
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.config import load_config
from harness.vision import capture_frame, expected_channel_margin

config = load_config()
out = Path("claude_test/rgb_burst")

RPC = (
    'docker exec ha_led-main-1 python -c "from arduino.app_utils import'
    " Bridge; Bridge.call('set_rgb', {args})\""
)


def call(args: str) -> None:
    proc = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "arduino@192.168.31.84", RPC.format(args=args)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if proc.returncode != 0:
        print(f"RPC {args} failed: {proc.stderr.strip()[:200]}")


call("False, False, False")
time.sleep(1.5)
base = out / "rpc_off.jpg"
capture_frame(config, base, lock_dir=config.results_dir)

for name, args, channel in (
    ("red", "True, False, False", "red"),
    ("green", "False, True, False", "green"),
    ("blue", "False, False, True", "blue"),
):
    call(args)
    time.sleep(1.5)
    frame = out / f"rpc_{name}.jpg"
    capture_frame(config, frame, lock_dir=config.results_dir)
    margin = expected_channel_margin(
        frame,
        base,
        config["led_regions"]["rgb_led"],
        channel,
        config["hue_thresholds"],
    )
    print(f"rpc {name}: expected-channel margin {margin:+.1f}")

call("False, False, False")
