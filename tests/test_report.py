"""Report math and degradation tests (FR8)."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.report import (
    build_markdown,
    cohens_d,
    load_results,
    sample_size_per_cell,
    two_by_two,
)


def make_record(task, model, vision, rep, duration, success=True, ft8=False):
    return {
        "trial_id": f"{task}_{model}_{vision}_r{rep}",
        "task": task,
        "model": model,
        "vision": vision,
        "rep": rep,
        "started_at": "",
        "finished_at": "",
        "success": success,
        "failure_type": "FT8" if ft8 else None,
        "judge_stages": {},
        "duration_s": duration,
        "tokens": {"input": 1000, "output": 500},
        "cost_a_usd": 0.01,
        "cost_b_wh": None,
        "cost_b_gpu_s": None,
        "ssh_calls": 10,
        "snap_calls": 2 if vision == "V+" else 0,
        "t2_latency_s": None,
        "peak_mem_mb": 900,
        "peak_load": 2.5,
        "status": "void" if ft8 else "complete",
        "notes": "",
    }


def full_24() -> list[dict]:
    records = []
    for task in ("T1", "T2"):
        for model in ("claude", "glm"):
            for vision in ("V+", "V-"):
                base = 1000 if model == "claude" else 1400
                bonus = -120 if vision == "V+" else 0
                for rep in (1, 2, 3):
                    records.append(
                        make_record(task, model, vision, rep, base + bonus + rep * 17)
                    )
    return records


class CohensDTest(unittest.TestCase):
    def test_known_value(self):
        d = cohens_d([10, 12, 14], [16, 18, 20])
        self.assertAlmostEqual(d, -3.0, places=6)

    def test_undefined_for_tiny_groups(self):
        self.assertIsNone(cohens_d([1], [2, 3]))

    def test_zero_variance_guarded(self):
        self.assertIsNone(cohens_d([5, 5, 5], [5, 5, 5]))


class SampleSizeTest(unittest.TestCase):
    def test_hand_calculation(self):
        # sd=200, mean=1000 -> effect=200 -> n = 2*(2.8016)^2 = 15.7 -> 16
        self.assertEqual(sample_size_per_cell(200.0, 1000.0), 16)

    def test_guards(self):
        self.assertIsNone(sample_size_per_cell(200.0, 0.0))


class TwoByTwoTest(unittest.TestCase):
    def test_full_matrix(self):
        analysis = two_by_two(full_24(), "T1")
        self.assertTrue(analysis["glm_present"])
        self.assertIsNotNone(analysis["interaction_dod"])
        self.assertIsNotNone(analysis["d_model_vp"])

    def test_claude_only_degrades_without_crash(self):
        claude_only = [r for r in full_24() if r["model"] == "claude"]
        analysis = two_by_two(claude_only, "T1")
        self.assertFalse(analysis["glm_present"])
        self.assertIsNone(analysis["interaction_dod"])
        self.assertIsNotNone(analysis["d_vision_claude"])
        markdown = build_markdown(claude_only)
        self.assertIn("n/a (GLM pending)", markdown)


class LoadResultsTest(unittest.TestCase):
    def test_ft8_void_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            results = Path(tmp)
            good = make_record("T1", "claude", "V+", 1, 900)
            void = make_record("T1", "claude", "V-", 1, 900, ft8=True)
            for record in (good, void):
                folder = results / record["trial_id"]
                folder.mkdir()
                (folder / "result.json").write_text(json.dumps(record))
            loaded = load_results(results)
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0]["trial_id"], good["trial_id"])


if __name__ == "__main__":
    unittest.main()
