# Purpose: one-off smoke test that wrapper generation + logging works
# and the trial matrix filters the Latin square correctly (Phase 1/2).
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.config import build_trial_matrix, load_config
from harness.wrappers import count_calls, generate_wrappers, smoke_test_wrapper

config = load_config()

# 1. Trial matrix: Claude-only should give 12 trials in square order.
trials = build_trial_matrix(config)
print(f"matrix size: {len(trials)}")
for trial in trials[:6]:
    print(" ", trial.trial_id)
assert len(trials) == 12, "expected 12 Claude-only trials"
assert trials[0].trial_id == "T1_CLD_VP_r1"
assert trials[2].trial_id == "T1_CLD_VM_r1"

# 2. Wrappers: V+ has snap.bat, V- does not; ssh.bat logs calls.
with tempfile.TemporaryDirectory() as tmp:
    trial_dir = Path(tmp) / "trial"
    wrapper_dir = generate_wrappers(trial_dir, "V+", config, config.root)
    assert (wrapper_dir / "ssh.bat").exists()
    assert (wrapper_dir / "snap.bat").exists()
    ok = smoke_test_wrapper(wrapper_dir, "ssh")
    calls = count_calls(trial_dir, "ssh_calls.log")
    print(f"V+ wrapper smoke: ok={ok} ssh_calls={calls}")
    assert ok and calls == 1

    trial_dir2 = Path(tmp) / "trial2"
    wrapper_dir2 = generate_wrappers(trial_dir2, "V-", config, config.root)
    assert not (wrapper_dir2 / "snap.bat").exists()
    print("V- wrapper: no snap.bat (correct)")

print("ALL SMOKE TESTS PASSED")
