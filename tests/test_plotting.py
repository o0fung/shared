import pytest
from matplotlib import colors as mcolors
import matplotlib.pyplot as plt

from gait_analysis.plotting import (
    close_trial_review,
    create_trial_review,
    plot_r_statistic,
    refresh_trial_review,
    statistic_summary_series,
)
from gait_analysis.segmenter import QUALITY_REJECTED, segment_rows


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


def test_trial_review_shading_ends_when_swing_begins() -> None:
    rows = [
        {"t_ms": "0", "walk_state": "1"},
        {"t_ms": "400", "walk_state": "2"},
        {"t_ms": "800", "walk_state": "5"},
        {"t_ms": "900", "walk_state": "6"},
        {"t_ms": "1200", "walk_state": "7"},
        {"t_ms": "1220", "walk_state": "1"},
    ]

    review = create_trial_review(rows, segment_rows(rows))

    assert review is not None
    first_span = review.axes[0].patches[0]
    assert max(first_span.get_xy()[:, 0]) == pytest.approx(0.9)
    close_trial_review(review)


def test_trial_review_shading_keeps_incomplete_cycle_status_visible() -> None:
    rows = [
        {"t_ms": "0", "walk_state": "1"},
        {"t_ms": "400", "walk_state": "2"},
    ]
    cycles = segment_rows(rows)

    review = create_trial_review(rows, cycles)

    assert cycles[0].quality_status == QUALITY_REJECTED
    assert review is not None
    first_span = review.axes[0].patches[0]
    assert max(first_span.get_xy()[:, 0]) == pytest.approx(0.4)
    assert first_span.get_facecolor() == pytest.approx(mcolors.to_rgba("#C62828", alpha=0.12))
    close_trial_review(review)


def test_creates_r_statistic_plot_with_inverted_torque_and_x_grid(tmp_path, monkeypatch) -> None:
    summary = [
        {
            "gait_percent": 0.0,
            "walk_pos_rad_mean": 0.5235987755982988,
            "walk_pos_rad_sd": 0.17453292519943295,
            "walk_tilt_forward_deg_mean": 5.0,
            "walk_tilt_forward_deg_sd": 2.0,
            "walk_tq_nm_mean": -12.0,
            "walk_tq_nm_sd": 1.5,
        },
        {
            "gait_percent": 100.0,
            "walk_pos_rad_mean": 0.8726646259971648,
            "walk_pos_rad_sd": 0.2617993877991494,
            "walk_tilt_forward_deg_mean": 7.0,
            "walk_tilt_forward_deg_sd": 3.0,
            "walk_tq_nm_mean": -15.0,
            "walk_tq_nm_sd": 2.5,
        },
    ]
    output_path = tmp_path / "statistics.png"

    series = statistic_summary_series(summary)

    assert series["Ankle Joint Angle"][1].mean() == pytest.approx(0.0)
    assert series["Leg Tilt Angle"][1].mean() == pytest.approx(0.0)
    assert series["Foot Tilt Angle"][1].mean() == pytest.approx(0.0)
    assert series["Ankle Joint Angle"][2][0] == pytest.approx(10.0)
    assert series["Foot Tilt Angle"][2][0] == pytest.approx(104**0.5)
    assert series["Torque Output"][1].tolist() == [-12.0, -15.0]
    assert series["Torque Output"][2].tolist() == [1.5, 2.5]
    close_figure = plt.close
    monkeypatch.setattr(plt, "close", lambda _: None)
    assert plot_r_statistic(summary, output_path)
    figure = plt.gcf()
    assert len(figure.axes) == 4
    for axis in figure.axes:
        assert axis.get_xticks().tolist() == [0, 25, 50, 75, 100]
        assert all(line.get_visible() for line in axis.get_xgridlines())
    close_figure(figure)
    assert output_path.is_file()
    assert output_path.stat().st_size > 0
