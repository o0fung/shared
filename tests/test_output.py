import json
from pathlib import Path

from gait_analysis.output import (
    cycle_report,
    load_saved_review_decisions,
    normalize_cycles,
    restore_saved_review_decisions,
    write_review,
)
from gait_analysis.segmenter import Cycle, segment_rows


def test_normalizes_continuous_and_discrete_channels() -> None:
    rows = [
        {"t_ms": "0", "walk_state": "1", "walk_pos_rad": "0.0", "walk_out": "0", "note": ""},
        {"t_ms": "400", "walk_state": "2", "walk_pos_rad": "1.0", "walk_out": "6", "note": ""},
        {"t_ms": "800", "walk_state": "5", "walk_pos_rad": "2.0", "walk_out": "1", "note": ""},
        {"t_ms": "900", "walk_state": "6", "walk_pos_rad": "3.0", "walk_out": "1", "note": ""},
        {"t_ms": "1200", "walk_state": "7", "walk_pos_rad": "4.0", "walk_out": "3", "note": ""},
        {"t_ms": "1220", "walk_state": "1", "walk_pos_rad": "5.0", "walk_out": "0", "note": ""},
    ]
    fields, records = normalize_cycles(list(rows[0]), rows, segment_rows(rows), points=3)
    assert fields[:2] == ["cycle_index", "gait_percent"]
    assert [record["walk_pos_rad"] for record in records] == [0.0, 1.5, 4.0]
    assert {record["walk_state"] for record in records} <= {1, 2, 5, 6, 7}


def test_cycle_report_uses_state_ranges_for_phase_durations() -> None:
    rows = [
        {"t_ms": "0", "walk_state": "1", "note": ""},
        {"t_ms": "400", "walk_state": "2", "note": ""},
        {"t_ms": "800", "walk_state": "5", "note": ""},
        {"t_ms": "850", "walk_state": "0", "note": ""},
        {"t_ms": "920", "walk_state": "6", "note": ""},
        {"t_ms": "1200", "walk_state": "7", "note": ""},
        {"t_ms": "1220", "walk_state": "1", "note": ""},
    ]

    cycle = next(cycle for cycle in segment_rows(rows) if cycle.accepted)
    report = cycle_report(cycle)

    assert report["stance_ms"] == 920
    assert report["swing_ms"] == 300
    assert report["cycle_ms"] == 1220


def _cycle(index: int = 1) -> Cycle:
    return Cycle(
        index=index,
        start_row=10,
        end_row=20,
        start_ms=100.0,
        end_ms=300.0,
        state_path=[1, 2, 5, 6, 7],
        accepted=True,
        user_decision="forced_accept",
        reason="accepted by user",
    )


def test_load_saved_review_decisions_prefers_json_and_restores_matching_cycle(tmp_path: Path) -> None:
    write_review(tmp_path, "walk", [_cycle()])
    (tmp_path / "walk_cycle_review.csv").write_text(
        "cycle_index,start_row,end_row,start_ms,end_ms,state_path,accepted,user_decision\n"
        "1,10,20,100,300,1→2→5→6→7,False,forced_reject\n",
        encoding="utf-8",
    )

    path, decisions = load_saved_review_decisions(tmp_path, "walk")
    current = _cycle()
    current.accepted, current.user_decision, current.reason = False, "auto", "invalid timing"

    assert path == tmp_path / "walk_cycle_review.json"
    assert restore_saved_review_decisions([current], decisions) == (1, 0)
    assert (current.accepted, current.user_decision, current.reason) == (
        True,
        "forced_accept",
        "accepted by user",
    )


def test_load_saved_review_decisions_falls_back_to_csv_when_json_is_malformed(tmp_path: Path) -> None:
    (tmp_path / "walk_cycle_review.json").write_text("{not valid JSON", encoding="utf-8")
    (tmp_path / "walk_cycle_review.csv").write_text(
        "cycle_index,start_row,end_row,start_ms,end_ms,state_path,accepted,user_decision\n"
        "1,10,20,100,300,1→2→5→6→7,False,forced_reject\n",
        encoding="utf-8",
    )

    path, decisions = load_saved_review_decisions(tmp_path, "walk")

    assert path == tmp_path / "walk_cycle_review.csv"
    assert len(decisions) == 1
    assert decisions[0].user_decision == "forced_reject"


def test_load_saved_review_decisions_ignores_malformed_artifacts(tmp_path: Path) -> None:
    (tmp_path / "walk_cycle_review.json").write_text(json.dumps([{"cycle_index": 1}]), encoding="utf-8")

    assert load_saved_review_decisions(tmp_path, "walk") == (None, [])


def test_restore_saved_review_decisions_skips_mismatched_cycle_identity(tmp_path: Path) -> None:
    write_review(tmp_path, "walk", [_cycle()])
    _, decisions = load_saved_review_decisions(tmp_path, "walk")
    current = _cycle()
    current.end_row = 21
    current.accepted, current.user_decision, current.reason = False, "auto", "invalid timing"

    assert restore_saved_review_decisions([current], decisions) == (0, 1)
    assert (current.accepted, current.user_decision, current.reason) == (False, "auto", "invalid timing")
