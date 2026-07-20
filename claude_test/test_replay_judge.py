# Purpose: verify the new stage-4 verification replay against the live
# HA + entity + token left by test-drive round 3, without a full trial.
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.board import make_board
from harness.config import load_config
from harness.judge_t1 import T1Judge

config = load_config()
board = make_board(config)
trial_dir = Path(tempfile.mkdtemp(prefix="replay_test_"))
judge = T1Judge(board, config, trial_dir)

print("s1:", judge._stage1())
print("s2:", judge._stage2(), "entity:", judge.entity_id)
if judge.entity_id is None:
    sys.exit("no entity -- board not in post-trial state")
print("s3+s4 replay:", judge._stage34())
print("stages:", judge.stages)
print("frames in:", trial_dir)
