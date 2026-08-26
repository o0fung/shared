"""Streaming gait-cycle segmentation using the recorded UPDATE gait model."""

from __future__ import annotations

from dataclasses import dataclass, field
from math import exp, log
from statistics import median
from typing import Iterable


STATE_NAMES = {
    0: "FAILSAFE",
    1: "INIT_CONTACT",
    2: "STANCE",
    3: "STANCE_GYRO",
    4: "STANCE_ACCEL",
    5: "PUSH_OFF",
    6: "INIT_SWING",
    7: "MID_SWING",
}
STANCE_STATES = frozenset(range(0, 6))
QUALITY_ACCEPTED = "accepted"
QUALITY_REVIEW = "review"
QUALITY_REJECTED = "rejected"
STEP_TYPE_STANDARD = "standard"
STEP_TYPE_WALK_OUT_0_6_0 = "walk_out_0_6_0"
STEP_CODE_WALK_OUT_0_6_0 = "W060"
SEGMENT_TYPE_FULL_CYCLE = "full_cycle"
SEGMENT_TYPE_TRANSITION_5_TO_0 = "transition_5_to_0"
SEGMENT_CODE_TRANSITION_5_TO_0 = "T50"


@dataclass(frozen=True)
class SegmentationConfig:
    """Structural-validation and patient-specific cluster settings."""

    timing_consistency_tolerance_ms: float = 20
    robust_z_max: float = 3.5
    cluster_log_duration_tolerance: float = 0.35
    cluster_stance_percent_tolerance: float = 10
    cluster_min_cycles: int = 5


@dataclass
class Cycle:
    index: int
    start_row: int
    end_row: int
    start_ms: float | None
    end_ms: float | None
    phase_entry_ms: dict[int, float] = field(default_factory=dict)
    state_path: list[int] = field(default_factory=list)
    accepted: bool = False
    reason: str = ""
    user_decision: str = "auto"
    quality_status: str = QUALITY_REJECTED
    walk_out_pattern: list[int] = field(default_factory=list)
    cluster_size: int | None = None
    cluster_stance_median_ms: float | None = None
    cluster_swing_median_ms: float | None = None
    cluster_stance_percent_median: float | None = None
    segment_type: str = SEGMENT_TYPE_FULL_CYCLE
    follows_t50_transition: bool = False

    @property
    def duration_ms(self) -> float | None:
        if self.start_ms is None or self.end_ms is None:
            return None
        return self.end_ms - self.start_ms

    def phase_duration_ms(self, state: int) -> float | None:
        """Return the dwell of state before its next logical phase."""
        successors = {6: 7, 7: 1_007}
        successor = successors.get(state)
        if successor is None:
            return None
        if state not in self.phase_entry_ms or successor not in self.phase_entry_ms:
            return None
        return self.phase_entry_ms[successor] - self.phase_entry_ms[state]

    @property
    def stance_ms(self) -> float | None:
        start_state = 1 if 1 in self.phase_entry_ms else 0
        if start_state not in self.phase_entry_ms or 6 not in self.phase_entry_ms:
            return None
        return self.phase_entry_ms[6] - self.phase_entry_ms[start_state]

    @property
    def swing_ms(self) -> float | None:
        if 6 not in self.phase_entry_ms or 1_007 not in self.phase_entry_ms:
            return None
        return self.phase_entry_ms[1_007] - self.phase_entry_ms[6]

    @property
    def swing_phase_ms(self) -> float | None:
        """Return INIT_SWING through MID_SWING, excluding confirmation latency."""
        return self.phase_duration_ms(6)

    @property
    def confirmation_wrap_ms(self) -> float | None:
        """Return the MID_SWING-to-contact confirmation latency."""
        return self.phase_duration_ms(7)

    @property
    def stance_percent(self) -> float | None:
        duration = self.duration_ms
        stance = self.stance_ms
        if duration is None or stance is None or duration == 0:
            return None
        return 100 * stance / duration

    @property
    def step_type(self) -> str:
        """Classify observed controller output without changing quality rules."""
        if self.walk_out_pattern == [0, 6, 0]:
            return STEP_TYPE_WALK_OUT_0_6_0
        return STEP_TYPE_STANDARD

    @property
    def step_code(self) -> str | None:
        """Return the compact display code for a non-standard step type."""
        if self.segment_type == SEGMENT_TYPE_TRANSITION_5_TO_0:
            return SEGMENT_CODE_TRANSITION_5_TO_0
        if self.step_type == STEP_TYPE_WALK_OUT_0_6_0:
            return STEP_CODE_WALK_OUT_0_6_0
        return None

    @property
    def has_full_phase_timing(self) -> bool:
        """Return whether this segment can contribute to gait-phase analysis."""
        return self.segment_type == SEGMENT_TYPE_FULL_CYCLE and self.stance_ms is not None and self.swing_ms is not None

    @property
    def walk_out_values(self) -> frozenset[int]:
        """Return the distinct controller outputs used by this cycle."""
        return frozenset(self.walk_out_pattern)


def _float(value: str | None) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except ValueError:
        return None


def _state(value: str | None) -> int | None:
    parsed = _float(value)
    if parsed is None or not parsed.is_integer():
        return None
    return int(parsed)


def _record_walk_out(candidate: Cycle, row: dict[str, str]) -> None:
    """Record the cycle's compressed controller-output pattern."""
    walk_out = _state(row.get("walk_out"))
    if walk_out is not None and (not candidate.walk_out_pattern or candidate.walk_out_pattern[-1] != walk_out):
        candidate.walk_out_pattern.append(walk_out)


def _reject_partial(index: int, start_row: int, end_row: int, reason: str) -> Cycle:
    return Cycle(
        index=index,
        start_row=start_row,
        end_row=end_row,
        start_ms=None,
        end_ms=None,
        accepted=False,
        reason=reason,
    )


def _validate(candidate: Cycle, config: SegmentationConfig) -> tuple[bool, str]:
    checks = (
        ("stance", candidate.stance_ms, True),
        ("swing", candidate.swing_ms, True),
        ("cycle", candidate.duration_ms, True),
        ("confirmation_wrap", candidate.confirmation_wrap_ms, False),
    )
    for name, duration, must_be_positive in checks:
        if duration is None:
            return False, f"missing {name} timing"
        if duration < 0 or (must_be_positive and duration == 0):
            return False, f"invalid {name} duration {duration:.0f} ms"
    duration = candidate.duration_ms
    stance = candidate.stance_ms
    swing = candidate.swing_ms
    if duration is None or stance is None or swing is None:
        return False, "missing timing consistency inputs"
    if abs(duration - stance - swing) > config.timing_consistency_tolerance_ms:
        return False, "cycle duration does not equal stance plus swing"
    return True, ""


def _validate_transition(candidate: Cycle) -> tuple[bool, str]:
    """Validate a 5→0 duration-only transition segment."""
    duration = candidate.duration_ms
    if duration is None or duration <= 0:
        return False, "invalid transition duration"
    return True, "valid 5→0 transition step"


def _robust_z_score(value: float, center: float, mad: float) -> float | None:
    """Return a median-based z-score, or None when the baseline has no spread."""
    if mad == 0:
        return None
    return 0.6745 * (value - center) / mad


def _cluster_metrics(cycle: Cycle) -> tuple[float, float, float]:
    """Return independent timing features for patient-specific clustering."""
    stance = cycle.stance_ms
    swing = cycle.swing_ms
    stance_percent = cycle.stance_percent
    if stance is None or swing is None or stance_percent is None:
        raise ValueError("structurally valid cycle is missing timing metrics")
    return log(stance), log(swing), stance_percent


def _is_cluster_neighbor(
    candidate: tuple[float, float, float],
    reference: tuple[float, float, float],
    config: SegmentationConfig,
) -> bool:
    """Compare duration ratios in log space and phase balance in percentage points."""
    return (
        abs(candidate[0] - reference[0]) <= config.cluster_log_duration_tolerance
        and abs(candidate[1] - reference[1]) <= config.cluster_log_duration_tolerance
        and abs(candidate[2] - reference[2]) <= config.cluster_stance_percent_tolerance
    )


def apply_session_timing_quality(cycles: list[Cycle], config: SegmentationConfig) -> None:
    """Accept the densest patient-specific timing cluster in a recording.

    Complete cycles first vote for locally similar timing neighbours, so slow
    impaired gait can form the dominant baseline without normal-adult bounds.
    The selected cluster then supplies median/MAD scores for every complete
    cycle; structural failures never enter this calculation.
    """
    candidates = [cycle for cycle in cycles if cycle.accepted and cycle.has_full_phase_timing]
    if not candidates:
        return

    features = {cycle.index: _cluster_metrics(cycle) for cycle in candidates}
    neighbor_sets = [
        [other for other in candidates if _is_cluster_neighbor(features[other.index], features[cycle.index], config)]
        for cycle in candidates
    ]
    cluster = max(neighbor_sets, key=len)
    if len(cluster) < config.cluster_min_cycles:
        for cycle in candidates:
            cycle.accepted = False
            cycle.quality_status = QUALITY_REVIEW
            cycle.reason = (
                f"timing cluster unavailable: largest cluster has {len(cluster)} "
                f"of required {config.cluster_min_cycles} cycles"
            )
        return

    cluster_features = [features[cycle.index] for cycle in cluster]
    centers = tuple(median(feature[position] for feature in cluster_features) for position in range(3))
    mads = tuple(
        median(abs(feature[position] - centers[position]) for feature in cluster_features)
        for position in range(3)
    )
    cluster_indexes = {cycle.index for cycle in cluster}
    for cycle in candidates:
        cycle.cluster_size = len(cluster)
        cycle.cluster_stance_median_ms = exp(centers[0])
        cycle.cluster_swing_median_ms = exp(centers[1])
        cycle.cluster_stance_percent_median = centers[2]

        flags: list[str] = []
        for name, value, center, mad in zip(
            ("log_stance_ms", "log_swing_ms", "stance_percent"),
            features[cycle.index],
            centers,
            mads,
        ):
            score = _robust_z_score(value, center, mad)
            if score is None:
                if value != center and cycle.index not in cluster_indexes:
                    flags.append(f"{name} differs from zero-variation cluster")
            elif abs(score) > config.robust_z_max:
                flags.append(f"{name} robust z={score:.1f}")

        if not flags:
            cycle.quality_status = QUALITY_ACCEPTED
            cycle.reason = f"matches patient timing cluster ({len(cluster)} cycles)"
        else:
            cycle.accepted = False
            cycle.quality_status = QUALITY_REVIEW
            cycle.reason = f"timing review required: {'; '.join(flags)}"


def segment_rows(
    rows: Iterable[dict[str, str]],
    config: SegmentationConfig | None = None,
) -> list[Cycle]:
    """Segment rows in one pass; a cycle is emitted only on its 7→1 closing edge."""
    config = config or SegmentationConfig()
    cycles: list[Cycle] = []
    candidate: Cycle | None = None
    last_state: int | None = None
    last_timestamp: float | None = None
    prefix_start_row = 1
    index = 1
    last_row_number = 0

    # A full cycle starts at state 1, or at state 0 immediately after a 5→0
    # transition boundary. States 0–5 remain stance-family states until state 6
    # begins swing and 7 completes it. A 5→0 edge instead emits a duration-only
    # transition step and starts the next full candidate at that state-0 row.
    for row_number, row in enumerate(rows, start=1):
        last_row_number = row_number
        timestamp = _float(row.get("t_ms"))
        state = _state(row.get("walk_state"))
        is_gap = bool(row.get("note")) or timestamp is None or state is None
        if is_gap:
            if candidate is not None:
                candidate.end_row = row_number - 1
                candidate.accepted = False
                candidate.reason = "incomplete cycle crossed a gap or invalid telemetry row"
                cycles.append(candidate)
                index += 1
                candidate = None
            last_state = None
            last_timestamp = None
            prefix_start_row = row_number + 1
            continue

        if last_timestamp is not None and timestamp < last_timestamp:
            if candidate is not None:
                candidate.end_row = row_number - 1
                candidate.accepted = False
                candidate.reason = "incomplete cycle crossed a decreasing timestamp"
                cycles.append(candidate)
                index += 1
                candidate = None
            last_state = None
            prefix_start_row = row_number

        if state not in STATE_NAMES:
            cycles.append(_reject_partial(index, row_number, row_number, f"unexpected walk_state {state}"))
            index += 1
            last_state = None
            last_timestamp = timestamp
            prefix_start_row = row_number + 1
            continue

        if state == last_state:
            if candidate is not None:
                _record_walk_out(candidate, row)
            last_timestamp = timestamp
            continue

        if state == 1:
            if candidate is not None and candidate.state_path[-1] == 7:
                # The next contact is not part of the cycle, but is used to
                # causally confirm that the final MID_SWING phase completed.
                candidate.phase_entry_ms[1_007] = timestamp
                candidate.end_ms = timestamp
                accepted, reason = _validate(candidate, config)
                if accepted and candidate.follows_t50_transition:
                    candidate.accepted = False
                    candidate.quality_status = QUALITY_REVIEW
                    candidate.reason = "full cycle immediately follows T50 transition and requires review"
                else:
                    candidate.accepted = accepted
                    candidate.reason = reason
                    candidate.quality_status = QUALITY_ACCEPTED if accepted else QUALITY_REJECTED
                cycles.append(candidate)
                index += 1
            elif candidate is not None:
                candidate.end_row = row_number - 1
                candidate.accepted = False
                candidate.reason = f"incomplete cycle ended with state 1 after {candidate.state_path}"
                cycles.append(candidate)
                index += 1
            elif prefix_start_row < row_number:
                cycles.append(_reject_partial(index, prefix_start_row, row_number - 1, "incomplete prefix before first state 1"))
                index += 1

            candidate = Cycle(
                index=index,
                start_row=row_number,
                end_row=row_number,
                start_ms=timestamp,
                end_ms=None,
                phase_entry_ms={1: timestamp},
                state_path=[1],
            )
            _record_walk_out(candidate, row)
        elif candidate is not None:
            previous_state = candidate.state_path[-1]
            if state == 0 and previous_state == 5:
                candidate.end_row = row_number - 1
                candidate.end_ms = timestamp
                candidate.segment_type = SEGMENT_TYPE_TRANSITION_5_TO_0
                structurally_valid, reason = _validate_transition(candidate)
                if structurally_valid:
                    candidate.accepted = False
                    candidate.quality_status = QUALITY_REVIEW
                    candidate.reason = "duration-only transition requires review"
                else:
                    candidate.accepted = False
                    candidate.quality_status = QUALITY_REJECTED
                    candidate.reason = reason
                cycles.append(candidate)
                index += 1

                candidate = Cycle(
                    index=index,
                    start_row=row_number,
                    end_row=row_number,
                    start_ms=timestamp,
                    end_ms=None,
                    phase_entry_ms={0: timestamp},
                    state_path=[0],
                    follows_t50_transition=True,
                )
                _record_walk_out(candidate, row)
            elif state in STANCE_STATES and previous_state in STANCE_STATES:
                candidate.state_path.append(state)
                candidate.phase_entry_ms[state] = timestamp
                _record_walk_out(candidate, row)
            elif state == 6 and previous_state in STANCE_STATES:
                candidate.state_path.append(state)
                candidate.phase_entry_ms[6] = timestamp
                _record_walk_out(candidate, row)
            elif state == 7 and previous_state == 6:
                candidate.state_path.append(state)
                candidate.phase_entry_ms[7] = timestamp
                _record_walk_out(candidate, row)
                # A 1→...→7 cycle stays pending until its 7→1 edge confirms
                # the complete swing interval and provides its end timestamp.
                candidate.end_row = row_number
            else:
                candidate.end_row = row_number - 1
                candidate.accepted = False
                candidate.reason = f"illegal transition to {state} after {candidate.state_path}"
                cycles.append(candidate)
                index += 1
                candidate = None
                prefix_start_row = row_number
        else:
            prefix_start_row = min(prefix_start_row, row_number)

        last_state = state
        last_timestamp = timestamp

    if candidate is not None:
        candidate.end_row = last_row_number
        candidate.accepted = False
        candidate.reason = f"incomplete suffix after {candidate.state_path}"
        cycles.append(candidate)
    elif prefix_start_row <= last_row_number:
        cycles.append(_reject_partial(index, prefix_start_row, last_row_number, "incomplete suffix without a cycle start"))
    return cycles
