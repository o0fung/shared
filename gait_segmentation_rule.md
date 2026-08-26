# Mobile Gait Segmentation and Quality Rule

This document specifies a platform-neutral, streaming algorithm for segmenting
gait cycles from mobile telemetry and accepting the dominant patient-specific
gait pattern. It is intended for direct translation to Kotlin, Swift, Dart, or
TypeScript.

## 1. Scope and principles

- Segment cycles causally: do not use future samples to choose a cycle start.
- Reject only structurally invalid telemetry or state paths.
- Do not reject a cycle merely because its timing differs from normal-adult
  gait. Slow, impaired gait may have long stance and short swing.
- Learn the dominant timing cluster separately for each homogeneous session.
- Keep controller-output labels such as `W060` independent from timing quality.

## 2. Required input

Process samples in timestamp order. Each sample needs:

| Field | Type | Meaning |
|---|---|---|
| `t_ms` | integer or floating-point | Monotonic timestamp in milliseconds |
| `walk_state` | integer | Gait state, 0 through 7 |
| `walk_out` | optional integer | Controller output code |
| `is_gap` | boolean | True for missing/corrupt telemetry or an explicit gap |

Treat a missing/non-numeric timestamp or state as `is_gap = true`. Reject the
current partial cycle if a gap occurs before it closes.

## 3. State model

The expected steady-state cycle is:

```text
1 INIT_CONTACT → 0..5 stance-family states → 6 INIT_SWING → 7 MID_SWING → 1 closing contact
```

State names:

| State | Name | Allowed role |
|---:|---|---|
| 0 | FAILSAFE | Starts a full cycle after a `5→0` transition boundary |
| 1 | INIT_CONTACT | Cycle start and closing contact |
| 2 | STANCE | Stance-family state |
| 3 | STANCE_GYRO | Stance-family state |
| 4 | STANCE_ACCEL | Stance-family state |
| 5 | PUSH_OFF | Stance-family state |
| 6 | INIT_SWING | First swing state |
| 7 | MID_SWING | Final required swing state |

The recorded firmware may omit states 3 and 4. Any sequence of stance states is
valid before state 6, except `5→0`, which is a dedicated transition boundary.
Once state 6 has been entered, returning to a stance-family state before a
closing contact is invalid.

## 4. Streaming segmentation

### Cycle boundary rule

1. Start a full-cycle candidate at a transition into state 1, or at the state-0
   sample immediately following a `5→0` boundary.
2. Record the first entry timestamp for state 1, state 6, and state 7.
3. Accept only stance-family transitions while the candidate is in stance.
4. Permit `stance-family → 6`, then only `6 → 7`.
5. The next transition `7 → 1` closes the previous candidate and immediately
   starts the next candidate at that same state-1 sample.
6. A `5→0` edge closes the preceding candidate as a `transition_5_to_0`
   (`T50`) segment for manual review. The state-0 sample starts the next
   full-cycle candidate, which is also sent to manual review if it completes.

The closing state-1 sample confirms timing but does not belong to the previous
cycle's source-row range. It is the first sample of the next candidate.
Likewise, the state-0 boundary sample does not belong to the preceding
transition segment; it starts the following full cycle.

### Structural rejection

Reject a candidate with a specific reason when any of these occurs:

- gap, missing required field, or invalid state inside the candidate;
- timestamp decreases;
- unexpected state outside 0–7;
- illegal state transition;
- a new state 1 before the candidate reaches state 7;
- end of recording before a closing `7 → 1`;
- missing phase entry timestamp;
- negative duration, zero stance/swing/cycle duration, or
  `abs(cycle_ms - stance_ms - swing_ms) > timing_consistency_tolerance_ms`.

Recommended `timing_consistency_tolerance_ms`: `20`.

Do not apply fixed physiological stance, swing, or cycle duration bounds as
default rejection rules.

## 5. Timing definitions

For a completed cycle:

| Metric | Formula |
|---|---|
| `cycle_ms` | `t(closing state 1) - t(start state 1 or boundary state 0)` |
| `stance_ms` | `t(first state 6) - t(start state 1 or boundary state 0)` |
| `swing_ms` | `t(closing state 1) - t(first state 6)` |
| `swing_phase_ms` | `t(first state 7) - t(first state 6)` |
| `confirmation_wrap_ms` | `t(closing state 1) - t(first state 7)` |
| `stance_percent` | `100 * stance_ms / cycle_ms` |
| `swing_percent` | `100 * swing_ms / cycle_ms` |

`swing_ms = swing_phase_ms + confirmation_wrap_ms`. The confirmation wrap is
controller/segmentation latency, not necessarily airborne biomechanical swing.

A `T50` transition segment has only `cycle_ms`: it ends at state 0 and has no
stance/swing phase metrics. It is `review` by default and must be manually
accepted before downstream use; it never contributes to timing-cluster fitting
or full-cycle normalization.

A completed full cycle that immediately follows a `T50` is also `review` by
default. It does not contribute to timing-cluster fitting, but may be manually
accepted before downstream use.

## 6. walk_out pattern and step type

Within the source rows of each cycle, read numeric `walk_out` values and remove
only consecutive duplicates. Store the resulting ordered pattern.

Examples:

| Pattern | `step_type` | `step_code` |
|---|---|---|
| `0→6→1→3` | `standard` | empty |
| `0→6→0` | `walk_out_0_6_0` | `W060` |

`W060` is a display/controller-output label. It must not cause a timing
acceptance or rejection on its own.

## 7. Patient-specific timing cluster

Run this after all structural segmentation is complete for one
homogeneous-speed session.

### Features

For each structurally complete full-phase cycle, calculate:

```text
x1 = ln(stance_ms)
x2 = ln(swing_ms)
x3 = stance_percent
```

Log durations compare proportional differences: a 20% timing change has
similar influence at fast and slow walking speeds.

### Find the initial dominant cluster

For each complete cycle `i`, count every complete cycle `j` that satisfies:

```text
abs(log(stance_i) - log(stance_j)) <= cluster_log_duration_tolerance
abs(log(swing_i)  - log(swing_j))  <= cluster_log_duration_tolerance
abs(stance_percent_i - stance_percent_j) <= cluster_stance_percent_tolerance
```

Choose the cycle with the most neighbours and use its neighbour set as the
initial dominant cluster.

Recommended defaults:

| Parameter | Default | Meaning |
|---|---:|---|
| `cluster_log_duration_tolerance` | 0.35 | Duration ratio of about 1.42 |
| `cluster_stance_percent_tolerance` | 10 | Percentage points |
| `cluster_min_cycles` | 5 | Minimum stable cluster size |
| `robust_z_max` | 3.5 | Outlier threshold |

If the largest cluster has fewer than `cluster_min_cycles`, do not learn a
baseline. Mark all structurally complete cycles as `review` with
`timing cluster unavailable`; do not automatically accept them.

### Robust score and final decision

For the initial cluster, calculate the median `m_k` and MAD:

```text
MAD_k = median(abs(x_k - m_k))
robust_z_k = 0.6745 * (x_k - m_k) / MAD_k
```

For each structurally complete cycle:

1. Set `accepted` when every available feature has
   `abs(robust_z_k) <= robust_z_max`.
2. Set `review` when one or more features exceed the threshold. Store every
   triggering feature and score.
3. If a feature has zero MAD, the cluster has no observed variability in that
   feature. A non-cluster cycle that differs from its center on that feature is
   `review`; an equal value is acceptable.
4. Preserve `rejected` for structural failure or an explicit user rejection.

This lets a high-stance, slow patient form a slow/high-stance cluster and a
normal-speed patient independently form a normal-speed cluster.

## 8. Reference pseudocode

```text
cycles = segment_stream(samples)
complete = cycles where structural_status == valid

if complete is empty:
    return cycles

features = map complete to [ln(stance_ms), ln(swing_ms), stance_percent]
seed_cluster = largest_neighbor_set(features, tolerances)

if size(seed_cluster) < cluster_min_cycles:
    mark every complete cycle REVIEW("timing cluster unavailable")
    return cycles

center = median(seed_cluster.features)
mad = median_absolute_deviation(seed_cluster.features, center)

for cycle in complete:
    flags = robust_score_flags(cycle.features, center, mad, robust_z_max)
    cycle.cluster_size = size(seed_cluster)
    cycle.cluster_center = center
    if flags is empty:
        cycle.status = ACCEPTED
        cycle.reason = "matches patient timing cluster"
    else:
        cycle.status = REVIEW
        cycle.reason = join(flags)
```

## 9. Output record

Persist at least:

```text
cycle_index, start_row, end_row, start_ms, end_ms, state_path,
segment_type, step_type, step_code, walk_out_values, walk_out_pattern,
cycle_ms, stance_ms, swing_ms, swing_phase_ms, confirmation_wrap_ms,
stance_percent, swing_percent,
cluster_size, cluster_stance_median_ms, cluster_swing_median_ms,
cluster_stance_percent_median,
quality_status, accepted, user_decision, reason
```

Status meanings:

| Status | Meaning |
|---|---|
| `accepted` | Structurally valid full-cycle cluster match, or explicit reviewer acceptance |
| `review` | Structurally complete but not a confident cluster match |
| `rejected` | Structurally invalid or explicitly rejected by a reviewer |

Only accepted full-phase cycles should be included in automatic gait-phase
normalization/aggregation. `T50` transition steps remain in the review/count
output but are not normalized, even if manually accepted.
Allow a clinician or reviewer to force accept/reject, preserving that explicit
decision separately from the automatic status.

## 10. Test cases

Validate the mobile implementation with:

1. A valid normal-speed cycle with correct phase durations.
2. A valid slow/high-stance session with at least five similar cycles: all
   should become accepted despite timings outside normal-adult ranges.
3. A fast/normal session: its own dominant cluster should become accepted.
4. A mixed session with one timing outlier: it should become `review`, not
   structural `rejected`.
5. Gap, decreasing timestamp, illegal transition, incomplete prefix, and
   incomplete suffix: each should be `rejected`.
6. A `0→6→0` controller-output sequence: it should receive `W060` while its
   timing decision remains independent.
7. A `1→2→5→0→2→5→6→7→1` sequence: emit a review `T50` transition
   segment and a following full cycle starting at state 0.
