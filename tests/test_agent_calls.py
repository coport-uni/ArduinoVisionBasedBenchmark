"""Agent-call counting fallback tests (FR6 metric robustness)."""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.cost import count_agent_calls


def tool_use(command: str) -> str:
    return json.dumps(
        {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "tool_use", "name": "Bash", "input": {"command": command}}
                ]
            },
        }
    )


class CountAgentCallsTest(unittest.TestCase):
    def test_counts_ssh_and_scp(self):
        lines = [
            tool_use('ssh arduino@192.168.31.84 "systemctl status"'),
            tool_use("scp local arduino@192.168.31.84:/tmp/x"),
            tool_use("ls -la"),
        ]
        ssh, snap = count_agent_calls(lines)
        self.assertEqual(ssh, 2)
        self.assertEqual(snap, 0)

    def test_counts_snap(self):
        lines = [tool_use("snap"), tool_use("snap.bat"), tool_use("echo hi")]
        ssh, snap = count_agent_calls(lines)
        self.assertEqual(snap, 2)

    def test_ignores_substrings(self):
        # "sshd" or "snapshot" must not be miscounted as ssh/snap.
        lines = [tool_use("systemctl status sshd; ls snapshot.jpg")]
        ssh, snap = count_agent_calls(lines)
        self.assertEqual(ssh, 0)
        self.assertEqual(snap, 0)

    def test_chained_commands(self):
        lines = [tool_use("cd /tmp && ssh host uptime && scp a host:b")]
        ssh, _ = count_agent_calls(lines)
        self.assertEqual(ssh, 2)

    def test_malformed_lines_skipped(self):
        ssh, snap = count_agent_calls(["not json", "{bad", ""])
        self.assertEqual((ssh, snap), (0, 0))


if __name__ == "__main__":
    unittest.main()
