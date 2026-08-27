"""Derived-angle calculation for knee, ankle, and foot coordinate exports."""

from __future__ import annotations

import csv
from dataclasses import dataclass
import json
from math import atan2, degrees, isfinite
from pathlib import Path
import re


ANGLE_COLUMNS = (
    "leg_tilt_angle",
    "foot_tilt_angle",
    "ankle_joint_angle",
    "ankle_joint_angle_trend",
    "ankle_joint_angle_detrended",
)
FILTERED_COLUMNS = (
    "ankle_x_filtered",
    "ankle_y_filtered",
    "foot_x_filtered",
    "foot_y_filtered",
    "knee_x_filtered",
    "knee_y_filtered",
)
FILTER_WINDOW_SAMPLES = 5
POINT_COLUMNS = {
    "ankle": ("Ankle angle.ankle/0/X", "Ankle angle.ankle/0/Y"),
    "foot": ("Ankle angle.foot/0/X", "Ankle angle.foot/0/Y"),
    "knee": ("Ankle angle.knee/0/X", "Ankle angle.knee/0/Y"),
}


def _canonical_header(header: str) -> str:
    """Normalize the insignificant whitespace difference in source exports."""
    return re.sub(r"\s+\.", ".", " ".join(header.strip().split()))


def _wrap_signed_degrees(angle: float) -> float:
    """Wrap a directed angle to the half-open interval [-180, 180)."""
    return (angle + 180.0) % 360.0 - 180.0


def _format_angle(value: float | None) -> str:
    """Write blank output for undefined angles and stable decimal output otherwise."""
    return "" if value is None else f"{value:.6f}"


def _centered_moving_average(values: list[float]) -> list[float]:
    """Return a five-sample centered average with edge-value padding."""
    radius = FILTER_WINDOW_SAMPLES // 2
    padded = [values[0]] * radius + values + [values[-1]] * radius
    return [
        sum(padded[index:index + FILTER_WINDOW_SAMPLES]) / FILTER_WINDOW_SAMPLES
        for index in range(len(values))
    ]


@dataclass(frozen=True)
class CoordinateCsv:
    """Raw coordinate CSV values plus canonical-to-source column mapping."""

    headers: list[str]
    rows: list[dict[str, str]]
    source_headers: dict[str, str]
    time_header: str

    @classmethod
    def from_csv(cls, path: Path, start_index: int = 1) -> "CoordinateCsv":
        """Read selected coordinate rows and validate points required for geometry."""
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            headers = reader.fieldnames or []
            rows = list(reader)
        if not headers:
            raise ValueError("CSV has no header row")
        if start_index < 1 or start_index > len(rows):
            raise ValueError(f"start index must be between 1 and {len(rows)}")
        rows = rows[start_index - 1:]
        canonical_headers = [_canonical_header(header) for header in headers]
        if len(set(canonical_headers)) != len(canonical_headers):
            raise ValueError("CSV headers are ambiguous after whitespace normalization")
        source_headers = dict(zip(canonical_headers, headers, strict=True))
        time_header = next((header for header in headers if _canonical_header(header).casefold() == "time"), None)
        if time_header is None:
            raise ValueError("coordinate CSV must contain a Time column")
        missing = [
            required
            for point in POINT_COLUMNS.values()
            for required in point
            if required not in source_headers
        ]
        if missing:
            raise ValueError(f"coordinate CSV is missing required columns: {', '.join(missing)}")

        required_headers = [source_headers[required] for point in POINT_COLUMNS.values() for required in point]
        for row_number, row in enumerate(rows, start=2):
            for header in [time_header, *required_headers]:
                try:
                    float(row[header])
                except (KeyError, TypeError, ValueError) as error:
                    raise ValueError(f"{header} is not numeric at CSV row {row_number}") from error
        return cls(headers=headers, rows=rows, source_headers=source_headers, time_header=time_header)

def _filtered_coordinates(source: CoordinateCsv) -> dict[str, list[float]]:
    """Smooth every required coordinate independently before angle derivation."""
    return {
        canonical_header: _centered_moving_average(
            [float(row[source_header]) for row in source.rows]
        )
        for canonical_header, source_header in source.source_headers.items()
        if canonical_header in {column for point in POINT_COLUMNS.values() for column in point}
    }


def _raw_angles(
    ankle: tuple[float, float], foot: tuple[float, float], knee: tuple[float, float]
) -> tuple[float | None, float | None, float | None]:
    """Return raw leg tilt, foot heading, and vertical-reference foot tilt."""
    ankle_x, ankle_y = ankle
    foot_dx, foot_dy = foot[0] - ankle_x, foot[1] - ankle_y
    knee_dx, knee_dy = knee[0] - ankle_x, knee[1] - ankle_y
    foot_is_zero = foot_dx == 0 and foot_dy == 0
    leg_is_zero = knee_dx == 0 and knee_dy == 0

    leg_tilt = None if leg_is_zero else degrees(atan2(knee_dx, knee_dy))
    foot_heading = None if foot_is_zero else degrees(atan2(foot_dy, foot_dx))
    foot_tilt = None if foot_is_zero else degrees(atan2(foot_dx, foot_dy))
    return leg_tilt, foot_heading, foot_tilt


def calculate_angles(ankle: tuple[float, float], foot: tuple[float, float], knee: tuple[float, float]) -> tuple[float | None, float | None, float | None]:
    """Return inverted per-sample angles before time-series foot unwrapping.

    The ankle is the common origin. Both leg and foot tilt are clockwise from
    vertical to their respective ankle-originating vectors. Foot tilt has a
    -90° baseline offset, and joint angle is foot tilt minus leg tilt.
    """
    raw_leg_tilt, _, raw_foot_tilt = _raw_angles(ankle, foot, knee)
    leg_tilt = None if raw_leg_tilt is None else -raw_leg_tilt
    foot_tilt = None if raw_foot_tilt is None else -raw_foot_tilt - 90.0
    ankle_joint = None if None in (leg_tilt, foot_tilt) else _wrap_signed_degrees(foot_tilt - leg_tilt)
    return leg_tilt, foot_tilt, ankle_joint


def _unwrap_foot_tilt(current: float, previous: float | None) -> float:
    """Choose the equivalent tilt closest to the preceding valid sample."""
    if previous is None:
        return current
    return previous + _wrap_signed_degrees(current - previous)


def _linear_trend(times: list[float], values: list[float | None]) -> dict[str, float | int | None | str]:
    """Fit the ankle-angle least-squares trend using only defined samples."""
    samples = [(time, value) for time, value in zip(times, values, strict=True) if value is not None]
    if not samples:
        return {
            "slope_degrees_per_ms": None,
            "slope_degrees_per_s": None,
            "intercept_degrees": None,
            "reference_time_ms": times[0] if times else None,
            "fitted_sample_count": 0,
            "formula": "detrended = raw - slope_degrees_per_ms * (Time - reference_time_ms)",
        }
    mean_time = sum(time for time, _ in samples) / len(samples)
    mean_angle = sum(value for _, value in samples) / len(samples)
    denominator = sum((time - mean_time) ** 2 for time, _ in samples)
    slope = 0.0 if denominator == 0 else sum(
        (time - mean_time) * (value - mean_angle) for time, value in samples
    ) / denominator
    return {
        "slope_degrees_per_ms": slope,
        "slope_degrees_per_s": slope * 1_000,
        "intercept_degrees": mean_angle - slope * mean_time,
        "reference_time_ms": times[0],
        "fitted_sample_count": len(samples),
        "formula": "detrended = raw - slope_degrees_per_ms * (Time - reference_time_ms)",
    }


def _computed_rows_with_metadata(
    source: CoordinateCsv,
    ankle_joint_scale: float = 1.0,
) -> tuple[list[dict[str, str]], int, dict[str, float | int | None | str]]:
    """Append raw angles, a fitted joint trend, and detrended joint values."""
    if not isfinite(ankle_joint_scale):
        raise ValueError("ankle joint scale must be finite")
    output_rows: list[dict[str, str]] = []
    undefined_rows = 0
    previous_foot_tilt: float | None = None
    times: list[float] = []
    joint_angles: list[float | None] = []
    filtered_coordinates = _filtered_coordinates(source)
    for row_index, row in enumerate(source.rows):
        ankle = tuple(filtered_coordinates[column][row_index] for column in POINT_COLUMNS["ankle"])
        foot = tuple(filtered_coordinates[column][row_index] for column in POINT_COLUMNS["foot"])
        knee = tuple(filtered_coordinates[column][row_index] for column in POINT_COLUMNS["knee"])
        raw_leg_tilt, _, raw_foot_tilt = _raw_angles(
            ankle,
            foot,
            knee,
        )
        # Preserve foot-angle continuity across ±180°. Each equivalent tilt
        # differs by 360°, so select the one nearest the previous valid sample,
        # then apply the requested inversion and -90° offset. A zero-length
        # foot vector breaks continuity because it has no physical direction.
        if raw_foot_tilt is None:
            foot_tilt = None
            previous_foot_tilt = None
        else:
            previous_foot_tilt = _unwrap_foot_tilt(raw_foot_tilt, previous_foot_tilt)
            foot_tilt = -previous_foot_tilt - 90.0
        leg_tilt = None if raw_leg_tilt is None else -raw_leg_tilt
        ankle_joint = None if None in (leg_tilt, foot_tilt) else _wrap_signed_degrees(foot_tilt - leg_tilt)
        if None in (leg_tilt, foot_tilt, ankle_joint):
            undefined_rows += 1
        times.append(float(row[source.time_header]))
        joint_angles.append(ankle_joint)
        output_rows.append(
            {
                **row,
                "ankle_x_filtered": _format_angle(ankle[0]),
                "ankle_y_filtered": _format_angle(ankle[1]),
                "foot_x_filtered": _format_angle(foot[0]),
                "foot_y_filtered": _format_angle(foot[1]),
                "knee_x_filtered": _format_angle(knee[0]),
                "knee_y_filtered": _format_angle(knee[1]),
                "leg_tilt_angle": _format_angle(leg_tilt),
                "foot_tilt_angle": _format_angle(foot_tilt),
                "ankle_joint_angle": _format_angle(ankle_joint),
            }
        )
    metadata = _linear_trend(times, joint_angles)
    slope = metadata["slope_degrees_per_ms"]
    intercept = metadata["intercept_degrees"]
    reference_time = metadata["reference_time_ms"]
    # The regression excludes undefined geometry, but every source row remains
    # in the output. First remove the slope, then center the valid residuals at
    # zero before applying the user scale; this separates camera-drift removal,
    # baseline removal, and amplitude adjustment into auditable steps.
    residuals = [
        angle - slope * (time - reference_time)
        for time, angle in zip(times, joint_angles, strict=True)
        if angle is not None and slope is not None and reference_time is not None
    ]
    mean_offset = sum(residuals) / len(residuals) if residuals else None
    metadata["detrended_mean_offset_degrees"] = mean_offset
    metadata["ankle_joint_scale"] = ankle_joint_scale
    metadata["formula"] = (
        "detrended = (raw - slope_degrees_per_ms * "
        "(Time - reference_time_ms) - detrended_mean_offset_degrees) * ankle_joint_scale"
    )
    for row, time, angle in zip(output_rows, times, joint_angles, strict=True):
        if angle is None or slope is None or intercept is None or reference_time is None or mean_offset is None:
            row["ankle_joint_angle_trend"] = ""
            row["ankle_joint_angle_detrended"] = ""
            continue
        row["ankle_joint_angle_trend"] = _format_angle(intercept + slope * time)
        row["ankle_joint_angle_detrended"] = _format_angle(
            (angle - slope * (time - reference_time) - mean_offset) * ankle_joint_scale
        )
    return output_rows, undefined_rows, metadata


def computed_rows(source: CoordinateCsv, ankle_joint_scale: float = 1.0) -> tuple[list[dict[str, str]], int]:
    """Append computed and detrended angles to each source row."""
    rows, undefined_rows, _ = _computed_rows_with_metadata(source, ankle_joint_scale)
    return rows, undefined_rows


def write_computed_angles(
    output_dir: Path,
    stem: str,
    source: CoordinateCsv,
    ankle_joint_scale: float = 1.0,
) -> tuple[Path, Path, int]:
    """Write source columns, derived angles, and auditable trend metadata."""
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{stem}_computed_angles.csv"
    metadata_path = output_dir / f"{stem}_computed_angles.json"
    rows, undefined_rows, metadata = _computed_rows_with_metadata(source, ankle_joint_scale)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=[*source.headers, *FILTERED_COLUMNS, *ANGLE_COLUMNS])
        writer.writeheader()
        writer.writerows(rows)
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return path, metadata_path, undefined_rows
