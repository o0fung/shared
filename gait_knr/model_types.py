"""Types shared by the KNR gait detector modules."""

from __future__ import annotations

from dataclasses import dataclass, field
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
    csv_prefix: str
    gyro_z_sign: float


@dataclass
class SensorFrame:
    """All recorded measurements for one side at one synchronized frame."""

    fid: int | None = None
    acc_x: float | None = None
    acc_y: float | None = None
    acc_z: float | None = None
    gyr_x: float | None = None
    gyr_y: float | None = None
    gyr_z: float | None = None
    pos_rad: float | None = None
    vel_rad_s: float | None = None
    tilt_forward_deg: float | None = None
    tilt_accel_deg: float | None = None


@dataclass
class SideState:
    """Persistent gait phase, complete sensor frames, and derived motion signals."""

    gait_state: GaitState = GaitState.STANCE
    event: GaitEvent = GaitEvent.NONE
    phase_elapsed_ms: float = 0.0
    current_frame: SensorFrame = field(default_factory=SensorFrame)
    previous_frame: SensorFrame = field(default_factory=SensorFrame)
    has_previous_normalized_gyr_z: bool = False
    normalized_gyr_z: float | None = None
    previous_normalized_gyr_z: float | None = None
    gyro_polarity: int = 0
    previous_gyro_polarity: int = 0
    gyro_slope_direction: int = 0
    previous_gyro_slope_direction: int = 0
    lowest_swing_gyr_z: float | None = None
    lowest_swing_fid: int | None = None


@dataclass(frozen=True)
class FrameOutput:
    gait_state: GaitState
    event: GaitEvent
    normalized_gyr_z: float | None
    gyro_polarity: int
    gyro_slope_direction: int
    phase_elapsed_ms: float | None
    lowest_swing_gyr_z: float | None
    lowest_swing_fid: int | None

