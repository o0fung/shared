from gait_analysis.segmenter import SegmentationConfig, segment_rows


def _row(time_ms: int | None, state: int | None, note: str = "") -> dict[str, str]:
    return {
        "t_ms": "" if time_ms is None else str(time_ms),
        "walk_state": "" if state is None else str(state),
        "note": note,
    }


def test_confirms_valid_cycle_only_at_closing_edge() -> None:
    rows = [_row(0, 1), _row(400, 2), _row(800, 5), _row(900, 6), _row(1200, 7), _row(1220, 1)]
    cycles = segment_rows(rows)
    completed = [cycle for cycle in cycles if cycle.accepted]
    assert len(completed) == 1
    assert completed[0].state_path == [1, 2, 5, 6, 7]
    assert completed[0].stance_ms == 900
    assert completed[0].swing_ms == 320
    assert cycles[-1].reason.startswith("incomplete suffix")


def test_counts_failsafe_as_stance_without_rejecting_cycle() -> None:
    rows = [
        _row(0, 1),
        _row(400, 2),
        _row(800, 5),
        _row(850, 0),
        _row(880, 2),
        _row(900, 5),
        _row(920, 6),
        _row(1200, 7),
        _row(1220, 1),
    ]

    completed = [cycle for cycle in segment_rows(rows) if cycle.accepted]

    assert len(completed) == 1
    assert completed[0].state_path == [1, 2, 5, 0, 2, 5, 6, 7]
    assert completed[0].stance_ms == 920
    assert completed[0].swing_ms == 300


def test_rejects_illegal_transition_and_gap() -> None:
    illegal = [_row(0, 1), _row(400, 2), _row(600, 6), _row(700, 0)]
    gap = [_row(0, 1), _row(400, 2), _row(None, None, "GAP:FID_MISSING")]
    assert any("illegal transition" in cycle.reason for cycle in segment_rows(illegal))
    assert any("gap" in cycle.reason for cycle in segment_rows(gap))


def test_rejects_duration_outlier() -> None:
    rows = [_row(0, 1), _row(400, 2), _row(10_000, 5), _row(10_100, 6), _row(10_300, 7), _row(10_320, 1)]
    cycles = segment_rows(rows, SegmentationConfig(stance_max_ms=9_000))
    assert not cycles[0].accepted
    assert "stance" in cycles[0].reason
