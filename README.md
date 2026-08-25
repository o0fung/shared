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
`--stance-max-ms 3000 --cycle-max-ms 5000`. Use `--plot-channels` to choose
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
treated as bootstrap/failsafe rather than a normal cycle boundary. Missing
telemetry, `GAP:*` rows, illegal state transitions, incomplete prefix/suffix
fragments, and invalid timing are reported as rejected cycles.

## Output

Artifacts mirror the input CSV's parent directory beneath `data/`. For example:

```text
data/Joint coordinates/P1 ZGJ/rr_20260821_110517/walk.csv
output/Joint coordinates/P1 ZGJ/rr_20260821_110517/walk_cycle_review.csv
```

For an input named `walk.csv`, its matching directory under `output/` contains:

- `walk_cycle_review.csv` and `.json`: all candidate cycles, timings,
  auto/user decision, and rejection reason.
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
