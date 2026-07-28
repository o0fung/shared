"""Causal signal helpers for the KNR gait detector."""

from __future__ import annotations

import math
from collections.abc import Mapping

from gait_knr.model_types import DetectorConfig, GaitEvent, GaitState, SideSpec, SideState


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


def load_side_signal(
    row: Mapping[str, str],
    side: SideSpec,
    state: SideState,
    config: DetectorConfig,
) -> bool:
    raw_gyro_z = parse_optional_float(row.get(side.gyro_z_column))
    state.event = GaitEvent.NONE
    if raw_gyro_z is None:
        state.gyro_z_norm = None
        state.gyro_slope = 0
        return False

    gyro_z_norm = raw_gyro_z * side.sign
    prev_gyro = state.gyro_z_norm if state.has_prev_gyro else gyro_z_norm
    state.prev_gyro_z_norm = state.gyro_z_norm
    state.gyro_z_norm = gyro_z_norm
    state.has_prev_gyro = True
    state.prev_gyro_pol = state.gyro_pol
    state.gyro_pol = polarity_hyst(
        state.prev_gyro_pol,
        gyro_z_norm,
        config.gyro_zero_hyst_dps,
    )
    state.prev_gyro_slope = state.gyro_slope
    state.gyro_slope = slope_sign(prev_gyro, gyro_z_norm, config)
    state.phase_ms += config.dt_ms
    return True


def reset_phase(state: SideState) -> None:
    state.phase_ms = 0.0


def start_swing_min(state: SideState, fid: int | None) -> None:
    state.swing_min_gyr_z = state.gyro_z_norm
    state.swing_min_fid = fid


def update_swing_min(state: SideState, fid: int | None) -> None:
    if state.state == GaitState.STANCE or state.gyro_z_norm is None:
        return
    if state.swing_min_gyr_z is None or state.gyro_z_norm < state.swing_min_gyr_z:
        state.swing_min_gyr_z = state.gyro_z_norm
        state.swing_min_fid = fid


def clear_swing_min(state: SideState) -> None:
    state.swing_min_gyr_z = None
    state.swing_min_fid = None


def format_optional_float(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.6g}"


def format_optional_int(value: int | None) -> str:
    return "" if value is None else str(value)

