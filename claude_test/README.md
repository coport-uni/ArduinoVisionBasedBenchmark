# claude_test

Index of debug scripts, one-off experiments, and diagnostic code.

Production-quality tests belong in `tests/`, not here. See CLAUDE.md §3 and
`external/CommonClaude/CLAUDE.md` §3.

Add a row to the table below for every file added to this directory.

| File | Purpose | What was learned |
|------|---------|------------------|
| `smoke_wrappers.py` | Smoke-test wrapper generation, logging, and trial-matrix filtering (Phase 1/2) | Latin-square filter yields 12 Claude trials in order; `ssh.bat` logs and delegates; snap.bat correctly absent in V- |
