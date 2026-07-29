"""Frame-by-frame KNR gait event state machine."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from gait_knr.model_tools import (
    begin_lowest_swing_gyro_tracking,
    clear_lowest_swing_gyro,
    record_lower_swing_gyro,
    reset_phase,
    update_side_measurements,
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
    csv_prefix="slave_left_walk",
    gyro_z_sign=1.0,
)
RIGHT_SPEC = SideSpec(
    name="right",
    csv_prefix="master_right_walk",
    gyro_z_sign=-1.0,
)


@dataclass(frozen=True)
class GaitFrameContext:
    """Shared two-leg facts captured before either side transitions."""

    gait_state_before_transition: dict[str, GaitState]
    early_swing_started: dict[str, bool]


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
        """Process one synchronized frame and return each side's gait result."""
        # A frame is processed in a fixed order:
        # 1) retain every raw sensor channel and derive motion signals,
        # 2) latch swing-start evidence for both sides from this same frame,
        # 3) advance both gait phases using those latched decisions,
        # 4) expose the resulting phase and update aggregate counts.
        #
        # Latching before either side advances is crucial: MID_SWING may react
        # to the opposite side's early swing, so left/right iteration must not
        # change the outcome.
        has_usable_gyro = {
            name: update_side_measurements(
                row,
                self._specs[name],
                self._states[name],
                self.config,
            )
            for name in self._states
        }
        previous_gait_states = {
            name: self._states[name].gait_state
            for name in self._states
        }
        early_swing_starts = {
            name: (
                has_usable_gyro[name]
                and previous_gait_states[name] == GaitState.STANCE
                and self._states[name].previous_gyro_polarity >= 0
                and self._states[name].gyro_polarity < 0
            )
            for name in self._states
        }

        # Shared two-leg context for this frame:
        # 1) both sides have already loaded current measurements,
        # 2) state and early-swing edges are frozen before any transition runs,
        # 3) each side can read the other side's gait state/edge without the
        #    result depending on whether left or right is processed first.
        gait_context = GaitFrameContext(
            gait_state_before_transition=previous_gait_states,
            early_swing_started=early_swing_starts,
        )

        # Inline gait state machine. Each branch defines the condition it cares
        # about, explains the movement pattern, and applies the transition in
        # place so behavior can be read from top to bottom like the AKR model.
        for name in ("left", "right"):
            state = self._states[name]
            opposite_name = "right" if name == "left" else "left"
            gait_state_at_frame_start = gait_context.gait_state_before_transition[name]
            opposite_gait_state_at_frame_start = (
                gait_context.gait_state_before_transition[opposite_name]
            )
            state.event = GaitEvent.NONE

            if not has_usable_gyro[name]:
                continue

            if gait_state_at_frame_start == GaitState.STANCE:
                swing_started_from_gyro_crossing = gait_context.early_swing_started[
                    name
                ]

                # STANCE flow:
                # 1) wait while normalized Z gyro is non-negative or quiet,
                # 2) a crossing into negative gyro means this leg starts swing,
                # 3) reset the phase timer and begin recording swing's low point.
                if swing_started_from_gyro_crossing:
                    state.gait_state = GaitState.EARLY_SWING
                    state.event = GaitEvent.EARLY_SWING_START
                    reset_phase(state)
                    begin_lowest_swing_gyro_tracking(state)

            elif gait_state_at_frame_start == GaitState.EARLY_SWING:
                # EARLY_SWING flow:
                # 1) keep the most negative normalized Z gyro seen in this swing,
                # 2) require that low point to be meaningfully negative,
                # 3) enter MID_SWING only once gyro slope turns upward.
                record_lower_swing_gyro(state)
                swing_has_deep_negative_gyro = (
                    state.lowest_swing_gyr_z is not None
                    and state.lowest_swing_gyr_z <= -self.config.gyro_zero_hyst_dps
                )
                gyro_has_started_rising = (
                    state.previous_gyro_slope_direction < 0
                    and state.gyro_slope_direction >= 0
                )
                mid_swing_valley_detected = (
                    swing_has_deep_negative_gyro and gyro_has_started_rising
                )

                if mid_swing_valley_detected:
                    state.gait_state = GaitState.MID_SWING
                    state.event = GaitEvent.MID_SWING_VALLEY
                    reset_phase(state)

            elif gait_state_at_frame_start == GaitState.MID_SWING:
                # MID_SWING flow:
                # 1) keep tracking the low point for debug visibility,
                # 2) normally finish when the opposite leg begins swing,
                # 3) recover to STANCE by timeout if that opposite edge is missed.
                record_lower_swing_gyro(state)
                opposite_leg_was_in_stance = (
                    opposite_gait_state_at_frame_start == GaitState.STANCE
                )
                opposite_leg_started_swing = (
                    opposite_leg_was_in_stance
                    and gait_context.early_swing_started[opposite_name]
                )
                mid_swing_timed_out = (
                    state.phase_elapsed_ms >= self.config.mid_swing_timeout_ms
                )

                if opposite_leg_started_swing:
                    self._enter_stance(state, GaitEvent.STANCE_BY_OPPOSITE_SWING)
                elif mid_swing_timed_out:
                    self._enter_stance(state, GaitEvent.STANCE_BY_TIMEOUT)

        outputs = {
            name: self._snapshot(self._states[name], has_usable_gyro[name])
            for name in self._states
        }
        for name, state in self._states.items():
            if state.gait_state != previous_gait_states[name]:
                self.transition_counts[name] += 1
            self.event_counts[name][state.event] += 1
        return outputs

    def _enter_stance(self, state: SideState, event: GaitEvent) -> None:
        state.gait_state = GaitState.STANCE
        state.event = event
        reset_phase(state)
        clear_lowest_swing_gyro(state)

    def _snapshot(self, state: SideState, valid: bool) -> FrameOutput:
        return FrameOutput(
            gait_state=state.gait_state,
            event=state.event,
            normalized_gyr_z=state.normalized_gyr_z if valid else None,
            gyro_polarity=state.gyro_polarity if valid else 0,
            gyro_slope_direction=state.gyro_slope_direction if valid else 0,
            phase_elapsed_ms=state.phase_elapsed_ms if valid else None,
            lowest_swing_gyr_z=state.lowest_swing_gyr_z,
            lowest_swing_fid=state.lowest_swing_fid,
        )

