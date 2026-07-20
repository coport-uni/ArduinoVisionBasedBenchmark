# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with
code in this repository.

## Overview

ArduinoVisionBenchmark is an Arduino / embedded C++ project. It adopts the
[CommonClaude](https://github.com/coport-uni/CommonClaude) conventions, vendored
as a git submodule at [external/CommonClaude/](external/CommonClaude/).

## 0. Rule Sources and Priority

| Order | Source | Scope |
|---|---|---|
| 1 (wins) | This file | Project-specific overrides |
| 2 | [external/CommonClaude/CLAUDE.md](external/CommonClaude/CLAUDE.md) | Global conventions |
| 3 | [external/CommonClaude/README.md](external/CommonClaude/README.md) | Convention summary |

Per CommonClaude §1, the more-specific context wins. Where this file is silent,
the submodule's `CLAUDE.md` applies verbatim.

Update the pinned conventions with:

```bash
git submodule update --remote external/CommonClaude
```

---

## 1. Inherited Rules (apply as written)

The following CommonClaude sections apply to this project unchanged. Read them
in [external/CommonClaude/CLAUDE.md](external/CommonClaude/CLAUDE.md):

| Section | Rule |
|---|---|
| §3 | Debug File Management — `claude_test/` vs `tests/` |
| §4 | Task Management — `ToDo.md` → user approval → `gh issue create` → branch → PR |
| §5 | Testing Rules — no magic numbers, no hardcoding, quality over passing |
| §7 | Research Before Coding — Serena / Context7 / Fetch MCP servers |
| §8 | Exceptions — `claude_test/` waivers, `ToDo.md` checkbox updates |
| §9, §10 | Learned Patterns — read before drafting `ToDo.md`, append after |
| §11 | Commit Messages — Conventional Commits |
| §12 | Branching Strategy — GitHub Flow, `<type>/<short-description>` |
| §14 | Versioning — SemVer |
| §15 | Pull Request Guidelines |

The English-only rule for code comments, documentation, commit messages, issues,
and PRs (CommonClaude §2 Language) applies here without exception.

---

## 2. Override: Language is C/C++, not Python

CommonClaude's `CLAUDE.md` is written for Python. This project is C/C++, so the
naming, documentation, and linting rules below **replace** CommonClaude §2 and
§6. The MIT CommLab style principles behind them are unchanged — see
[external/CommonClaude/README.md](external/CommonClaude/README.md) §1, which
already states the C form of this table.

### 2.1 Naming

| Element  | Style               | Example                          |
|----------|---------------------|----------------------------------|
| Variable | `snake_case`        | `frame_width`                    |
| Function | `snake_case`        | `capture_frame`                  |
| Type     | `PascalCase` / `_t` | `FrameBuffer` / `frame_buffer_t` |
| Macro    | `UPPER_SNAKE_CASE`  | `MAX_FRAME_BYTES`                |
| Constant | `UPPER_SNAKE_CASE`  | `SETTLE_MID_MS`                  |
| File     | `lower_snake`       | `frame_buffer.c`, `frame_buffer.h` |

Variables and types are nouns; functions are verbs. Name length is proportional
to scope. Avoid abbreviations unless self-explanatory.

### 2.2 Structure

- 80-column limit, 4-space indentation, never tabs.
- One statement per line.
- Operators go on the left of continuation lines.

These are enforced by [.clang-format](.clang-format) (LLVM base, copied from the
submodule).

### 2.3 Documentation

Public functions and types carry Doxygen blocks with `@brief`, `@param`, and
`@return` — this replaces the PEP 257 docstring rule. A comment states **what**
and **why**, never **how**.

```c
/**
 * @brief Capture one frame from the camera into the shared buffer.
 *
 * Non-blocking: returns as soon as the DMA transfer is queued, not
 * when the frame is complete. Poll frame_ready() before reading.
 *
 * @param buf  Destination buffer, at least MAX_FRAME_BYTES long.
 * @return 0 on success, negative errno on transfer setup failure.
 */
int capture_frame(uint8_t *buf);
```

TODO format: `/* TODO: (@owner) description */`

### 2.4 Linting (replaces CommonClaude §6 Ruff)

Before committing, every changed C/C++ file must pass:

```bash
clang-format --dry-run --Werror <file>
cppcheck --enable=warning,style --std=c11 <file>
```

Sketches compile with `arduino-cli compile` before any commit that touches them.

---

## 3. Override: Repository Layout

| Path | Contents |
|---|---|
| `external/CommonClaude/` | Conventions submodule — **read-only**, never edit in place |
| `docs/` | Project documentation |
| `tests/` | Production-quality tests wired into CI |
| `claude_test/` | Debug scripts and one-off experiments (see §3 of CommonClaude) |

Changes to the conventions themselves belong upstream in the CommonClaude
repository, not in `external/CommonClaude/` working copy.

---

## 4. Override: Hooks on Windows

The hooks in [.claude/settings.json](.claude/settings.json) are copied verbatim
from the submodule and are bash scripts that parse their stdin with `jq`.

- `bash` is available via Git Bash.
- **`jq` is not installed on this machine.** Until it is, every hook exits
  non-zero and reports a hook error instead of enforcing its rule. Install with:

  ```powershell
  winget install jqlang.jq
  ```

Note that `post-write-lint.sh` lints Python via `ruff` and is a no-op for `.c`,
`.h`, `.cpp`, and `.ino` files. The C linting in §2.4 is currently a manual
step, not hook-enforced.
