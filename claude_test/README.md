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
