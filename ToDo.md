# ToDo.md

> Append-only task history. Never overwrite or reorder existing entries.
> See CLAUDE.md §1 and external/CommonClaude/CLAUDE.md §4.

## Active Tasks

- [ ] T1 CLD run COMPLETE (2026-07-21, recalibrated camera). 5/6 valid
      successes; VP_r3 = FT8 void (optical, re-run). all_results.csv +
      report.md generated.
      Per-condition (successful trials): V+ n=2 success 1.00, duration
      720 s mean; V- n=3 success 1.00, duration 667 s mean; vision
      effect (Cohen's d) 0.36. snap: V+ 4/trial, V- 0 (condition
      manipulation clean). Sample-size estimate: 15 reps/cell for a
      20% effect. Two report bugs fixed: load_results was globbing
      `*_void_*` archives (an archived partial carried status=complete
      and inflated V+ to n=3 success 0.67) -- now filtered to
      canonical trial-dir names; VP_r3 classified FT8 after direct
      drive of its surviving entity confirmed the RGB light works
      (red +78 / blue +8.8 / green +3.5, green just below the +4 floor
      as afternoon ambient rose to off_level ~300).
      REMAINING for a full T1 dataset: re-run VP_r3 under favourable
      light (or camera closer).

- [ ] T2 target class change required (pre-flight 2026-07-21):
      yolov8n does NOT detect the LED 7-segment desk clock as COCO
      "clock" (only chair/couch/mouse at low conf) -- COCO clock is
      trained on analog clocks. The board camera sees the clock
      clearly ("17:08"), so it's a class-mismatch, not a visibility
      problem: every T2 trial would fail at s1 regardless of agent
      skill. Recommended retarget: cell phone (top-reliability COCO
      class, easy to place); alternatives person (original SPEC) or an
      analog clock. AWAITING operator to place the object in the board
      camera view; then verify detection (test_clock_detection.py) and
      swap the T2 prompt event name + judge class before running.

- [ ] BLOCKED on optics (operator repositioning camera 2026-07-21):
      T1 s4 physical verification is unreliable in strong morning light
      (region off_level ~270 vs ~194 last evening) -- the small LED3
      colour fringe is swamped, so green/blue rises fall below the
      lit-gate. Two contributing factors seen in the frames: (a) bright
      ambient, (b) the turn_off "off" baseline sometimes captured while
      the LED was still blue-lit (variable HA->MQTT->RPC latency).
      GOOD NEWS: the non-interactive prompt fix worked -- the agent now
      runs to completion (s1/s2/s3 met, ssh_calls=46, snap_calls=7, no
      background parking). Hardened the off-baseline (turn_off issued
      twice + wait for a STABLE dark reading before accepting) so a
      still-lit frame can't contaminate the baseline. NEXT: operator
      moves the host camera closer to the board / shades it; then
      RE-CALIBRATE led_regions (LED moves in-frame) via
      claude_test/verify_led_matrix.py or the calibrate tool, and
      re-run `--only T1`.

- [ ] T1-only production run (operator decision 2026-07-21: T2 clock
      detection deferred -- the clock is hard to recognise in the
      board-camera baseline). Running `--only T1` = T1 x {V+, V-} x 3
      = 6 trials in Latin-square order, giving the full T1 half of the
      Claude experiment for the V+/V- vision-feedback main effect
      (PQ6). All four prior fixes are in (non-interactive prompt,
      s3+s4 replay, host-HA reset, ssh/snap metric fallback). T2 to be
      revisited after improving the clock's visibility to the board
      camera.

- [ ] CLD_VP v2 run STOPPED after T1_CLD_VP_r1 failed in 12.8 min with
      all stages null. Two more real-behaviour findings, both fixed;
      run must be RE-STARTED next:
      (1) Agent parked on a background pip-install task and yielded its
      turn -- but `claude -p` is single-shot, so the CLI exited and HA
      was never finished. Fixed in the prompts (common section): a
      paragraph telling the agent it runs in a single non-interactive
      session, must not defer to background tasks, and must run installs
      to completion in the foreground. (Prompt is experiment material;
      this is a harness-fairness fix, not content optimization -- flag
      for operator confirmation.)
      (2) ssh_calls/snap_calls logged 0 despite ~39 ssh commands: the
      POSIX wrappers exist but the Git Bash Bash tool re-orders PATH so
      system ssh/scp win over the wrapper dir. Added a stream-json
      fallback (`cost.count_agent_calls`) that parses Bash tool_use
      commands; runner takes max(wrapper log, parsed) so the metric is
      robust either way. This is FR6 metrics, not NFR1 judging, so
      parsing stdout is allowed. Backfill on the failed trial: (39, 1).
      5 new unit tests (37 total pass).
      NEXT SESSION: operator-confirm the prompt addition, then re-run
      `python -m harness.runner --only CLD_VP` (archives r1_void first).

- [ ] CLD_VP production run RESTARTED with judge/reset fixes
      (operator-approved 2026-07-20). Two mid-run corrections drove the
      restart, both discovered from real trial behaviour:
      (1) T1 stage 3 folded into the stage-4 verification replay --
      passive observation of the agent's one-shot R/G/B/off demo is
      timing-fragile (the demo usually finishes before the state
      poller starts at s2), which false-negatived T1_CLD_VP_r2 even
      though the agent completed the task; s3 now = replay confirms
      RED renders in order, s4 = all three. Operator-approved
      FR4-3/4-4 deviation. r1 (which had passed s3 passively) is
      re-run for comparability.
      (2) FR2 reset gap -- agents install Home Assistant either as a
      Docker container (r1) or a host systemd venv service (r2); the
      old reset only removed the Docker form and its systemd grep
      missed the hyphenated `home-assistant.service`, so a host HA
      survived and answered 8123 into the next trial. Reset now stops
      and disables host HA services (home-?assistant|hass), kills
      stray processes, and removes the venv dirs (verified:
      port_8123_dead True after reset).
      timeout_s raised 3600 -> 5400 (T2 agent spent ~45 min on a
      torch->onnxruntime pivot). Superseded earlier partial results
      (T1_CLD_VP_r1 success, r2 s3 false-negative, T2_CLD_VP_r1 FT5)
      are archived under results/*_void_* and re-collected.

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
