"""Trial orchestration entry point (FR3, FR7, FR9, NFR5).

Usage:
    python -m harness.runner [--only FILTER] [--redo TRIAL_ID]
        [--skip-preflight] [--no-reset] [--reset-only]

Each run: preflight gate -> per-trial FR2 reset -> agent + judge +
monitors -> result.json + SHA-256 manifest. Existing completed trials
are skipped so an interrupted run resumes where it stopped.
"""

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

from harness.agents import (
    AgentProcess,
    build_agent_command,
    build_env,
    build_prompt,
    verify_prompt_pair,
)
from harness.board import make_board
from harness.config import TrialSpec, build_trial_matrix, load_config
from harness.cost import cost_a_usd, cost_b, parse_stream_json
from harness.errors import CaptureError, HarnessError
from harness.judge_t1 import T1Judge
from harness.judge_t2 import T2Judge
from harness.keyboard import KeyListener
from harness.monitor import GpuMonitor, ResourceMonitor
from harness.util import now_iso, write_json_atomic, write_manifest
from harness.vision import capture_frame
from harness.wrappers import count_calls, generate_wrappers

AUTO_FAILURE_TYPES = {"timeout": "FT6", "network_loss": "FT7"}
MANUAL_FAILURE_TYPES = ("FT1", "FT2", "FT3", "FT4", "FT5", "FT8")
STATUS_LINE_INTERVAL_S = 10.0


def trial_done(trial_dir: Path) -> bool:
    """FR9: complete result.json means skip; void (FT8) means re-run."""
    result_path = trial_dir / "result.json"
    if not result_path.exists():
        return False
    try:
        data = json.loads(result_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    return data.get("status") == "complete"


def select_trials(config, only: str | None, redo: str | None):
    trials = build_trial_matrix(config)
    if redo:
        trials = [t for t in trials if t.trial_id == redo]
        if not trials:
            raise HarnessError(f"--redo target not in matrix: {redo}")
        return trials, True
    if only:
        token = only.upper()
        trials = [
            t
            for t in trials
            if token in (t.task, t.condition.condition_id)
            or token in t.condition.condition_id
        ]
        if not trials:
            raise HarnessError(f"--only matched nothing: {only}")
    return trials, False


def classify_failure(judge, timed_out: bool, network_lost: bool) -> str:
    """FT6/FT7 are automatic; anything else asks the operator (FR7)."""
    if network_lost:
        return "FT7"
    if timed_out:
        return "FT6"
    print("trial failed -- select failure type:")
    print("  FT1 environment recognition   FT2 installation")
    print("  FT3 integration layer         FT4 sketch build/deploy")
    print("  FT5 judgment criteria unmet   FT8 harness defect")
    while True:
        answer = input("failure type [FT1/FT2/FT3/FT4/FT5/FT8]: ").strip()
        answer = answer.upper()
        if answer in MANUAL_FAILURE_TYPES:
            return answer


def run_trial(
    config,
    board,
    trial: TrialSpec,
    keys: KeyListener,
    apps_baseline,
    skip_reset: bool = False,
) -> dict:
    """Execute one trial end to end and return its result record."""
    trial_dir = config.results_dir / trial.trial_id
    if trial_dir.exists():
        # Void or partial leftovers: archive rather than overwrite so
        # completed folders stay immutable (NFR2).
        stamp = time.strftime("%Y%m%d_%H%M%S")
        shutil.move(str(trial_dir), f"{trial_dir}_void_{stamp}")
    trial_dir.mkdir(parents=True)

    started_at = now_iso()
    start_monotonic = time.monotonic()

    # FR2 reset before every trial (Wi-Fi and SSH state preserved).
    if not skip_reset:
        reset_log = board.reset(apps_baseline=apps_baseline)
        write_json_atomic(trial_dir / "reset.json", reset_log)
        reset_state = board.verify_reset()
        write_json_atomic(trial_dir / "reset_verify.json", reset_state)

    clock_skew = board.measure_clock_skew()

    baseline_frame = trial_dir / "baseline.jpg"
    try:
        capture_frame(config, baseline_frame, lock_dir=config.results_dir)
    except CaptureError as exc:
        print(f"warning: baseline capture failed: {exc}")

    # Prompt + wrappers + env.
    verify_prompt_pair(trial.task, config.prompts_dir)
    prompt = build_prompt(trial.task, trial.condition.vision, config.prompts_dir)
    (trial_dir / "prompt_used.txt").write_text(prompt, encoding="utf-8")
    wrapper_dir = generate_wrappers(
        trial_dir, trial.condition.vision, config, config.root
    )
    env = build_env(
        config,
        trial.condition.model,
        wrapper_dir,
        log_path=trial_dir / "trial.log",
    )

    # Judge + monitors.
    if trial.task == "T1":
        judge = T1Judge(board, config, trial_dir)
    else:
        judge = T2Judge(
            board,
            config,
            trial_dir,
            clock_skew_s=clock_skew or 0.0,
            baseline_frame=baseline_frame,
        )
    resource_monitor = ResourceMonitor(board, config, trial_dir / "resources.csv")
    resource_monitor.start()
    gpu_monitor = None
    if config["models"][trial.condition.model].get("local", False):
        gpu_monitor = GpuMonitor(config, trial_dir / "gpu.csv")
        gpu_monitor.start()

    # Agent.
    agent_workdir = trial_dir / "agent_home"
    agent_workdir.mkdir()
    agent = AgentProcess(
        build_agent_command(config, prompt),
        env,
        agent_workdir,
        trial_dir / "agent_stdout.jsonl",
    )
    print(f"[{now_iso()}] {trial.trial_id} started (agent pid {agent.pid})")

    # Main loop: judge polling, key marks, termination conditions.
    success = False
    timed_out = False
    network_lost = False
    agent_exit_monotonic: float | None = None
    last_status = 0.0
    poll_interval = config["poll_interval_s"]
    timeout_s = config["timeout_s"]
    grace_s = config["post_exit_grace_s"]
    next_judge_poll = 0.0

    while True:
        now = time.monotonic()
        elapsed = now - start_monotonic

        for key, epoch in keys.drain():
            if key == "q":
                print("operator abort (q)")
                timed_out = True
            else:
                judge.handle_key(key, epoch)

        if now >= next_judge_poll:
            next_judge_poll = now + poll_interval
            try:
                if judge.poll():
                    success = True
                    break
            except HarnessError as exc:
                print(f"judge error: {exc}")
                network_lost = True
                break

        if agent.poll() is not None and agent_exit_monotonic is None:
            agent_exit_monotonic = now
            print(f"[{now_iso()}] agent exited; {grace_s}s grace")

        if timed_out or elapsed >= timeout_s:
            timed_out = True
            break
        if agent_exit_monotonic is not None and now - agent_exit_monotonic >= grace_s:
            break

        if now - last_status >= STATUS_LINE_INTERVAL_S:
            last_status = now
            stages = judge.summary().get("stages", {})
            met = [k for k, v in stages.items() if v]
            waiting = " [m/c marks armed]" if trial.task == "T2" and not success else ""
            print(
                f"[{now_iso()}] {trial.trial_id}"
                f" elapsed={int(elapsed)}s stages={met or 'none'}{waiting}"
            )
        time.sleep(0.2)

    # Teardown.
    agent.kill_tree()
    judge.shutdown()
    resource_monitor.stop()
    if gpu_monitor is not None:
        gpu_monitor.stop()
    resource_monitor.join(timeout=30)
    if gpu_monitor is not None:
        gpu_monitor.join(timeout=30)

    finished_at = now_iso()
    duration_s = int(time.monotonic() - start_monotonic)

    usage = parse_stream_json(agent.lines_snapshot())
    gpu_samples = gpu_monitor.samples if gpu_monitor else []
    wh, gpu_busy_s = cost_b(config, trial.condition.model, gpu_samples)

    failure_type = None
    if not success:
        failure_type = classify_failure(judge, timed_out, network_lost)

    judge_summary = judge.summary()
    result = {
        "trial_id": trial.trial_id,
        "task": trial.task,
        "model": trial.condition.model,
        "vision": trial.condition.vision,
        "rep": trial.rep,
        "started_at": started_at,
        "finished_at": finished_at,
        "success": success,
        "failure_type": failure_type,
        "judge_stages": judge_summary["stages"],
        "duration_s": duration_s,
        "tokens": {
            "input": usage.input,
            "output": usage.output,
            "cache_creation": usage.cache_creation,
            "cache_read": usage.cache_read,
        },
        "cost_a_usd": cost_a_usd(config, trial.condition.model, usage),
        "cost_a_reported_usd": usage.reported_cost_usd,
        "cost_b_wh": wh,
        "cost_b_gpu_s": gpu_busy_s,
        "ssh_calls": count_calls(trial_dir, "ssh_calls.log")
        + count_calls(trial_dir, "scp_calls.log"),
        "snap_calls": count_calls(trial_dir, "snap_calls.log"),
        "t2_latency_s": judge_summary.get("t2_latency_s"),
        "peak_mem_mb": resource_monitor.peak_mem_mb,
        "peak_load": resource_monitor.peak_load,
        "clock_skew_s": clock_skew,
        "status": "void" if failure_type == "FT8" else "complete",
        "notes": "",
    }
    write_json_atomic(trial_dir / "result.json", result)
    write_manifest(trial_dir)
    print(
        f"[{now_iso()}] {trial.trial_id} finished:"
        f" success={success} failure={failure_type} duration={duration_s}s"
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", help="task or condition filter, e.g. T1, CLD_VP")
    parser.add_argument("--redo", help="re-run one trial id")
    parser.add_argument("--skip-preflight", action="store_true")
    parser.add_argument("--no-reset", action="store_true")
    parser.add_argument(
        "--reset-only",
        action="store_true",
        help="run the FR2 board reset and exit",
    )
    args = parser.parse_args()

    config = load_config()
    config.results_dir.mkdir(exist_ok=True)
    board = make_board(config, log_path=config.results_dir / "board.log")

    if args.reset_only:
        outcomes = board.reset()
        for outcome in outcomes:
            flag = "ok" if outcome["ok"] else "FAILED"
            print(f"  [{flag}] {outcome['step']}")
        state = board.verify_reset()
        print(f"post-reset: {state}")
        return 0

    trials, is_redo = select_trials(config, args.only, args.redo)
    tasks = sorted({t.task for t in trials})

    if not args.skip_preflight:
        from tools.preflight import run_preflight

        if run_preflight(config, selected_tasks=tuple(tasks)) != 0:
            print("preflight failed -- refusing to start (FR1)")
            return 1

    baseline_path = config.results_dir / "_baseline" / "apps.json"
    apps_baseline = None
    if baseline_path.exists():
        apps_baseline = json.loads(baseline_path.read_text(encoding="utf-8")).get(
            "apps"
        )

    keys = KeyListener()
    keys.start()
    completed = 0
    try:
        for trial in trials:
            trial_dir = config.results_dir / trial.trial_id
            if not is_redo and trial_done(trial_dir):
                print(f"skip {trial.trial_id} (already complete)")
                continue
            board.ensure_connected()
            run_trial(
                config,
                board,
                trial,
                keys,
                apps_baseline,
                skip_reset=args.no_reset,
            )
            completed += 1
    finally:
        keys.stop()
    print(f"run finished: {completed} trial(s) executed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
