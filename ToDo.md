# ToDo.md

> Append-only task history. Never overwrite or reorder existing entries.
> See CLAUDE.md §1 and external/CommonClaude/CLAUDE.md §4.

## Active Tasks

- [ ] CLD_VP production run (6 trials, operator-approved 2026-07-20).
      Results so far: T1_CLD_VP_r1 SUCCESS (17.7 min, $4.92, replay
      margins red +70 / green +9.5 / blue +5.1); T2_CLD_VP_r1 FT5 --
      agent built a working bridge->matrix path and an onnxruntime
      yolov8n pipeline but the real detection loop never fired
      (events.log empty, matrix delta ~0.011 vs 0.25 across 24
      checks); the physical stages caught what the agent-forgeable
      log stages could not. r2/r3 (T1+T2) continuing unattended.
      Two harness findings this run: (a) ssh_calls under-counted
      because the agent uses Git Bash where .bat wrappers are not on
      PATH -- fixed by emitting POSIX-script wrappers alongside .bat
      (verified: Git Bash `ssh` now logs to ssh_calls.log); (b) T2
      needs a longer timeout budget (agent spent ~45 min on
      ultralytics->onnxruntime pivot + disk cleanup).

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
- [x] Test-drive round 3 evaluated (issue #1): unattended completion,
      FT8 = 0. Agent (claude-sonnet-5) met s1 (~12 min), s2, s3;
      21 min, $4.05 (46k output + 9.6M cache-read tokens), 6 snap
      calls. Stage 4 failed and the failure is LEGITIMATE (FT5): the
      agent's HA stack physically renders green/blue as white on LED3
      — confirmed by a control run of the reference sketch showing
      true green/blue in the same ambient light. Machine verdict
      matches visual inspection (PQ2 concordance).
- [x] Stage 4 redesigned as a verification replay (operator-approved
      SPEC FR4-4 deviation): after s3, the judge drives the
      agent-created entity through red/green/blue itself using the
      agent-saved token (brightness 255, judge-controlled timing,
      3 captures per colour) and accepts on majority hue verdict OR
      median expected-channel margin >= 6. This removes the
      SSH-poll/capture timing race that made demo-edge frames land
      outside 3 s colour holds. Agent-white output cleanly rejected
      (median margins green 2.1 / blue 0.2 vs red 47.6).
- [x] CORRECTION of the round-3 verdict (issue #1): the user
      challenged the white-LED conclusion and the record trace proved
      the agent implementation CORRECT at every link -- MQTT payloads
      exact (mosquitto_sub), main.py thresholds sound, and direct
      Bridge-RPC drive gives proper per-channel colours (margins red
      +61 / green +6.8 / blue +8.8 on camera). The earlier "white"
      readings were harness artifacts: replay captures raced the
      variable HA->MQTT->RPC latency, and rising afternoon ambient
      light collapsed the green/blue margins (+9 -> +2 within 10
      minutes). Trial reclassified FT5 -> FT8 (void, re-run).
      Replay hardened to adjacent OFF/ON pair differentials with
      brightness-gated readback, but margins remain ambient-limited:
      the fix is OPTICAL (camera closer to the board or reduced
      ambient), not algorithmic.
- [x] T2 judging made fully automatic (operator decision: the clock
      sits permanently in the board camera's view): s3 = matrix lit
      vs trial baseline on every poll, s4 = lit stable >= 10 s later,
      t2_latency = board-internal detected->draw gap; m/c keys are now
      optional evidence hooks and the preflight console-TTY check is
      removed, so T2 runs unattended like T1.

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
