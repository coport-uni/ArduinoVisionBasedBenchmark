"""Aggregation and reporting (FR8): CSV, 2x2 tables, effect sizes.

Statistics stay hand-rolled (SPEC 9 bans statistics libraries): pooled
Cohen's d and a normal-approximation sample-size formula with named z
constants. With GLM cells absent the 2x2 degrades to a per-task V+/V-
comparison and model columns render as pending.

Usage:
    python -m harness.report [--results DIR] [--out DIR]
"""

import argparse
import csv
import json
import math
import re
import sys
from pathlib import Path

# Canonical trial-dir name, e.g. T1_CLD_VP_r2. Archived retries are
# suffixed (`..._void_<timestamp>`) and must NOT be aggregated -- an
# archived partial can still carry status="complete".
TRIAL_DIR_RE = re.compile(r"^T[12]_[A-Z]{3}_V[PM]_r\d+$")

Z_ALPHA_2 = 1.959964  # two-sided alpha = 0.05
Z_POWER = 0.841621  # power = 0.80

CSV_COLUMNS = [
    "trial_id",
    "task",
    "model",
    "vision",
    "rep",
    "started_at",
    "finished_at",
    "success",
    "failure_type",
    "duration_s",
    "tokens_input",
    "tokens_output",
    "tokens_cache_creation",
    "tokens_cache_read",
    "cost_a_usd",
    "cost_a_reported_usd",
    "cost_b_wh",
    "cost_b_gpu_s",
    "ssh_calls",
    "snap_calls",
    "t2_latency_s",
    "peak_mem_mb",
    "peak_load",
    "clock_skew_s",
    "notes",
]


def load_results(results_dir: Path) -> list[dict]:
    """All complete trial records; FT8/void trials are excluded (FR7)."""
    records = []
    for result_path in sorted(results_dir.glob("*/result.json")):
        if not TRIAL_DIR_RE.match(result_path.parent.name):
            continue  # skip archived retries (T1_CLD_VP_r1_void_...)
        try:
            data = json.loads(result_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if data.get("status") != "complete":
            continue
        records.append(data)
    return records


def flatten(record: dict) -> dict:
    tokens = record.get("tokens") or {}
    flat = {key: record.get(key) for key in CSV_COLUMNS if "tokens_" not in key}
    flat["tokens_input"] = tokens.get("input")
    flat["tokens_output"] = tokens.get("output")
    flat["tokens_cache_creation"] = tokens.get("cache_creation")
    flat["tokens_cache_read"] = tokens.get("cache_read")
    return flat


def write_csv(records: list[dict], out_path: Path) -> None:
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for record in records:
            writer.writerow(flatten(record))


def mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def stdev(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    center = mean(values)
    return math.sqrt(sum((v - center) ** 2 for v in values) / (len(values) - 1))


def cohens_d(group_a: list[float], group_b: list[float]) -> float | None:
    """Pooled-SD Cohen's d (a minus b); None when undefined."""
    if len(group_a) < 2 or len(group_b) < 2:
        return None
    var_a, var_b = stdev(group_a) ** 2, stdev(group_b) ** 2
    pooled = math.sqrt(
        ((len(group_a) - 1) * var_a + (len(group_b) - 1) * var_b)
        / (len(group_a) + len(group_b) - 2)
    )
    if pooled == 0:
        return None
    return (mean(group_a) - mean(group_b)) / pooled


def sample_size_per_cell(observed_sd: float, observed_mean: float) -> int | None:
    """n per cell to detect a 20% -of-mean effect (alpha .05, power .8)."""
    effect = 0.2 * observed_mean
    if effect <= 0 or observed_sd is None:
        return None
    n = 2 * ((Z_ALPHA_2 + Z_POWER) ** 2) * (observed_sd**2) / (effect**2)
    return math.ceil(n)


def _fmt(value, digits=1) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def condition_summary(records: list[dict]) -> list[dict]:
    """Per (task, model, vision) cell: success rate, time, cost, calls."""
    cells: dict[tuple, list[dict]] = {}
    for record in records:
        key = (record["task"], record["model"], record["vision"])
        cells.setdefault(key, []).append(record)
    rows = []
    for (task, model, vision), group in sorted(cells.items()):
        durations = [r["duration_s"] for r in group if r["success"]]
        costs = [r["cost_a_usd"] for r in group if r.get("cost_a_usd") is not None]
        rows.append(
            {
                "task": task,
                "model": model,
                "vision": vision,
                "n": len(group),
                "success_rate": sum(r["success"] for r in group) / len(group),
                "duration_mean": mean(durations),
                "duration_sd": stdev(durations),
                "cost_a_mean": mean(costs),
                "ssh_calls_mean": mean([r.get("ssh_calls", 0) for r in group]),
                "snap_calls_mean": mean([r.get("snap_calls", 0) for r in group]),
            }
        )
    return rows


def two_by_two(records: list[dict], task: str, metric: str = "duration_s"):
    """Cell means + main effects + interaction for one task.

    Uses successful trials' metric. Cells with no data give None and
    effects that need them render as pending in the report.
    """

    def cell(model: str, vision: str) -> list[float]:
        return [
            r[metric]
            for r in records
            if r["task"] == task
            and r["model"] == model
            and r["vision"] == vision
            and r["success"]
            and r.get(metric) is not None
        ]

    claude_vp, claude_vm = cell("claude", "V+"), cell("claude", "V-")
    glm_vp, glm_vm = cell("glm", "V+"), cell("glm", "V-")
    means = {
        ("claude", "V+"): mean(claude_vp),
        ("claude", "V-"): mean(claude_vm),
        ("glm", "V+"): mean(glm_vp),
        ("glm", "V-"): mean(glm_vm),
    }
    vision_effect_claude = cohens_d(claude_vp, claude_vm)
    analysis = {
        "means": means,
        "d_vision_claude": vision_effect_claude,
        "d_vision_glm": cohens_d(glm_vp, glm_vm),
        "d_model_vp": cohens_d(claude_vp, glm_vp),
        "d_model_vm": cohens_d(claude_vm, glm_vm),
        "glm_present": bool(glm_vp or glm_vm),
    }
    # Interaction as difference of differences (means only, small n).
    if all(v is not None for v in means.values()):
        analysis["interaction_dod"] = (
            means[("claude", "V+")] - means[("claude", "V-")]
        ) - (means[("glm", "V+")] - means[("glm", "V-")])
    else:
        analysis["interaction_dod"] = None
    return analysis


def build_markdown(records: list[dict]) -> str:
    lines = ["# Benchmark Report", "", f"Trials aggregated: {len(records)}", ""]

    lines += ["## Per-condition summary", ""]
    lines += [
        "| task | model | vision | n | success | duration mean (s) |"
        " duration sd | cost A ($) | ssh calls | snap calls |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for row in condition_summary(records):
        lines.append(
            f"| {row['task']} | {row['model']} | {row['vision']}"
            f" | {row['n']} | {_fmt(row['success_rate'], 2)}"
            f" | {_fmt(row['duration_mean'])} | {_fmt(row['duration_sd'])}"
            f" | {_fmt(row['cost_a_mean'], 4)}"
            f" | {_fmt(row['ssh_calls_mean'])}"
            f" | {_fmt(row['snap_calls_mean'])} |"
        )
    lines.append("")

    for task in ("T1", "T2"):
        analysis = two_by_two(records, task)
        lines += [f"## {task} 2x2 analysis (build duration, s)", ""]
        means = analysis["means"]
        lines += [
            "| | V+ | V- |",
            "|---|---|---|",
            f"| claude | {_fmt(means[('claude', 'V+')])}"
            f" | {_fmt(means[('claude', 'V-')])} |",
            f"| glm | {_fmt(means[('glm', 'V+')])} | {_fmt(means[('glm', 'V-')])} |",
            "",
            f"- Vision effect (claude), Cohen's d:"
            f" {_fmt(analysis['d_vision_claude'], 2)}",
        ]
        if analysis["glm_present"]:
            lines += [
                f"- Vision effect (glm), Cohen's d:"
                f" {_fmt(analysis['d_vision_glm'], 2)}",
                f"- Model effect (V+), Cohen's d: {_fmt(analysis['d_model_vp'], 2)}",
                f"- Model effect (V-), Cohen's d: {_fmt(analysis['d_model_vm'], 2)}",
                f"- Interaction (difference of differences):"
                f" {_fmt(analysis['interaction_dod'])}",
            ]
        else:
            lines += [
                "- Model effect: n/a (GLM pending)",
                "- Interaction: n/a (GLM pending)",
            ]
        lines.append("")

    lines += ["## Sample size estimate (main experiment)", ""]
    durations = [r["duration_s"] for r in records if r["success"]]
    duration_sd = stdev(durations)
    duration_mean = mean(durations)
    if duration_sd is not None and duration_mean:
        n = sample_size_per_cell(duration_sd, duration_mean)
        lines += [
            f"- Observed duration mean {duration_mean:.0f}s, sd {duration_sd:.0f}s",
            f"- Reps per cell to detect a 20% effect (alpha 0.05, power 0.8): **{n}**",
        ]
    else:
        lines.append("- insufficient successful trials for an estimate")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", default=None)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    from harness.config import load_config

    config = load_config()
    results_dir = Path(args.results) if args.results else config.results_dir
    out_dir = Path(args.out) if args.out else results_dir

    records = load_results(results_dir)
    if not records:
        print("no complete trials found")
        return 1
    out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(records, out_dir / "all_results.csv")
    (out_dir / "report.md").write_text(build_markdown(records), encoding="utf-8")
    print(f"wrote {out_dir / 'all_results.csv'} and {out_dir / 'report.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
