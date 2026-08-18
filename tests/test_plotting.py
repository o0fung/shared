from gait_analysis.plotting import close_trial_review, create_trial_review, refresh_trial_review
from gait_analysis.segmenter import segment_rows


def test_creates_annotated_full_trial_review_plot(tmp_path) -> None:
    rows = [
        {"t_ms": "0", "walk_state": "1", "walk_tilt_forward_deg": "0", "walk_gyr_z": "1", "walk_tq_nm": "0", "walk_pos_rad": "0", "walk_out": "0", "note": ""},
        {"t_ms": "400", "walk_state": "2", "walk_tilt_forward_deg": "1", "walk_gyr_z": "2", "walk_tq_nm": "1", "walk_pos_rad": "1", "walk_out": "6", "note": ""},
        {"t_ms": "800", "walk_state": "5", "walk_tilt_forward_deg": "2", "walk_gyr_z": "3", "walk_tq_nm": "2", "walk_pos_rad": "2", "walk_out": "1", "note": ""},
        {"t_ms": "900", "walk_state": "6", "walk_tilt_forward_deg": "3", "walk_gyr_z": "4", "walk_tq_nm": "3", "walk_pos_rad": "3", "walk_out": "1", "note": ""},
        {"t_ms": "1200", "walk_state": "7", "walk_tilt_forward_deg": "4", "walk_gyr_z": "5", "walk_tq_nm": "4", "walk_pos_rad": "4", "walk_out": "3", "note": ""},
        {"t_ms": "1220", "walk_state": "1", "walk_tilt_forward_deg": "5", "walk_gyr_z": "6", "walk_tq_nm": "5", "walk_pos_rad": "5", "walk_out": "0", "note": ""},
    ]
    output_path = tmp_path / "trial_review.png"
    cycles = segment_rows(rows)
    review = create_trial_review(rows, cycles)
    assert review is not None
    refresh_trial_review(review, cycles, output_path)
    assert output_path.is_file()
    assert output_path.stat().st_size > 0
    close_trial_review(review)
