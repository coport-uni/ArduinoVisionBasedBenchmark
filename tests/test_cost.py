"""Token parsing and cost formula tests (FR6)."""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.config import load_config
from harness.cost import TokenUsage, cost_a_usd, cost_b, parse_stream_json

REPO_ROOT = Path(__file__).resolve().parent.parent


def stream_lines(*events) -> list[str]:
    return [json.dumps(e) + "\n" for e in events]


class ParseStreamJsonTest(unittest.TestCase):
    def test_result_event_totals_are_authoritative(self):
        lines = stream_lines(
            {
                "type": "assistant",
                "message": {"usage": {"input_tokens": 10, "output_tokens": 5}},
            },
            {
                "type": "result",
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "cache_creation_input_tokens": 7,
                    "cache_read_input_tokens": 3,
                },
                "total_cost_usd": 0.42,
            },
        )
        usage = parse_stream_json(lines)
        self.assertEqual(usage.input, 100)
        self.assertEqual(usage.output, 50)
        self.assertEqual(usage.cache_creation, 7)
        self.assertEqual(usage.cache_read, 3)
        self.assertEqual(usage.reported_cost_usd, 0.42)

    def test_malformed_output_leaves_tokens_null(self):
        usage = parse_stream_json(["plain text output\n", "not json {{{\n"])
        self.assertFalse(usage.parsed)
        self.assertIsNone(usage.input)

    def test_message_usage_accumulates_without_result_event(self):
        lines = stream_lines(
            {
                "type": "assistant",
                "message": {"usage": {"input_tokens": 10, "output_tokens": 5}},
            },
            {
                "type": "assistant",
                "message": {"usage": {"input_tokens": 20, "output_tokens": 15}},
            },
        )
        usage = parse_stream_json(lines)
        self.assertEqual(usage.input, 30)
        self.assertEqual(usage.output, 20)


class CostFormulaTest(unittest.TestCase):
    def setUp(self):
        self.config = load_config(REPO_ROOT)

    def test_cost_a_claude_cache_aware(self):
        usage = TokenUsage(
            input=1_000_000, output=1_000_000, cache_creation=0, cache_read=0
        )
        pricing = self.config["claude_pricing_per_mtok"]
        expected = pricing["input"] + pricing["output"]
        self.assertAlmostEqual(cost_a_usd(self.config, "claude", usage), expected)

    def test_cost_a_null_when_unparsed(self):
        self.assertIsNone(cost_a_usd(self.config, "claude", TokenUsage()))

    def test_cost_b_null_for_api_model(self):
        wh, busy = cost_b(self.config, "claude", [(0, 100, 50), (10, 100, 50)])
        self.assertIsNone(wh)
        self.assertIsNone(busy)

    def test_cost_b_trapezoidal_integration(self):
        # Constant 100 W for 3600 s must integrate to 100 Wh exactly.
        samples = [(float(t), 100.0, 50.0) for t in range(0, 3601, 5)]
        wh, busy = cost_b(self.config, "glm", samples)
        self.assertAlmostEqual(wh, 100.0, places=6)
        self.assertAlmostEqual(busy, 3600.0, places=6)


if __name__ == "__main__":
    unittest.main()
