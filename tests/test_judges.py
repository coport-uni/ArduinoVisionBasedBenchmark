"""Judge logic tests: event-log parsing, rgb classification (FR4/FR5)."""

import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.judge_t1 import classify_rgb
from harness.judge_t2 import parse_event_log


def iso(offset_s: float) -> str:
    base = datetime(2026, 7, 21, 10, 0, 0).astimezone()
    return (base + timedelta(seconds=offset_s)).isoformat()


class ClassifyRgbTest(unittest.TestCase):
    def test_primary_colors(self):
        self.assertEqual(classify_rgb([255, 0, 0]), "red")
        self.assertEqual(classify_rgb([0, 255, 0]), "green")
        self.assertEqual(classify_rgb([0, 0, 255]), "blue")

    def test_dominance_required(self):
        self.assertIsNone(classify_rgb([255, 200, 0]))  # orange-ish
        self.assertIsNone(classify_rgb([128, 128, 128]))  # grey

    def test_malformed(self):
        self.assertIsNone(classify_rgb(None))
        self.assertIsNone(classify_rgb([255, 0]))


class ParseEventLogTest(unittest.TestCase):
    def test_tab_separated_contract(self):
        text = f"{iso(0)}\tclock_detected\n{iso(2)}\tmatrix_draw_o\n"
        events = parse_event_log(text)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0][1], "clock_detected")
        self.assertAlmostEqual(events[1][0] - events[0][0], 2.0, places=3)

    def test_tolerates_space_and_noise_lines(self):
        text = (
            "starting detector...\n"
            f"{iso(0).replace('T', ' ')} clock_detected conf=0.91\n"
            "warning: low light\n"
        )
        events = parse_event_log(text)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0][1], "clock_detected")

    def test_five_second_window_logic(self):
        # 6 s gap: stage 2 must NOT match within a 5 s window.
        text = f"{iso(0)}\tclock_detected\n{iso(6)}\tmatrix_draw_o\n"
        events = parse_event_log(text)
        detections = [t for t, n in events if n == "clock_detected"]
        draws = [t for t, n in events if n == "matrix_draw_o"]
        window = 5
        matched = any(0 <= d - p <= window for p in detections for d in draws)
        self.assertFalse(matched)


if __name__ == "__main__":
    unittest.main()
