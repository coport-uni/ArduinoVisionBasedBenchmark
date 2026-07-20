# Purpose: diagnose the T1_CLD_VP_r1 s4 mismatch -- classify the three
# judge edge frames with magnitudes and zoom their LED area for review.
import json
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.config import load_config
from harness.vision import dominant_color_diff

config = load_config()
trial = Path("results/T1_CLD_VP_r1")
out = Path("claude_test/rgb_burst")

for name in ("judge_t1_1_red", "judge_t1_2_green", "judge_t1_3_blue"):
    result = dominant_color_diff(
        trial / f"{name}.jpg",
        trial / "baseline.jpg",
        config["led_regions"]["rgb_led"],
        config["hue_thresholds"],
    )
    hue = round(result["hue"]) if result["hue"] is not None else None
    print(f"{name}: {result['color']} hue={hue} mag={result['magnitude']:.0f}")
    im = Image.open(trial / f"{name}.jpg")
    im.crop((404, 203, 490, 288)).resize((430, 425)).save(out / f"{name}_zoom.jpg")
im = Image.open(trial / "baseline.jpg")
im.crop((404, 203, 490, 288)).resize((430, 425)).save(out / "trial_baseline_zoom.jpg")

# Which model is the agent running?
for line in (
    (trial / "agent_stdout.jsonl")
    .read_text(encoding="utf-8", errors="replace")
    .splitlines()
):
    if '"model"' in line:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        model = event.get("model") or (event.get("message") or {}).get("model")
        if model:
            print(f"agent model: {model}")
            break
