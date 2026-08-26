from gait_analysis.segmenter import (
    QUALITY_REVIEW,
    SegmentationConfig,
    apply_session_timing_quality,
    segment_rows,
)


def _row(time_ms: int | None, state: int | None, note: str = "", walk_out: str = "") -> dict[str, str]:
    return {
        "t_ms": "" if time_ms is None else str(time_ms),
        "walk_state": "" if state is None else str(state),
        "note": note,
        "walk_out": walk_out,
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


def test_splits_five_to_zero_into_transition_and_full_cycle() -> None:
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

    cycles = segment_rows(rows)
    transition = cycles[0]
    full_cycle = next(cycle for cycle in cycles if cycle.state_path == [0, 2, 5, 6, 7])

    assert transition.segment_type == "transition_5_to_0"
    assert transition.step_code == "T50"
    assert transition.duration_ms == 850
    assert transition.stance_ms is None
    assert transition.swing_ms is None
    assert not transition.has_full_phase_timing
    assert not transition.accepted
    assert transition.quality_status == QUALITY_REVIEW
    assert transition.reason == "duration-only transition requires review"
    assert full_cycle.state_path == [0, 2, 5, 6, 7]
    assert not full_cycle.accepted
    assert full_cycle.quality_status == QUALITY_REVIEW
    assert full_cycle.reason == "full cycle immediately follows T50 transition and requires review"
    assert full_cycle.stance_ms == 70
    assert full_cycle.swing_ms == 300
    assert full_cycle.has_full_phase_timing

    apply_session_timing_quality(cycles, SegmentationConfig())
    assert not transition.accepted
    assert transition.quality_status == QUALITY_REVIEW
    assert full_cycle.quality_status == QUALITY_REVIEW


def test_keeps_t50_followup_out_of_an_otherwise_matching_timing_cluster() -> None:
    rows = [
        _row(0, 1),
        _row(400, 5),
        _row(500, 0),
        _row(1_500, 6),
        _row(1_800, 7),
        _row(2_000, 1),
    ]
    timestamp = 2_000
    for _ in range(5):
        rows.extend([
            _row(timestamp + 1_000, 6),
            _row(timestamp + 1_300, 7),
            _row(timestamp + 1_500, 1),
        ])
        timestamp += 1_500

    config = SegmentationConfig(cluster_min_cycles=5)
    cycles = segment_rows(rows, config)
    apply_session_timing_quality(cycles, config)

    followup = next(cycle for cycle in cycles if cycle.state_path == [0, 6, 7])
    normal_cycles = [cycle for cycle in cycles if cycle.state_path == [1, 6, 7]]
    assert followup.quality_status == QUALITY_REVIEW
    assert not followup.accepted
    assert len(normal_cycles) == 5
    assert all(cycle.accepted for cycle in normal_cycles)


def test_rejects_illegal_transition_and_gap() -> None:
    illegal = [_row(0, 1), _row(400, 2), _row(600, 6), _row(700, 0)]
    gap = [_row(0, 1), _row(400, 2), _row(None, None, "GAP:FID_MISSING")]
    assert any("illegal transition" in cycle.reason for cycle in segment_rows(illegal))
    assert any("gap" in cycle.reason for cycle in segment_rows(gap))


def test_keeps_long_structurally_complete_cycle_for_clustering() -> None:
    rows = [_row(0, 1), _row(400, 2), _row(10_000, 5), _row(10_100, 6), _row(10_300, 7), _row(10_320, 1)]
    cycles = segment_rows(rows)
    assert cycles[0].accepted
    assert cycles[0].stance_ms == 10_100


def test_classifies_walk_out_0_6_0_cycle() -> None:
    rows = [
        _row(0, 1, walk_out="0"),
        _row(400, 2, walk_out="6"),
        _row(800, 5, walk_out="0"),
        _row(900, 6, walk_out="0"),
        _row(1200, 7, walk_out="0"),
        _row(1220, 1, walk_out="1"),
    ]

    cycle = next(cycle for cycle in segment_rows(rows) if cycle.accepted)

    assert cycle.walk_out_pattern == [0, 6, 0]
    assert cycle.walk_out_values == frozenset({0, 6})
    assert cycle.step_type == "walk_out_0_6_0"
    assert cycle.step_code == "W060"


def test_marks_multi_metric_session_outlier_for_review() -> None:
    rows: list[dict[str, str]] = []
    timestamp = 0
    for stance in (780, 800, 820, 780, 800, 820, 780, 800):
        rows.extend([_row(timestamp, 1), _row(timestamp + stance, 6), _row(timestamp + stance + 400, 7)])
        timestamp += stance + 500
    rows.extend([_row(timestamp, 1), _row(timestamp + 1_000, 6), _row(timestamp + 1_500, 7), _row(timestamp + 1_600, 1)])

    config = SegmentationConfig(cluster_min_cycles=4)
    cycles = segment_rows(rows, config)
    apply_session_timing_quality(cycles, config)

    outlier = next(cycle for cycle in cycles if cycle.duration_ms == 1_600)
    assert not outlier.accepted
    assert outlier.quality_status == QUALITY_REVIEW
    assert outlier.reason.startswith("timing review required:")


def test_accepts_slow_high_stance_patient_cluster() -> None:
    rows = [_row(0, 1)]
    timestamp = 0
    for stance, swing in ((2_800, 560), (3_000, 520), (3_100, 540), (2_900, 560), (3_200, 500)):
        rows.extend([
            _row(timestamp + stance, 6),
            _row(timestamp + stance + swing - 200, 7),
            _row(timestamp + stance + swing, 1),
        ])
        timestamp += stance + swing

    config = SegmentationConfig(cluster_min_cycles=5)
    cycles = segment_rows(rows, config)
    apply_session_timing_quality(cycles, config)

    completed = [cycle for cycle in cycles if cycle.duration_ms is not None]
    assert len(completed) == 5
    assert all(cycle.accepted for cycle in completed)
    assert {cycle.quality_status for cycle in completed} == {"accepted"}
    assert {cycle.cluster_size for cycle in completed} == {5}
