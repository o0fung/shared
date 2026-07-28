#!/usr/bin/env python3
"""Run KNR gait event detection on the synchronized backup CSV."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Any

from gait_knr.model_tools import format_optional_float, format_optional_int
from gait_knr.model_types import DetectorConfig, FrameOutput, GaitEvent, GaitState
from gait_knr.model_update import GaitDetector


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = REPO_ROOT / "backup" / "synchronized_walk.csv"
DEFAULT_OUTPUT = REPO_ROOT / "viewer" / "data" / "synchronized_walk.csv"
KNR_COLUMNS = (
    "knr_right_state",
    "knr_right_event",
    "knr_right_gyr_z_norm",
    "knr_right_gyr_pol",
    "knr_right_gyr_slope",
    "knr_right_phase_ms",
    "knr_right_swing_min_gyr_z",
    "knr_right_swing_min_fid",
    "knr_left_state",
    "knr_left_event",
    "knr_left_gyr_z_norm",
    "knr_left_gyr_pol",
    "knr_left_gyr_slope",
    "knr_left_phase_ms",
    "knr_left_swing_min_gyr_z",
    "knr_left_swing_min_fid",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Append causal KNR gait detector state/event/debug channels to a "
            "synchronized walk CSV."
        )
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--sample-rate-hz", type=float, default=50.0)
    parser.add_argument("--gyro-zero-hyst-dps", type=float, default=5.0)
    parser.add_argument("--slope-deadband-dps2", type=float, default=75.0)
    parser.add_argument("--mid-swing-timeout-ms", type=float, default=700.0)
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    if args.sample_rate_hz <= 0.0:
        raise ValueError("--sample-rate-hz must be positive")
    if args.gyro_zero_hyst_dps < 0.0:
        raise ValueError("--gyro-zero-hyst-dps cannot be negative")
    if args.slope_deadband_dps2 < 0.0:
        raise ValueError("--slope-deadband-dps2 cannot be negative")
    if args.mid_swing_timeout_ms <= 0.0:
        raise ValueError("--mid-swing-timeout-ms must be positive")


def load_rows(input_path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with input_path.open(newline="", encoding="utf-8-sig") as csv_file:
        reader = csv.DictReader(csv_file)
        if reader.fieldnames is None:
            raise ValueError(f"{input_path}: missing CSV header")
        rows = [dict(row) for row in reader]
    if "fid" not in reader.fieldnames:
        raise ValueError(f"{input_path}: missing required fid column")
    return list(reader.fieldnames), rows


def output_columns(fieldnames: list[str]) -> list[str]:
    base_columns = [column for column in fieldnames if not column.startswith("knr_")]
    return [*base_columns, *KNR_COLUMNS]


def frame_output_columns(prefix: str, output: FrameOutput) -> dict[str, str]:
    return {
        f"knr_{prefix}_state": str(int(output.state)),
        f"knr_{prefix}_event": str(int(output.event)),
        f"knr_{prefix}_gyr_z_norm": format_optional_float(output.gyro_z_norm),
        f"knr_{prefix}_gyr_pol": str(output.gyro_pol),
        f"knr_{prefix}_gyr_slope": str(output.gyro_slope),
        f"knr_{prefix}_phase_ms": format_optional_float(output.phase_ms),
        f"knr_{prefix}_swing_min_gyr_z": format_optional_float(output.swing_min_gyr_z),
        f"knr_{prefix}_swing_min_fid": format_optional_int(output.swing_min_fid),
    }


def augment_rows(rows: list[dict[str, str]], config: DetectorConfig) -> tuple[list[dict[str, str]], GaitDetector]:
    detector = GaitDetector(config)
    augmented_rows: list[dict[str, str]] = []
    for row in rows:
        outputs = detector.step(row)
        out_row = {key: value for key, value in row.items() if not key.startswith("knr_")}
        out_row.update(frame_output_columns("left", outputs["left"]))
        out_row.update(frame_output_columns("right", outputs["right"]))
        augmented_rows.append(out_row)
    return augmented_rows, detector


def write_rows(output_path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def event_summary(detector: GaitDetector) -> dict[str, Any]:
    return {
        side: {
            "transitions": detector.transition_counts[side],
            "events": {
                event.name: count
                for event, count in detector.event_counts[side].items()
                if event is not GaitEvent.NONE and count > 0
            },
        }
        for side in ("left", "right")
    }


def print_legend() -> None:
    states = ", ".join(f"{int(state)}={state.name}" for state in GaitState)
    events = ", ".join(f"{int(event)}={event.name}" for event in GaitEvent)
    print(f"state enum: {states}")
    print(f"event enum: {events}")


def main() -> None:
    args = parse_args()
    validate_args(args)
    config = DetectorConfig(
        sample_rate_hz=args.sample_rate_hz,
        gyro_zero_hyst_dps=args.gyro_zero_hyst_dps,
        slope_deadband_dps2=args.slope_deadband_dps2,
        mid_swing_timeout_ms=args.mid_swing_timeout_ms,
    )
    fieldnames, rows = load_rows(args.input)
    augmented_rows, detector = augment_rows(rows, config)
    output_fieldnames = output_columns(fieldnames)
    write_rows(args.output, output_fieldnames, augmented_rows)

    print(f"read {len(rows)} rows from {args.input}")
    print(f"wrote {len(augmented_rows)} rows to {args.output}")
    print_legend()
    for side, summary in event_summary(detector).items():
        print(f"{side}: {summary}")


if __name__ == "__main__":
    main()

