# Purpose: one-off splice of the adjacent-pair replay body into
# judge_t1._stage4 (ruff reformatting made Edit-tool matching brittle).
from pathlib import Path

path = Path("harness/judge_t1.py")
src = path.read_text(encoding="utf-8")

start_marker = '        payload_off = {"entity_id": self.entity_id}'
end_marker = '        self._call_light_service("turn_off", payload_off)'

start = src.index(start_marker)
end = src.index(end_marker, start) + len(end_marker)
body = Path("claude_test/_replay_body.txt").read_text(encoding="utf-8")
path.write_text(src[:start] + body + src[end:], encoding="utf-8")
print("spliced", start, end)
