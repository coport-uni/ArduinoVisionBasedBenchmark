# ToDo.md

> Append-only task history. Never overwrite or reorder existing entries.
> See CLAUDE.md §1 and external/CommonClaude/CLAUDE.md §4.

## Active Tasks

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
