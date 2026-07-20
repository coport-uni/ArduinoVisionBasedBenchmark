# Purpose: one-off operator reclassification of T1_CLD_VP_r1 from FT5
# to FT8 after the agent implementation was proven correct.
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.util import write_json_atomic, write_manifest

path = Path("results/T1_CLD_VP_r1/result.json")
record = json.loads(path.read_text(encoding="utf-8"))
record["failure_type"] = "FT8"
record["status"] = "void"
record["notes"] = (
    "Operator reclassification (was FT5): the agent implementation is "
    "CORRECT -- direct Bridge-RPC drive shows proper per-channel colours "
    "(margins red +61 / green +6.8 / blue +8.8) and MQTT payloads are "
    "exact. The stage-4 failure was a harness artifact: demo-edge "
    "captures raced the variable HA->MQTT->RPC chain latency, and "
    "afternoon ambient light collapsed the LED colour margin below "
    "detection. FT8: excluded from aggregation, re-run required after "
    "the optical setup is improved (camera closer to the board or "
    "reduced ambient)."
)
write_json_atomic(path, record)
write_manifest(path.parent)
print("reclassified FT8 / void")
