"""Frame-by-frame KNR gait event state machine."""

from __future__ import annotations

from collections.abc import Mapping

from gait_knr.model_tools import (
    clear_swing_min,
    load_side_signal,
    parse_fid,
    reset_phase,
    start_swing_min,
    update_swing_min,
)
from gait_knr.model_types import (
    DetectorConfig,
    FrameOutput,
    GaitEvent,
    GaitState,
    SideSpec,
    SideState,
)


LEFT_SPEC = SideSpec(
    name="left",
    gyro_z_column="slave_left_walk_gyr_z",
    sign=1.0,
)
RIGHT_SPEC = SideSpec(
    name="right",
    gyro_z_column="master_right_walk_gyr_z",
    sign=-1.0,
)


class GaitDetector:
    def __init__(self, config: DetectorConfig) -> None:
        self.config = config
        self._specs = {
            "left": LEFT_SPEC,
            "right": RIGHT_SPEC,
        }
        self._states = {
            "left": SideState(),
            "right": SideState(),
        }
        self.event_counts = {
            "left": {event: 0 for event in GaitEvent},
            "right": {event: 0 for event in GaitEvent},
        }
        self.transition_counts = {
            "left": 0,
            "right": 0,
        }

    @property
    def states(self) -> dict[str, SideState]:
        return self._states

    def step(self, row: Mapping[str, str]) -> dict[str, FrameOutput]:
        fid = parse_fid(row.get("fid"))
        valid = {
            name: load_side_signal(row, self._specs[name], self._states[name], self.config)
            for name in self._states
        }
        early_start = {
            name: self._is_early_swing_start(self._states[name], valid[name])
            for name in self._states
        }

        # Transition flow is intentionally split in two stages:
        # 1) compute left/right early-swing edges from the same input frame,
        # 2) apply state changes using those latched edges.
        # This lets MID_SWING react to the opposite side without making the
        # output depend on whether left or right was updated first.
        previous_states = {
            name: self._states[name].state
            for name in self._states
        }
        self._advance_side("left", fid, valid["left"], early_start["left"], early_start["right"])
        self._advance_side("right", fid, valid["right"], early_start["right"], early_start["left"])

        outputs = {
            name: self._snapshot(self._states[name], valid[name])
            for name in self._states
        }
        for name, state in self._states.items():
            if state.state != previous_states[name]:
                self.transition_counts[name] += 1
            self.event_counts[name][state.event] += 1
        return outputs

    def _advance_side(
        self,
        name: str,
        fid: int | None,
        valid: bool,
        early_start: bool,
        opposite_early_start: bool,
    ) -> None:
        state = self._states[name]
        state.event = GaitEvent.NONE
        if not valid:
            return

        if state.state != GaitState.STANCE:
            update_swing_min(state, fid)

        if state.state == GaitState.MID_SWING:
            if opposite_early_start:
                self._enter_stance(state, GaitEvent.STANCE_BY_OPPOSITE_SWING)
            elif state.phase_ms >= self.config.mid_swing_timeout_ms:
                self._enter_stance(state, GaitEvent.STANCE_BY_TIMEOUT)
            return

        if state.state == GaitState.STANCE:
            if early_start:
                state.state = GaitState.EARLY_SWING
                state.event = GaitEvent.EARLY_SWING_START
                reset_phase(state)
                start_swing_min(state, fid)
            return

        if state.state == GaitState.EARLY_SWING and self._is_mid_swing_valley(state):
            state.state = GaitState.MID_SWING
            state.event = GaitEvent.MID_SWING_VALLEY
            reset_phase(state)

    def _enter_stance(self, state: SideState, event: GaitEvent) -> None:
        state.state = GaitState.STANCE
        state.event = event
        reset_phase(state)
        clear_swing_min(state)

    def _is_early_swing_start(self, state: SideState, valid: bool) -> bool:
        return (
            valid
            and state.state == GaitState.STANCE
            and state.prev_gyro_pol >= 0
            and state.gyro_pol < 0
        )

    def _is_mid_swing_valley(self, state: SideState) -> bool:
        return (
            state.swing_min_gyr_z is not None
            and state.swing_min_gyr_z <= -self.config.gyro_zero_hyst_dps
            and state.prev_gyro_slope < 0
            and state.gyro_slope >= 0
        )

    def _snapshot(self, state: SideState, valid: bool) -> FrameOutput:
        return FrameOutput(
            state=state.state,
            event=state.event,
            gyro_z_norm=state.gyro_z_norm if valid else None,
            gyro_pol=state.gyro_pol if valid else 0,
            gyro_slope=state.gyro_slope if valid else 0,
            phase_ms=state.phase_ms if valid else None,
            swing_min_gyr_z=state.swing_min_gyr_z,
            swing_min_fid=state.swing_min_fid,
        )

