"""Types shared by the KNR gait detector modules."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class GaitState(IntEnum):
    STANCE = 0
    EARLY_SWING = 1
    MID_SWING = 2


class GaitEvent(IntEnum):
    NONE = 0
    EARLY_SWING_START = 1
    MID_SWING_VALLEY = 2
    STANCE_BY_TIMEOUT = 3
    STANCE_BY_OPPOSITE_SWING = 4


@dataclass(frozen=True)
class DetectorConfig:
    sample_rate_hz: float = 50.0
    gyro_zero_hyst_dps: float = 5.0
    slope_deadband_dps2: float = 75.0
    mid_swing_timeout_ms: float = 700.0

    @property
    def dt_ms(self) -> float:
        return 1000.0 / self.sample_rate_hz


@dataclass(frozen=True)
class SideSpec:
    name: str
    gyro_z_column: str
    sign: float


@dataclass
class SideState:
    state: GaitState = GaitState.STANCE
    event: GaitEvent = GaitEvent.NONE
    phase_ms: float = 0.0
    has_prev_gyro: bool = False
    gyro_z_norm: float | None = None
    prev_gyro_z_norm: float | None = None
    gyro_pol: int = 0
    prev_gyro_pol: int = 0
    gyro_slope: int = 0
    prev_gyro_slope: int = 0
    swing_min_gyr_z: float | None = None
    swing_min_fid: int | None = None


@dataclass(frozen=True)
class FrameOutput:
    state: GaitState
    event: GaitEvent
    gyro_z_norm: float | None
    gyro_pol: int
    gyro_slope: int
    phase_ms: float | None
    swing_min_gyr_z: float | None
    swing_min_fid: int | None

