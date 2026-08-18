"""Streaming gait-cycle segmentation using the recorded UPDATE gait model."""

from __future__ import annotations

from dataclasses import dataclass, field
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
EXPECTED_STATES = (1, 2, 5, 6, 7)


@dataclass(frozen=True)
class SegmentationConfig:
    """Durations are inclusive validation limits in milliseconds."""

    contact_min_ms: float = 360
    contact_max_ms: float = 1_000
    stance_min_ms: float = 160
    stance_max_ms: float = 9_000
    push_off_min_ms: float = 0
    push_off_max_ms: float = 260
    init_swing_min_ms: float = 20
    init_swing_max_ms: float = 560
    cycle_min_ms: float = 1_200
    cycle_max_ms: float = 10_000
    wrap_max_ms: float = 2_000


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

    @property
    def duration_ms(self) -> float | None:
        if self.start_ms is None or self.end_ms is None:
            return None
        return self.end_ms - self.start_ms

    def phase_duration_ms(self, state: int) -> float | None:
        """Return the dwell of state before its next logical phase."""
        successors = {1: 2, 2: 5, 5: 6, 6: 7, 7: 1_007}
        successor = successors[state]
        if state not in self.phase_entry_ms or successor not in self.phase_entry_ms:
            return None
        return self.phase_entry_ms[successor] - self.phase_entry_ms[state]

    @property
    def stance_ms(self) -> float | None:
        contact = self.phase_duration_ms(1)
        stance = self.phase_duration_ms(2)
        if contact is None or stance is None:
            return None
        return contact + stance

    @property
    def swing_ms(self) -> float | None:
        push_off = self.phase_duration_ms(5)
        init_swing = self.phase_duration_ms(6)
        if push_off is None or init_swing is None:
            return None
        return push_off + init_swing


def _float(value: str | None) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except ValueError:
        return None


def _state(value: str | None) -> int | None:
    parsed = _float(value)
    if parsed is None or not parsed.is_integer():
        return None
    raw_state = int(parsed)
    return 2 if raw_state in (3, 4) else raw_state


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
    if candidate.state_path != list(EXPECTED_STATES):
        return False, f"abnormal state path {candidate.state_path}; expected {list(EXPECTED_STATES)}"

    checks = (
        ("contact", candidate.phase_duration_ms(1), config.contact_min_ms, config.contact_max_ms),
        ("stance", candidate.phase_duration_ms(2), config.stance_min_ms, config.stance_max_ms),
        ("push_off", candidate.phase_duration_ms(5), config.push_off_min_ms, config.push_off_max_ms),
        ("init_swing", candidate.phase_duration_ms(6), config.init_swing_min_ms, config.init_swing_max_ms),
        ("cycle", candidate.duration_ms, config.cycle_min_ms, config.cycle_max_ms),
        ("confirmation_wrap", candidate.phase_duration_ms(7), 0, config.wrap_max_ms),
    )
    for name, duration, minimum, maximum in checks:
        if duration is None:
            return False, f"missing {name} timing"
        if not minimum <= duration <= maximum:
            return False, f"{name} {duration:.0f} ms outside {minimum:.0f}–{maximum:.0f} ms"
    return True, ""


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

    # The candidate progresses only when a state changes. This permits streaming:
    # each row updates current state, and only the observed 7→1 edge finalizes
    # the preceding cycle. Gaps and illegal edges discard pending state safely.
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
            last_timestamp = timestamp
            continue

        if state == 1:
            if candidate is not None and candidate.state_path == list(EXPECTED_STATES):
                # The next contact is not part of the cycle, but is used to
                # causally confirm that the final MID_SWING phase completed.
                candidate.phase_entry_ms[1_007] = timestamp
                accepted, reason = _validate(candidate, config)
                candidate.accepted = accepted
                candidate.reason = reason
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
        elif candidate is not None:
            expected_next = EXPECTED_STATES[len(candidate.state_path)] if len(candidate.state_path) < len(EXPECTED_STATES) else None
            if state == expected_next:
                candidate.state_path.append(state)
                candidate.phase_entry_ms[state] = timestamp
                if state == 7:
                    # A 1→...→7 cycle ends at MID_SWING entry. It is retained
                    # until the next 7→1 edge proves the stream can continue.
                    candidate.end_row = row_number
                    candidate.end_ms = timestamp
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
