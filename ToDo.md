# ToDo.md

> Append-only task history. Never overwrite or reorder existing entries.
> See CLAUDE.md §1 and external/CommonClaude/CLAUDE.md §4.

## Active Tasks

- [ ] Test-drive round 3 of trial `T1_CLD_VP_r1` is running in the
      background (agent claude-sonnet-5, started 2026-07-20 13:59 KST,
      up to 1 h + 120 s grace). On completion: evaluate `result.json`
      (stage timestamps, tokens, cost), verify the machine verdict
      against the judge frames, and record the outcome in ToDo.md and
      issue #1. Runner logs: `results/testdrive_t1_run3.log`.
- [ ] Implement the UNO Q pilot benchmark harness per `docs/SPEC.md` with the
      approved plan deviations: board access is SSH-only (adb retired after
      initial setup), Claude conditions (CLD_VP/CLD_VM, 12 trials) run now with
      GLM deferred behind a config gate, no dry-run mocks (real board/camera
      with mandatory preflight before every run), FR2 reset preserves only
      Wi-Fi/SSH access, and T2 mandates YOLOv8 nano on the board camera.
      Phases: (0) host bootstrap `tools/setup_host.py` + CLAUDE.md per-path
      language rules + `.gitignore` Python/results entries, (1) `board.py` /
      `wrappers.py` / `preflight.py`, (2) `agents.py` / `runner.py` skeleton,
      (3) `vision.py` / `calibrate.py`, (4) judges, (5) `monitor.py` /
      `cost.py`, (6) `report.py`, (7) integration rehearsal, (8) 12 Claude
      trials. Prompt files stay DRAFT until operator confirmation
      (see LP §3 Q1: guard hook deps; LP §2 G2/G4: stage explicit paths).

## Completed

- [x] Harness phases 0-6 implemented and verified (issue #1, branch
      `feat/benchmark-harness`): host bootstrap (`tools/setup_host.py`,
      Python 3.12 / ffmpeg / ruff installs, SSH key registered on the
      board, passwordless sudo verified), SSH board layer with
      forbidden-pattern guard, per-run preflight (all checks PASS on
      the live board), agent runner with resume, T1/T2 judges,
      monitors, cost, report, 32 unit tests, prompt files confirmed
      by the operator.
- [x] Real-hardware calibration (issue #1): LED3 is the built-in
      active-low RGB LED — added baseline-differential hue classifier
      (12/12 on a live burst) and brightness-delta matrix metric
      (white housing defeats absolute ratios); led_regions calibrated
      to rgb_led [434,233,460,258], matrix [448,192,484,218].
- [x] T2 task variant per operator decision (issue #1): YOLOv8n COCO
      "clock" detection of an LED desk clock replaces person
      detection; prompts, judge events (clock_detected), and tests
      renamed.
- [x] FR2 reset corrected to factory-state restoration (issue #1):
      keep Docker engine + App Lab base images (App Lab requires
      them), reflash a blank sketch each reset (MCU sketches outlive
      stopped containers), and remove leftover `ha-mcu-bridge` /
      `qtest_blink` apps from the board to prevent T1 answer leakage;
      apps baseline re-snapshotted (now only `qtest_blank`).
- [x] Test drive started: trial `T1_CLD_VP_r1` running end-to-end in
      the background with a progress monitor attached.
- [x] Test-drive round 1 debrief (issue #1): the agent (claude-fable-5,
      the unpinned CLI default) completed the T1 task in ~11 minutes
      (HA up, LED3 light entity, token saved, demo observed — s1-s3
      met), but the harness misjudged stage 4 (stale trial baseline
      vs lighting drift) and crashed in teardown (threading.Thread
      `_stop` attribute collision). Fixed: `_stop` renamed to
      `_stop_event` in monitor/poller threads; stage 4 now prefers the
      off-edge frame captured right after the demo as its baseline;
      CLD condition pinned to `claude-sonnet-5` via
      `models.claude.env.ANTHROPIC_MODEL` (operator decision).
- [x] Runner ordering fix: run a cleanup reset BEFORE preflight so a
      previous trial's leftover Home Assistant cannot fail the FR1
      port-8123 gate that reset exists to satisfy. Test-drive round 2
      relaunched with unbuffered logging.

- [x] Add CommonClaude as a submodule at `external/CommonClaude` and apply its
      conventions to this project (`git init`, `.claude/` hooks and settings,
      `.clang-format`, project `CLAUDE.md`, `ToDo.md`, `claude_test/`,
      `.gitignore`).
- [x] Bring the Uno Q onto Wi-Fi from the Windows host over ADB, and document
      the procedure as a reproducible runbook at
      `docs/uno_q_adb_wifi_setup.md`.
- [x] Install the GitHub CLI (`gh` 2.96.0) on the Windows host. `git` 2.51.0 was
      already present.

## Blocked

- [ ] Complete `gh auth login` (interactive browser OAuth — user action), then
      create the remote repository and adopt the CLAUDE.md §4 issue/branch/PR
      flow. Blocked on the repository having no remote and no commits.
      — Resolved 2026-07-20: `gh` is authenticated as coport-uni and the
      remote `origin` points at coport-uni/ArduinoVisionBasedBenchmark.
