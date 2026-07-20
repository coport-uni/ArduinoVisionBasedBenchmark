"""Agent process management: prompt assembly, environment, lifecycle.

The agent runs `claude -p` with stream-json output. Its stdout is
preserved raw (NFR2) and parsed incrementally for usage data; judging
never reads it (NFR1). Kill always takes the whole process tree via
taskkill /T so wrapper-spawned children die too (FR3).
"""

import os
import subprocess
import threading
from pathlib import Path

from harness.util import append_line, now_iso

SNAP_PLACEHOLDER = "{SNAP_CLAUSE}"


def build_prompt(task: str, vision: str, prompts_dir: Path) -> str:
    """Assemble the trial prompt from base + optional snap clause.

    V+ substitutes snap_clause.txt at the placeholder; V- removes the
    placeholder line entirely. Everything else must be byte-identical
    between the two variants (SPEC 1.3) -- enforced by
    verify_prompt_pair below, which the runner calls each trial.
    """
    base = (prompts_dir / f"{task}_base.txt").read_text(encoding="utf-8")
    if SNAP_PLACEHOLDER not in base:
        raise ValueError(f"{task}_base.txt lacks {SNAP_PLACEHOLDER}")
    if vision == "V+":
        clause = (prompts_dir / "snap_clause.txt").read_text(encoding="utf-8")
        return base.replace(SNAP_PLACEHOLDER, clause.strip())
    lines = [line for line in base.splitlines() if SNAP_PLACEHOLDER not in line]
    return "\n".join(lines) + ("\n" if base.endswith("\n") else "")


def verify_prompt_pair(task: str, prompts_dir: Path) -> None:
    """Assert V+/V- prompts differ only around the snap clause.

    Removing the snap clause from the V+ variant must reproduce the
    V- variant exactly; anything else means the base file leaks
    condition-dependent content.
    """
    v_plus = build_prompt(task, "V+", prompts_dir)
    v_minus = build_prompt(task, "V-", prompts_dir)
    clause = (prompts_dir / "snap_clause.txt").read_text(encoding="utf-8").strip()
    lines_without_clause = []
    clause_lines = clause.splitlines()
    plus_lines = v_plus.splitlines()
    index = 0
    while index < len(plus_lines):
        if plus_lines[index : index + len(clause_lines)] == clause_lines:
            index += len(clause_lines)
            continue
        lines_without_clause.append(plus_lines[index])
        index += 1
    if lines_without_clause != v_minus.splitlines():
        raise ValueError(f"{task} V+/V- prompts differ outside the snap clause")


def build_env(
    config, model: str, wrapper_dir: Path, log_path: Path | None = None
) -> dict[str, str]:
    """Agent environment: wrapper dir first on PATH + model env merge.

    Only env var *names* are logged (NFR3).
    """
    env = dict(os.environ)
    env["PATH"] = str(wrapper_dir) + os.pathsep + env.get("PATH", "")
    model_env = config["models"][model].get("env", {})
    env.update(model_env)
    if log_path is not None:
        merged_names = ", ".join(sorted(model_env.keys())) or "(none)"
        append_line(
            log_path,
            f"{now_iso()} agent env: model={model}"
            f" merged_keys=[{merged_names}] wrapper_dir={wrapper_dir}",
        )
    return env


def build_agent_command(config, prompt: str) -> list[str]:
    """The claude CLI invocation for one trial (FR3)."""
    cmd = [
        config["claude_path"],
        "-p",
        prompt,
        "--dangerously-skip-permissions",
        "--output-format",
        "stream-json",
        "--verbose",
    ]
    if not config.get("web_search_allowed", False):
        cmd += ["--disallowedTools", "WebSearch,WebFetch"]
    return cmd


class AgentProcess:
    """One running agent with raw stdout capture and tree-kill."""

    def __init__(
        self,
        command: list[str],
        env: dict[str, str],
        cwd: Path,
        stdout_path: Path,
    ):
        self._stdout_path = stdout_path
        self._lines: list[str] = []
        self._lines_lock = threading.Lock()
        self._proc = subprocess.Popen(
            command,
            env=env,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
        self._reader = threading.Thread(target=self._drain, daemon=True)
        self._reader.start()

    def _drain(self) -> None:
        assert self._proc.stdout is not None
        with self._stdout_path.open("a", encoding="utf-8") as fh:
            for line in self._proc.stdout:
                fh.write(line)
                fh.flush()
                with self._lines_lock:
                    self._lines.append(line)

    @property
    def pid(self) -> int:
        return self._proc.pid

    def poll(self) -> int | None:
        """Exit code, or None while still running."""
        return self._proc.poll()

    def lines_snapshot(self) -> list[str]:
        """Copy of stdout lines seen so far (for usage parsing only)."""
        with self._lines_lock:
            return list(self._lines)

    def kill_tree(self) -> None:
        """Terminate the agent and every descendant (FR3)."""
        if self._proc.poll() is None:
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(self._proc.pid)],
                capture_output=True,
                timeout=30,
            )
        self._reader.join(timeout=10)
