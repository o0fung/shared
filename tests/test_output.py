from gait_analysis.output import normalize_cycles
from gait_analysis.segmenter import segment_rows


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
