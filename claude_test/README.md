# claude_test

Index of debug scripts, one-off experiments, and diagnostic code.

Production-quality tests belong in `tests/`, not here. See CLAUDE.md §3 and
`external/CommonClaude/CLAUDE.md` §3.

Add a row to the table below for every file added to this directory.

| File | Purpose | What was learned |
|------|---------|------------------|
| `smoke_wrappers.py` | Smoke-test wrapper generation, logging, and trial-matrix filtering (Phase 1/2) | Latin-square filter yields 12 Claude trials in order; `ssh.bat` logs and delegates; snap.bat correctly absent in V- |
| `find_rgb_led.py` | Locate the cycling RGB LED via burst capture + per-pixel change ranking | Exposure flicker and moving hands defeat naive change detection; color-difference (R-G, R-B range) metrics are needed; the "RGB LED" turned out to be the board's built-in LED3 (active-low), not an external one |
| `verify_led_matrix.py` | Locate the LED matrix (phase-marked blink) and classify LED3 per frame | Matrix at [448,192,484,218]; LED3 at [434,233,460,258]; matrix reflection on the glossy monitor mimics an LED and must be excluded by y-bound |
| `verify_diff_classifier.py` | Accuracy check of `dominant_color_diff` on a 12-frame burst | 12/12 with hue bands red~352 / green~125 / blue~185; the LED core blows out white so absolute HSV classification fails — baseline-differential hue is required |
| `inspect_trial_frames.py` | Diagnose the T1_CLD_VP_r1 s4 mismatch: classify judge frames, zoom LED area, read agent model from stream-json | Frames were correct (green/blue clearly lit); the classifier failed because the 11-minute-old trial baseline drifted (ambient hue ~33 overwhelmed the LED); agent model was claude-fable-5 (CLI default, not pinned) |
| `refit_led_region.py` | Compare region sizes and baseline strategies against the misjudged trial frames | An edge-min pseudo-baseline recovers red/blue; green stays weak because the blown-out core is bright in all colour frames — a true off-edge frame is the right baseline, now captured by the poller |
| `test_replay_judge.py` | Exercise the stage-4 verification replay against a live post-trial board (agent HA + token + entity) without a full trial | Replay timing is deterministic (red verdict correct instantly); revealed the round-3 agent stack renders green/blue as white — a legitimate FT5, confirmed against the reference sketch |
| `analyze_replay_frames.py` | Per-channel diff statistics (top-10/25/50 by sum) of replay frames vs the off baseline | Agent green/blue diffs are achromatic with the RED channel highest — physically white output, not a classifier artifact |
| `test_chroma_ranking.py` | Try chroma-ranked pixel selection as an alternative classifier | Chroma ranking cannot recover colour that is not there; led to the expected-channel margin test (median of 3 captures) as the robust secondary signal |
| `probe_bridge_rpc.py` | Drive the agent's `set_rgb` Bridge RPC directly (bypassing HA/MQTT) with camera verification per channel | Proved the agent implementation correct (red +61 / green +6.8 / blue +8.8) — the "white LED" verdict was a harness artifact, leading to the FT5→FT8 reclassification |
| `_replay_body.txt` + `_splice_replay.py` | One-off splice of the adjacent-pair replay body into `judge_t1._stage4` | Ruff reformatting makes Edit-tool string matching brittle on large blocks; splice-by-marker is the reliable fallback |
| `_reclassify_r3.py` | One-off operator reclassification of `T1_CLD_VP_r1` FT5→FT8 (void) with manifest regeneration | Operator classification edits are the sanctioned post-trial mutation (FR7); the manifest must be regenerated afterwards |
| `_classify_t2_r1.py` | Operator classification of `T2_CLD_VP_r1` as FT5 | Agent built a working bridge→matrix path but the real detection loop never fired; the physical stages (matrix delta ~0.011 vs 0.25) caught what the agent-forgeable log stages could not |
| `live_margin_check.py` | Measure per-colour expected-channel margins against the free-running qtest_rgb cycle at the current camera position | Confirms optical separation before a run; the 2026-07-21 reposition gave red +100 / green +26 / blue +21 (vs morning +7/+2/+5), well clear of the floor -- optics, not code, gated the morning failures |
