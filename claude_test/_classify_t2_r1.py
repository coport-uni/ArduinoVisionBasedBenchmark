# Purpose: operator classification of T2_CLD_VP_r1 as FT5.
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.util import write_json_atomic, write_manifest

path = Path("results/T2_CLD_VP_r1/result.json")
record = json.loads(path.read_text(encoding="utf-8"))
record["failure_type"] = "FT5"
record["notes"] = (
    "Operator classification: legitimate FT5. The agent built a working "
    "bridge->matrix path (verified manually with snap) and an onnxruntime "
    "yolov8n pipeline, but the REAL detection loop never fired: s1/s2 were "
    "met by the agent's own manual end-to-end test events, which it then "
    "cleared; afterwards events.log stayed empty and the matrix never lit "
    "(judge delta ~0.011 vs threshold 0.25 across 24 checks). The physical "
    "stages caught what the log stages could not -- note for the report: "
    "log-based s1/s2 are agent-forgeable; s3/s4 are the integrity backstop."
)
write_json_atomic(path, record)
write_manifest(path.parent)
print("classified FT5")
