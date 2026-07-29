"""Regression tests for KNR frame storage and phase transitions."""

from __future__ import annotations

import unittest

from gait_knr.model_types import DetectorConfig, GaitEvent, GaitState
from gait_knr.model_update import GaitDetector


def make_row(
    fid: int,
    *,
    left_gyr_z: float | None = None,
    right_gyr_z: float | None = None,
) -> dict[str, str]:
    row = {"fid": str(fid)}
    for prefix, gyr_z in (
        ("slave_left_walk", left_gyr_z),
        ("master_right_walk", right_gyr_z),
    ):
        values = {
            "acc_x": "1.1",
            "acc_y": "2.2",
            "acc_z": "3.3",
            "gyr_x": "4.4",
            "gyr_y": "5.5",
            "gyr_z": "" if gyr_z is None else str(gyr_z),
            "pos_rad": "6.6",
            "vel_rad_s": "7.7",
            "tilt_forward_deg": "8.8",
            "tilt_accel_deg": "9.9",
        }
        row.update({f"{prefix}_{channel}": value for channel, value in values.items()})
    return row


class GaitDetectorFrameTests(unittest.TestCase):
    def test_retains_every_raw_sensor_channel_for_each_side(self) -> None:
        detector = GaitDetector(DetectorConfig())

        detector.step(make_row(42, left_gyr_z=6.6, right_gyr_z=7.7))

        left_frame = detector.states["left"].current_frame
        right_frame = detector.states["right"].current_frame
        self.assertEqual(left_frame.fid, 42)
        self.assertEqual(
            (
                left_frame.acc_x,
                left_frame.acc_y,
                left_frame.acc_z,
                left_frame.gyr_x,
                left_frame.gyr_y,
                left_frame.gyr_z,
                left_frame.pos_rad,
                left_frame.vel_rad_s,
                left_frame.tilt_forward_deg,
                left_frame.tilt_accel_deg,
            ),
            (1.1, 2.2, 3.3, 4.4, 5.5, 6.6, 6.6, 7.7, 8.8, 9.9),
        )
        self.assertEqual(right_frame.gyr_z, 7.7)
        self.assertEqual(detector.states["right"].normalized_gyr_z, -7.7)

        detector.step(make_row(43, left_gyr_z=8.8, right_gyr_z=9.9))
        self.assertEqual(detector.states["left"].previous_frame.fid, 42)
        self.assertEqual(detector.states["left"].previous_frame.gyr_z, 6.6)

    def test_missing_gyro_still_retains_the_frame_without_advancing_phase(self) -> None:
        detector = GaitDetector(DetectorConfig())

        outputs = detector.step(make_row(8, left_gyr_z=None, right_gyr_z=None))

        self.assertEqual(detector.states["left"].current_frame.fid, 8)
        self.assertEqual(detector.states["left"].current_frame.acc_y, 2.2)
        self.assertIsNone(outputs["left"].normalized_gyr_z)
        self.assertIsNone(outputs["left"].phase_elapsed_ms)

    def test_negative_valley_then_rising_gyro_enters_mid_swing(self) -> None:
        detector = GaitDetector(DetectorConfig())

        detector.step(make_row(0, left_gyr_z=10.0))
        early_swing = detector.step(make_row(1, left_gyr_z=-10.0))["left"]
        detector.step(make_row(2, left_gyr_z=-15.0))
        mid_swing = detector.step(make_row(3, left_gyr_z=-10.0))["left"]

        self.assertEqual(early_swing.gait_state, GaitState.EARLY_SWING)
        self.assertEqual(early_swing.event, GaitEvent.EARLY_SWING_START)
        self.assertEqual(mid_swing.gait_state, GaitState.MID_SWING)
        self.assertEqual(mid_swing.event, GaitEvent.MID_SWING_VALLEY)
        self.assertEqual(mid_swing.lowest_swing_gyr_z, -15.0)
        self.assertEqual(mid_swing.lowest_swing_fid, 2)

    def test_mid_swing_exits_when_opposite_side_starts_swing(self) -> None:
        detector = GaitDetector(DetectorConfig())

        detector.step(make_row(0, left_gyr_z=10.0, right_gyr_z=-10.0))
        detector.step(make_row(1, left_gyr_z=-10.0, right_gyr_z=-10.0))
        detector.step(make_row(2, left_gyr_z=-15.0, right_gyr_z=-10.0))
        detector.step(make_row(3, left_gyr_z=-10.0, right_gyr_z=-10.0))
        outputs = detector.step(make_row(4, left_gyr_z=-8.0, right_gyr_z=10.0))

        self.assertEqual(outputs["left"].gait_state, GaitState.STANCE)
        self.assertEqual(outputs["left"].event, GaitEvent.STANCE_BY_OPPOSITE_SWING)
        self.assertEqual(outputs["right"].gait_state, GaitState.EARLY_SWING)
        self.assertEqual(outputs["right"].event, GaitEvent.EARLY_SWING_START)

    def test_mid_swing_timeout_returns_to_stance_when_opposite_edge_is_missing(self) -> None:
        detector = GaitDetector(
            DetectorConfig(sample_rate_hz=50.0, mid_swing_timeout_ms=40.0)
        )

        detector.step(make_row(0, left_gyr_z=10.0))
        detector.step(make_row(1, left_gyr_z=-10.0))
        detector.step(make_row(2, left_gyr_z=-15.0))
        detector.step(make_row(3, left_gyr_z=-10.0))
        detector.step(make_row(4, left_gyr_z=-8.0))
        timeout_output = detector.step(make_row(5, left_gyr_z=-7.0))["left"]

        self.assertEqual(timeout_output.gait_state, GaitState.STANCE)
        self.assertEqual(timeout_output.event, GaitEvent.STANCE_BY_TIMEOUT)


if __name__ == "__main__":
    unittest.main()
