# ToDo.md

> Append-only task history. Never overwrite or reorder existing entries.
> See CLAUDE.md §1 and external/CommonClaude/CLAUDE.md §4.

## Active Tasks

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
