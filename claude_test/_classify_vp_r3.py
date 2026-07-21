# Purpose: classify T1_CLD_VP_r3 as FT8 (optical measurement limit),
# not an agent fault. Direct drive of the surviving entity confirmed
# green works (margin +3.5) but afternoon ambient (off_level 292-368)
# pushed the weakest channel below the +4 floor; red +78, blue +8.8.
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.util import write_json_atomic, write_manifest

path = Path("results/T1_CLD_VP_r3/result.json")
record = json.loads(path.read_text(encoding="utf-8"))
record["failure_type"] = "FT8"
record["status"] = "void"
record["notes"] = (
    "Optical measurement limit, NOT an agent fault (FT8, re-run). s1/s2/"
    "s3 met; s4 green MISS. Direct drive of the surviving entity after "
    "the run confirmed the agent's RGB light works: red margin +78, blue "
    "+8.8, green +3.5 -- green works but is the dimmest LED3 channel and "
    "afternoon ambient (off_level 292-368, up from ~250 at midday) pushed "
    "it just below the +4 detection floor. The 5 earlier trials passed "
    "with green +9..+26 under lower ambient. Re-collect under favourable "
    "light or with the camera closer."
)
write_json_atomic(path, record)
write_manifest(path.parent)
print("classified VP_r3 as FT8 (void)")
