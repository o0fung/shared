"""Causal signal helpers for the KNR gait detector."""

from __future__ import annotations

import math
from collections.abc import Mapping

from gait_knr.model_types import (
    DetectorConfig,
    GaitEvent,
    GaitState,
    SensorFrame,
    SideSpec,
    SideState,
)


def parse_optional_float(raw_value: str | None) -> float | None:
    if raw_value is None or raw_value == "":
        return None
    try:
        value = float(raw_value)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def parse_fid(raw_value: str | None) -> int | None:
    value = parse_optional_float(raw_value)
    if value is None:
        return None
    return int(value)


def polarity_hyst(prev_pol: int, value: float, deadband: float) -> int:
    """Return -1/0/+1 while holding the previous side outside the deadband."""
    if prev_pol > 0:
        return -1 if value < -deadband else 1
    if prev_pol < 0:
        return 1 if value > deadband else -1
    if value > deadband:
        return 1
    if value < -deadband:
        return -1
    return 0


def slope_sign(prev_value: float, cur_value: float, config: DetectorConfig) -> int:
    slope_dps2 = (cur_value - prev_value) * config.sample_rate_hz
    if slope_dps2 > config.slope_deadband_dps2:
        return 1
    if slope_dps2 < -config.slope_deadband_dps2:
        return -1
    return 0


def load_side_frame(row: Mapping[str, str], side: SideSpec) -> SensorFrame:
    """Read every synchronized sensor channel for one side from a CSV row."""
    prefix = side.csv_prefix
    return SensorFrame(
        fid=parse_fid(row.get("fid")),
        acc_x=parse_optional_float(row.get(f"{prefix}_acc_x")),
        acc_y=parse_optional_float(row.get(f"{prefix}_acc_y")),
        acc_z=parse_optional_float(row.get(f"{prefix}_acc_z")),
        gyr_x=parse_optional_float(row.get(f"{prefix}_gyr_x")),
        gyr_y=parse_optional_float(row.get(f"{prefix}_gyr_y")),
        gyr_z=parse_optional_float(row.get(f"{prefix}_gyr_z")),
        pos_rad=parse_optional_float(row.get(f"{prefix}_pos_rad")),
        vel_rad_s=parse_optional_float(row.get(f"{prefix}_vel_rad_s")),
        tilt_forward_deg=parse_optional_float(row.get(f"{prefix}_tilt_forward_deg")),
        tilt_accel_deg=parse_optional_float(row.get(f"{prefix}_tilt_accel_deg")),
    )


def update_side_measurements(
    row: Mapping[str, str],
    side: SideSpec,
    state: SideState,
    config: DetectorConfig,
) -> bool:
    """Store this frame, then derive the Z-gyro signals used by the detector."""
    current_frame = load_side_frame(row, side)
    state.event = GaitEvent.NONE
    state.previous_frame = state.current_frame
    state.current_frame = current_frame
    if current_frame.gyr_z is None:
        state.normalized_gyr_z = None
        state.gyro_slope_direction = 0
        # Do not calculate a slope across a gap in the recording.
        state.has_previous_normalized_gyr_z = False
        return False

    normalized_gyr_z = current_frame.gyr_z * side.gyro_z_sign
    previous_gyr_z = (
        state.normalized_gyr_z
        if state.has_previous_normalized_gyr_z
        else normalized_gyr_z
    )
    state.previous_normalized_gyr_z = state.normalized_gyr_z
    state.normalized_gyr_z = normalized_gyr_z
    state.has_previous_normalized_gyr_z = True
    state.previous_gyro_polarity = state.gyro_polarity
    state.gyro_polarity = polarity_hyst(
        state.previous_gyro_polarity,
        normalized_gyr_z,
        config.gyro_zero_hyst_dps,
    )
    state.previous_gyro_slope_direction = state.gyro_slope_direction
    state.gyro_slope_direction = slope_sign(
        previous_gyr_z,
        normalized_gyr_z,
        config,
    )
    state.phase_elapsed_ms += config.dt_ms
    return True


def reset_phase(state: SideState) -> None:
    state.phase_elapsed_ms = 0.0


def begin_lowest_swing_gyro_tracking(state: SideState) -> None:
    """Start a swing-only record of the lowest normalized Z gyro."""
    state.lowest_swing_gyr_z = state.normalized_gyr_z
    state.lowest_swing_fid = state.current_frame.fid


def record_lower_swing_gyro(state: SideState) -> None:
    """Keep the most negative normalized Z gyro observed during this swing."""
    if state.gait_state == GaitState.STANCE or state.normalized_gyr_z is None:
        return
    if (
        state.lowest_swing_gyr_z is None
        or state.normalized_gyr_z < state.lowest_swing_gyr_z
    ):
        state.lowest_swing_gyr_z = state.normalized_gyr_z
        state.lowest_swing_fid = state.current_frame.fid


def clear_lowest_swing_gyro(state: SideState) -> None:
    state.lowest_swing_gyr_z = None
    state.lowest_swing_fid = None


def format_optional_float(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.6g}"


def format_optional_int(value: int | None) -> str:
    return "" if value is None else str(value)

