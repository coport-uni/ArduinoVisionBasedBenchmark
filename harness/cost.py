"""Token usage collection and cost formulas A / B (FR6).

Usage comes from the agent's stream-json output. Parse failures leave
tokens null while the raw output stays preserved on disk -- the trial
is never invalidated by a metering problem.
"""

import json
import re
from dataclasses import dataclass

# Count board/snap invocations from the agent's own stream-json as a
# fallback: the PATH wrappers only log when the agent's shell honours
# the prepended wrapper dir, and the Git Bash Bash tool re-orders PATH
# so system ssh/scp win. This is a METRIC (FR6), not judging (NFR1
# forbids stdout only for pass/fail), so parsing stdout is acceptable.
_SSH_CMD_RE = re.compile(r"(?:^|[\s;&|(`])(ssh|scp)\s", re.MULTILINE)
_SNAP_CMD_RE = re.compile(r"(?:^|[\s;&|(`])snap(?:\.bat)?(?:\s|$)", re.MULTILINE)


def count_agent_calls(lines: list[str]) -> tuple[int, int]:
    """(ssh/scp count, snap count) parsed from stream-json tool_use.

    Scans Bash tool_use command strings; used only when the wrapper
    logs under-count (see module note).
    """
    ssh_count = 0
    snap_count = 0
    for line in lines:
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") != "assistant":
            continue
        for block in (event.get("message") or {}).get("content") or []:
            if block.get("type") != "tool_use":
                continue
            command = (block.get("input") or {}).get("command", "")
            if not command:
                continue
            ssh_count += len(_SSH_CMD_RE.findall(command))
            snap_count += len(_SNAP_CMD_RE.findall(command))
    return ssh_count, snap_count


@dataclass
class TokenUsage:
    """Accumulated token counts; None means unparseable."""

    input: int | None = None
    output: int | None = None
    cache_creation: int | None = None
    cache_read: int | None = None
    reported_cost_usd: float | None = None

    @property
    def parsed(self) -> bool:
        return self.input is not None or self.output is not None


def parse_stream_json(lines: list[str]) -> TokenUsage:
    """Extract usage totals from stream-json output lines.

    Sums per-message usage blocks and keeps the final result event's
    totals when present (they are authoritative). All four token
    fields are kept because cached input is priced differently.
    """
    usage = TokenUsage()
    totals = {"input": 0, "output": 0, "cache_creation": 0, "cache_read": 0}
    saw_usage = False
    for line in lines:
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "result":
            final = event.get("usage") or {}
            if final:
                totals["input"] = final.get("input_tokens", totals["input"])
                totals["output"] = final.get("output_tokens", totals["output"])
                totals["cache_creation"] = final.get(
                    "cache_creation_input_tokens", totals["cache_creation"]
                )
                totals["cache_read"] = final.get(
                    "cache_read_input_tokens", totals["cache_read"]
                )
                saw_usage = True
            if "total_cost_usd" in event:
                usage.reported_cost_usd = event["total_cost_usd"]
            continue
        block = (event.get("message") or {}).get("usage")
        if isinstance(block, dict):
            totals["input"] += block.get("input_tokens", 0)
            totals["output"] += block.get("output_tokens", 0)
            totals["cache_creation"] += block.get("cache_creation_input_tokens", 0)
            totals["cache_read"] += block.get("cache_read_input_tokens", 0)
            saw_usage = True
    if saw_usage:
        usage.input = totals["input"]
        usage.output = totals["output"]
        usage.cache_creation = totals["cache_creation"]
        usage.cache_read = totals["cache_read"]
    return usage


def cost_a_usd(config, model: str, usage: TokenUsage) -> float | None:
    """Formula A: token counts x per-model unit prices.

    Claude uses claude_pricing_per_mtok (cache-aware when the config
    provides cache rates); GLM uses its virtual_pricing_per_mtok.
    """
    if not usage.parsed:
        return None
    if model == "claude":
        pricing = config["claude_pricing_per_mtok"]
    else:
        pricing = config["models"][model].get("virtual_pricing_per_mtok")
        if not pricing:
            return None
    cost = (usage.input or 0) * pricing["input"] + (usage.output or 0) * pricing[
        "output"
    ]
    if "cache_write" in pricing:
        cost += (usage.cache_creation or 0) * pricing["cache_write"]
        cost += (usage.cache_read or 0) * pricing["cache_read"]
    return cost / 1_000_000


def cost_b(
    config, model: str, gpu_samples: list[tuple[float, float, float]]
) -> tuple[float | None, float | None]:
    """Formula B: (accumulated Wh, busy seconds) -- local models only.

    @param gpu_samples  (monotonic_time_s, power_w, util_pct) rows.
    @return             (wh, busy_s); (None, None) for API models.
    """
    if not config["models"][model].get("local", False):
        return None, None
    if len(gpu_samples) < 2:
        return 0.0, 0.0
    joules = 0.0
    busy_s = 0.0
    busy_util_floor = config.get("gpu_busy_util_pct", 5.0)
    for (t0, p0, u0), (t1, p1, _u1) in zip(gpu_samples, gpu_samples[1:]):
        dt = t1 - t0
        joules += dt * (p0 + p1) / 2  # trapezoidal integration
        if u0 >= busy_util_floor:
            busy_s += dt
    return joules / 3600.0, busy_s
