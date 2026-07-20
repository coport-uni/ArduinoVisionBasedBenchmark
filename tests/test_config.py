"""Trial matrix and config validation tests (FR9 groundwork)."""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.config import build_trial_matrix, load_config
from harness.errors import ConfigError

REPO_ROOT = Path(__file__).resolve().parent.parent


class TrialMatrixTest(unittest.TestCase):
    def setUp(self):
        self.config = load_config(REPO_ROOT)

    def test_claude_only_matrix_is_12_trials(self):
        trials = build_trial_matrix(self.config)
        self.assertEqual(len(trials), 12)

    def test_square_order_preserved_after_filter(self):
        trials = build_trial_matrix(self.config)
        round1 = [t.condition.condition_id for t in trials[:4]]
        # Round 1 square is CLD_VP, GLM_VP, CLD_VM, GLM_VM; with GLM
        # filtered the survivors keep their relative order.
        self.assertEqual(round1, ["CLD_VP", "CLD_VP", "CLD_VM", "CLD_VM"])

    def test_trial_ids_unique(self):
        trials = build_trial_matrix(self.config)
        ids = [t.trial_id for t in trials]
        self.assertEqual(len(ids), len(set(ids)))

    def test_missing_key_rejected(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = json.loads((REPO_ROOT / "config.json").read_text(encoding="utf-8"))
            del raw["ha"]
            (root / "config.json").write_text(json.dumps(raw))
            with self.assertRaises(ConfigError):
                load_config(root)

    def test_bad_region_rejected(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = json.loads((REPO_ROOT / "config.json").read_text(encoding="utf-8"))
            raw["led_regions"]["rgb_led"] = [100, 100, 50, 200]
            (root / "config.json").write_text(json.dumps(raw))
            with self.assertRaises(ConfigError):
                load_config(root)


if __name__ == "__main__":
    unittest.main()
