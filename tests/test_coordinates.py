import csv
import json
from pathlib import Path

import pytest

from gait_analysis.coordinates import FILTERED_COLUMNS, CoordinateCsv, calculate_angles, computed_rows, write_computed_angles


def _coordinate_csv(tmp_path: Path, rows: str) -> Path:
    path = tmp_path / "angles.csv"
    path.write_text(
        '"Time","Ankle angle .ankle/0/X","Ankle angle .ankle/0/Y",'
        '"Ankle angle .foot/0/X","Ankle angle .foot/0/Y",'
        '"Ankle angle .knee/0/X","Ankle angle .knee/0/Y"\n'
        f"{rows}",
        encoding="utf-8",
    )
    return path


def test_calculates_signed_tilts_and_joint_angle() -> None:
    leg_tilt, foot_tilt, joint_angle = calculate_angles(
        ankle=(0, 0),
        knee=(1, 0),
        foot=(1, 1),
    )

    assert leg_tilt == pytest.approx(-90)
    assert foot_tilt == pytest.approx(-135)
    assert joint_angle == pytest.approx(-45)


def test_wraps_signed_joint_angle_to_half_open_range() -> None:
    _, _, joint_angle = calculate_angles(
        ankle=(0, 0),
        knee=(-1, 0),
        foot=(0, 1),
    )

    assert joint_angle == pytest.approx(-180)


def test_normalizes_header_whitespace_and_preserves_source_columns(tmp_path: Path) -> None:
    source = CoordinateCsv.from_csv(
        _coordinate_csv(tmp_path, '"0","0","0","1","1","1","0"\n')
    )
    rows, undefined_rows = computed_rows(source)

    assert source.source_headers["Ankle angle.ankle/0/X"] == "Ankle angle .ankle/0/X"
    assert list(rows[0])[:7] == source.headers
    assert rows[0]["leg_tilt_angle"] == "-90.000000"
    assert rows[0]["foot_tilt_angle"] == "-135.000000"
    assert rows[0]["ankle_joint_angle"] == "-45.000000"
    assert undefined_rows == 0


def test_leaves_angles_blank_for_zero_length_vectors(tmp_path: Path) -> None:
    source = CoordinateCsv.from_csv(
        _coordinate_csv(tmp_path, '"0","0","0","0","0","1","0"\n')
    )
    rows, undefined_rows = computed_rows(source)

    assert rows[0]["leg_tilt_angle"] == "-90.000000"
    assert rows[0]["foot_tilt_angle"] == ""
    assert rows[0]["ankle_joint_angle"] == ""
    assert undefined_rows == 1


def test_unwraps_foot_tilt_before_inversion_and_baseline_offset(tmp_path: Path) -> None:
    source = CoordinateCsv.from_csv(
        _coordinate_csv(
            tmp_path,
            '"0","0","0","0.017452","-0.999848","1","0"\n'
            '"20","0","0","-0.017452","-0.999848","1","0"\n',
        )
    )
    rows, _ = computed_rows(source)

    assert float(rows[0]["foot_tilt_angle"]) < -180
    assert float(rows[1]["foot_tilt_angle"]) < -180
    assert abs(float(rows[1]["foot_tilt_angle"]) - float(rows[0]["foot_tilt_angle"])) < 2


def test_appends_edge_padded_filtered_coordinates_and_uses_them_for_angles(tmp_path: Path) -> None:
    source = CoordinateCsv.from_csv(
        _coordinate_csv(
            tmp_path,
            '"0","0","0","0","1","1","0"\n'
            '"20","10","0","0","1","1","0"\n'
            '"40","0","0","0","1","1","0"\n'
            '"60","0","0","0","1","1","0"\n'
            '"80","0","0","0","1","1","0"\n',
        )
    )
    rows, _ = computed_rows(source)

    assert list(rows[0])[7:13] == list(FILTERED_COLUMNS)
    assert rows[0]["ankle_x_filtered"] == "2.000000"
    assert rows[1]["ankle_x_filtered"] == "2.000000"
    assert rows[0]["leg_tilt_angle"] == "90.000000"


def test_detrends_joint_angle_and_preserves_first_time_value(tmp_path: Path) -> None:
    source = CoordinateCsv.from_csv(
        _coordinate_csv(
            tmp_path,
            '"0","0","0","0","1","1","0"\n'
            '"20","0","0","-0.173648","0.984808","1","0"\n'
            '"40","0","0","-0.342020","0.939693","1","0"\n',
        )
    )
    rows, _ = computed_rows(source)

    raw = [float(row["ankle_joint_angle"]) for row in rows]
    trend = [float(row["ankle_joint_angle_trend"]) for row in rows]
    detrended = [float(row["ankle_joint_angle_detrended"]) for row in rows]
    assert trend == pytest.approx(raw, abs=0.001)
    assert detrended == pytest.approx([0, 0, 0], abs=0.001)


def test_centers_detrended_joint_angle_and_applies_scale(tmp_path: Path) -> None:
    source = CoordinateCsv.from_csv(
        _coordinate_csv(
            tmp_path,
            '"0","0","0","0","1","1","0"\n'
            '"20","0","0","-0.173648","0.984808","1","0"\n'
            '"40","0","0","-0.500000","0.866025","1","0"\n'
            '"60","0","0","-0.173648","0.984808","1","0"\n'
            '"80","0","0","0","1","1","0"\n',
        )
    )
    default_rows, _ = computed_rows(source)
    scaled_rows, _ = computed_rows(source, ankle_joint_scale=2)
    default = [float(row["ankle_joint_angle_detrended"]) for row in default_rows]
    scaled = [float(row["ankle_joint_angle_detrended"]) for row in scaled_rows]

    assert sum(default) / len(default) == pytest.approx(0, abs=0.00001)
    assert any(abs(value) > 0.1 for value in default)
    assert scaled == pytest.approx([2 * value for value in default], abs=0.00001)


def test_rejects_missing_or_non_numeric_required_coordinates(tmp_path: Path) -> None:
    missing = tmp_path / "missing.csv"
    missing.write_text('"Time","Ankle angle.ankle/0/X"\n"0","0"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="missing required columns"):
        CoordinateCsv.from_csv(missing)

    invalid = _coordinate_csv(tmp_path, '"0","not-a-number","0","1","1","1","0"\n')
    with pytest.raises(ValueError, match="is not numeric at CSV row 2"):
        CoordinateCsv.from_csv(invalid)


def test_start_index_excludes_leading_rows_before_validation_and_smoothing(tmp_path: Path) -> None:
    path = _coordinate_csv(
        tmp_path,
        '"0","invalid","0","0","1","1","0"\n'
        '"20","0","0","0","1","1","0"\n'
        '"40","0","0","0","1","1","0"\n',
    )
    source = CoordinateCsv.from_csv(path, start_index=2)
    rows, _ = computed_rows(source)

    assert [row["Time"] for row in rows] == ["20", "40"]
    assert rows[0]["ankle_x_filtered"] == "0.000000"
    with pytest.raises(ValueError, match="start index must be between 1 and 3"):
        CoordinateCsv.from_csv(path, start_index=4)


def test_writes_computed_csv_with_new_columns(tmp_path: Path) -> None:
    source = CoordinateCsv.from_csv(
        _coordinate_csv(tmp_path, '"0","0","0","1","1","1","0"\n')
    )
    output_path, metadata_path, undefined_rows = write_computed_angles(tmp_path / "output", "angles", source)

    with output_path.open(encoding="utf-8", newline="") as stream:
        output = list(csv.DictReader(stream))
    assert output_path.name == "angles_computed_angles.csv"
    assert output[0]["ankle_joint_angle"] == "-45.000000"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["fitted_sample_count"] == 1
    assert metadata["slope_degrees_per_s"] == 0
    assert metadata["detrended_mean_offset_degrees"] == pytest.approx(-45)
    assert metadata["ankle_joint_scale"] == 1
    assert undefined_rows == 0
