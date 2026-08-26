# Gait Cycle Analysis

`gait-analyze` reads an rr_app walk CSV, causally segments gait cycles from
`walk_state`, presents a terminal review table, and writes reviewed and
normalized datasets to `output/`.

## Install

```sh
python3 -m pip install -e .
```

## Run

```sh
gait-analyze segment \
  "data/Joint coordinates/P1 ZGJ/rr_20260821_110517/rr_robot_2309830B93E80DF4383DB3ED73C63267_20260821_110517_01walk.csv"
```

Use `--yes` for a non-interactive run. Override automatic decisions with
`--accept 2,5-7` or `--reject 3`. Timing checks are configurable, for example
`--cluster-min-cycles 5 --robust-z-max 3.5`. Use `--plot-channels` to choose
the normalized overlays, and `--no-plot` to skip only the post-confirmation
normalized-cycle plot. After the first review table, an adjustable Matplotlib
window opens for pan/zoom/save inspection and stays open while you enter
accept/reject index ranges in the terminal. It refreshes with those decisions,
then closes after final confirmation. Use `--no-show-review-plot` for headless
or scripted runs. On macOS, the CLI continues pumping the figure event loop
while it waits for terminal input, so the toolbar stays responsive. Index lists
accept comma-separated ranges; trailing commas such as `12-15,` are allowed.
When a matching `*_cycle_review.json` (or, if needed, `.csv`) already exists
in the mirrored output folder, its manual accept/reject decisions are restored
before the table and review plot open. The analyzer verifies the saved cycle
bounds, timestamps, and state path against the current segmentation; unmatched
decisions are skipped. Automatic decisions are recalculated, and choices made
with the current prompts or `--accept`/`--reject` options take precedence.

## Causal state model

The UPDATE gait model defines states 0–7, but the recorded firmware compresses
stance variants 3 and 4 into state 2 and steady walking normally traces:

```text
1 INIT_CONTACT → 2 STANCE → 5 PUSH_OFF → 6 INIT_SWING → 7 MID_SWING → 1
```

The analyzer reads rows in order and never uses future rows to choose a start.
It only confirms a cycle when the closing `7 → 1` edge arrives. State `0` is
treated as bootstrap/failsafe. A `5 → 0` edge is a separate duration-only
transition step (`T50`) requiring manual review, and state 0
starts the following full cycle. Transition steps do not contribute to
phase-timing clustering or normalized full-cycle plots. Missing telemetry,
`GAP:*` rows, illegal state transitions, incomplete prefix/suffix fragments,
and invalid timing are reported as rejected cycles.

## Timing quality filter

For a homogeneous-speed recording, the analyzer rejects only structural
failures: incomplete/illegal state paths, telemetry gaps, invalid timestamps,
missing phase timing, or inconsistent timing arithmetic. Every structurally
complete cycle then participates in a session-specific dominant timing-cluster
search. The cluster center uses median/MAD values of log stance duration, log
swing duration, and stance percentage; matching cycles are accepted and
deviations are marked `review` unless manually accepted. This avoids treating
slow or impaired gait as invalid. `--cluster-min-cycles`,
`--cluster-log-duration-tolerance`, `--cluster-stance-percent-tolerance`, and
`--robust-z-max` tune this behavior.

`swing_ms` includes state 6 through the closing contact. Review artifacts also
separate `swing_phase_ms` (state 6 to state 7) from
`confirmation_wrap_ms` (state 7 to closing contact), so controller confirmation
latency is not mistaken for the swing phase.

## Step types

Each review record includes a `step_type` and the compressed `walk_out_pattern`.
The standard pattern in the current recording is `0→6→1→3`. A valid cycle
with the distinct `0→6→0` pattern is labeled `walk_out_0_6_0`; it remains
subject to the same timing-quality rules as standard cycles. Its compact
table/plot code is `W060`.

## Output

Artifacts mirror the input CSV's parent directory beneath `data/`. For example:

```text
data/Joint coordinates/P1 ZGJ/rr_20260821_110517/walk.csv
output/Joint coordinates/P1 ZGJ/rr_20260821_110517/walk_cycle_review.csv
```

For an input named `walk.csv`, its matching directory under `output/` contains:

- `walk_cycle_review.csv` and `.json`: all candidate cycles, phase timing,
  quality status, auto/user decision, and rejection/review reason.
- `walk_trial_review.png`: full-trial tilt, gyro-z, torque, position, output,
  and state traces. Each cycle is shaded (green accepted, red rejected) and
  labeled with the matching terminal review-table index. It opens after the
  initial terminal table and remains open during terminal acceptance overrides;
  PNG export remains available if no interactive backend exists.
- `walk_normalized_cycles.csv`: accepted numeric telemetry on a 0–100% grid
  (101 samples by default). Continuous values are linearly interpolated;
  state and identifier-like fields use nearest samples.
- `walk_normalized_cycles.png`: white-background stacked overlays and mean for
  selected channels.

The input CSV is never modified or copied. CSV inputs must be located under
`data/`.
