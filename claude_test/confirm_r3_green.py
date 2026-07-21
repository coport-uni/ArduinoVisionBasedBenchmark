# Purpose: drive VP_r3's surviving entity green/red directly and
# measure the camera margin, to decide whether VP_r3's s4 green MISS
# was a real agent/hardware fault (FT5) or a transient.
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.config import load_config
from harness.vision import (
    capture_frame,
    expected_channel_margin,
    region_brightness,
)

config = load_config()
region = config["led_regions"]["rgb_led"]
out = Path("claude_test/live_burst")
out.mkdir(exist_ok=True)
ENT = "light.led3_rgb"
TOKEN_CMD = "cat /home/arduino/benchmark/ha_token.txt"


def ssh(cmd: str) -> str:
    r = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "arduino@192.168.31.84", cmd],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return r.stdout.strip()


token = ssh(TOKEN_CMD)
api = "http://127.0.0.1:8123/api/services/light"
auth = f"Authorization: Bearer {token}"


def light(payload: str) -> None:
    ssh(
        f"curl -s -o /dev/null -X POST -H '{auth}'"
        f" -H 'Content-Type: application/json' -d '{payload}' {api}/turn_on"
    )


def off() -> None:
    ssh(
        f"curl -s -o /dev/null -X POST -H '{auth}'"
        f" -H 'Content-Type: application/json'"
        f' -d \'{{"entity_id":"{ENT}"}}\' {api}/turn_off'
    )


for color, rgb in (("red", "255,0,0"), ("green", "0,255,0"), ("blue", "0,0,255")):
    off()
    time.sleep(3)
    base = out / f"confirm_{color}_off.jpg"
    capture_frame(config, base, lock_dir=config.results_dir)
    off_level = region_brightness(base, region)
    light(f'{{"entity_id":"{ENT}","rgb_color":[{rgb}],"brightness":255}}')
    time.sleep(3)
    on = out / f"confirm_{color}_on.jpg"
    capture_frame(config, on, lock_dir=config.results_dir)
    rise = region_brightness(on, region) - off_level
    margin = expected_channel_margin(on, base, region, color, config["hue_thresholds"])
    print(f"{color}: off_level={off_level:.1f} rise={rise:+.1f} margin={margin:+.1f}")

off()
