#!/usr/bin/env python3
"""Synchronize two exoskeleton walk CSV files using walk_acc_y jump spikes."""

from __future__ import annotations

import argparse
import csv
import re
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


CHANNELS = (
    "walk_acc_x",
    "walk_acc_y",
    "walk_acc_z",
    "walk_gyr_x",
    "walk_gyr_y",
    "walk_gyr_z",
    "walk_pos_rad",
    "walk_vel_rad_s",
    "walk_tilt_forward_deg",
    "walk_tilt_accel_deg",
)
REQUIRED_COLUMNS = ("walk_fid", *CHANNELS)
SOURCE_NAME_PATTERN = re.compile(r"_01walk_(?P<role>[^_]+)_(?P<side>[^_.]+)\.csv$")


@dataclass(frozen=True)
class Recording:
    path: Path
    name: str
    rows_by_fid: dict[int, dict[str, str]]
    first_fid: int
    last_fid: int
    acc_y_by_local_fid: dict[int, float]

    @property
    def duration_fids(self) -> int:
        return self.last_fid - self.first_fid


@dataclass(frozen=True)
class Alignment:
    second_offset: int
    first_peaks: tuple[int, ...]
    second_peaks: tuple[int, ...]
    matched_peaks: tuple[tuple[int, int], ...]
    anchor_fid: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Merge two walk CSVs after aligning their walk_acc_y jump spikes. "
            "The output fid is relative to the earliest detected jump."
        )
    )
    parser.add_argument("first_csv", type=Path)
    parser.add_argument("second_csv", type=Path)
    parser.add_argument("-o", "--output", type=Path, required=True)
    parser.add_argument(
        "--spike-deviation",
        type=float,
        default=0.25,
        help="minimum downward walk_acc_y deviation from its median (default: 0.25)",
    )
    parser.add_argument(
        "--cluster-gap-fids",
        type=int,
        default=25,
        help="maximum gap within one jump cluster (default: 25)",
    )
    parser.add_argument(
        "--min-cluster-samples",
        type=int,
        default=10,
        help="minimum below-threshold samples in a jump cluster (default: 10)",
    )
    parser.add_argument(
        "--match-tolerance-fids",
        type=int,
        default=3,
        help="maximum timing error when matching jump peaks (default: 3)",
    )
    return parser.parse_args()


def source_name(path: Path) -> str:
    match = SOURCE_NAME_PATTERN.search(path.name)
    if match:
        return f"{match.group('role')}_{match.group('side')}"
    return re.sub(r"\W+", "_", path.stem).strip("_")


def parse_fid(raw_fid: str, path: Path, line_number: int) -> int:
    try:
        fid_as_float = float(raw_fid)
        fid = int(fid_as_float)
    except ValueError as error:
        raise ValueError(f"{path}:{line_number}: invalid walk_fid {raw_fid!r}") from error
    if fid_as_float != fid:
        raise ValueError(f"{path}:{line_number}: non-integral walk_fid {raw_fid!r}")
    return fid


def load_recording(path: Path) -> Recording:
    with path.open(newline="", encoding="utf-8-sig") as csv_file:
        reader = csv.DictReader(csv_file)
        if reader.fieldnames is None:
            raise ValueError(f"{path}: missing CSV header")
        missing = [column for column in REQUIRED_COLUMNS if column not in reader.fieldnames]
        if missing:
            raise ValueError(f"{path}: missing required columns: {', '.join(missing)}")

        rows_by_fid: dict[int, dict[str, str]] = {}
        acc_y_by_fid: dict[int, float] = {}
        for line_number, row in enumerate(reader, start=2):
            if not row["walk_fid"] or not row["walk_acc_y"]:
                continue
            fid = parse_fid(row["walk_fid"], path, line_number)
            if fid in rows_by_fid:
                raise ValueError(f"{path}:{line_number}: duplicate walk_fid {fid}")
            try:
                acc_y_by_fid[fid] = float(row["walk_acc_y"])
            except ValueError as error:
                raise ValueError(
                    f"{path}:{line_number}: invalid walk_acc_y {row['walk_acc_y']!r}"
                ) from error
            rows_by_fid[fid] = row

    if not rows_by_fid:
        raise ValueError(f"{path}: no rows with walk_fid and walk_acc_y")

    first_fid = min(rows_by_fid)
    last_fid = max(rows_by_fid)
    return Recording(
        path=path,
        name=source_name(path),
        rows_by_fid=rows_by_fid,
        first_fid=first_fid,
        last_fid=last_fid,
        acc_y_by_local_fid={
            fid - first_fid: value for fid, value in acc_y_by_fid.items()
        },
    )


def detect_jump_peaks(
    recording: Recording,
    spike_deviation: float,
    cluster_gap_fids: int,
    min_cluster_samples: int,
) -> tuple[int, ...]:
    median_acc_y = statistics.median(recording.acc_y_by_local_fid.values())
    threshold = median_acc_y - spike_deviation
    spike_fids = sorted(
        fid for fid, value in recording.acc_y_by_local_fid.items() if value <= threshold
    )

    clusters: list[list[int]] = []
    for fid in spike_fids:
        if not clusters or fid - clusters[-1][-1] > cluster_gap_fids:
            clusters.append([fid])
        else:
            clusters[-1].append(fid)

    peaks = []
    for cluster in clusters:
        if len(cluster) < min_cluster_samples:
            continue
        peaks.append(min(cluster, key=recording.acc_y_by_local_fid.__getitem__))

    if not peaks:
        raise ValueError(
            f"{recording.path}: no jump spikes detected; adjust --spike-deviation "
            "or --min-cluster-samples"
        )
    return tuple(peaks)


def match_peaks(
    first_peaks: Sequence[int],
    second_peaks: Sequence[int],
    second_offset: int,
    tolerance: int,
) -> tuple[tuple[int, int], ...]:
    matches: list[tuple[int, int]] = []
    used_second: set[int] = set()
    for first_peak in first_peaks:
        candidates = [
            second_peak
            for second_peak in second_peaks
            if second_peak not in used_second
            and abs(first_peak - (second_peak + second_offset)) <= tolerance
        ]
        if candidates:
            second_peak = min(
                candidates, key=lambda peak: abs(first_peak - (peak + second_offset))
            )
            matches.append((first_peak, second_peak))
            used_second.add(second_peak)
    return tuple(matches)


def align_recordings(
    first: Recording,
    second: Recording,
    first_peaks: tuple[int, ...],
    second_peaks: tuple[int, ...],
    tolerance: int,
) -> Alignment:
    # Every cross-recording peak pair proposes a start offset. Score each proposal
    # against all peaks, then retain the offset with the most one-to-one matches
    # and least residual error. Two matches guard against aligning unrelated gait.
    candidates: list[tuple[int, int, int, tuple[tuple[int, int], ...]]] = []
    for first_peak in first_peaks:
        for second_peak in second_peaks:
            second_offset = first_peak - second_peak
            matches = match_peaks(first_peaks, second_peaks, second_offset, tolerance)
            residual = sum(
                abs(left - (right + second_offset)) for left, right in matches
            )
            candidates.append((len(matches), -residual, second_offset, matches))

    match_count, _, second_offset, matched_peaks = max(
        candidates, key=lambda candidate: (candidate[0], candidate[1])
    )
    if match_count < 2:
        raise ValueError(
            "fewer than two common jump spikes were found; synchronization is ambiguous"
        )

    # Put fid=0 at the earliest jump on the shared timeline. This preserves
    # pre-jump samples as negative fids and naturally pads a later-starting robot.
    unified_peaks = [*first_peaks, *(peak + second_offset for peak in second_peaks)]
    return Alignment(
        second_offset=second_offset,
        first_peaks=first_peaks,
        second_peaks=second_peaks,
        matched_peaks=matched_peaks,
        anchor_fid=min(unified_peaks),
    )


def ensure_distinct_names(first: Recording, second: Recording) -> None:
    if first.name == second.name:
        raise ValueError(
            f"both inputs produce the source prefix {first.name!r}; "
            "rename the files to include distinct role/side suffixes"
        )


def write_merged_csv(
    output: Path,
    first: Recording,
    second: Recording,
    alignment: Alignment,
) -> tuple[int, int, int]:
    first_offset = 0
    offsets = (first_offset, alignment.second_offset)
    recordings = (first, second)
    timeline_start = min(offsets)
    timeline_end = max(
        offset + recording.duration_fids
        for recording, offset in zip(recordings, offsets)
    )
    fieldnames = ["fid"] + [
        f"{recording.name}_{channel}"
        for recording in recordings
        for channel in CHANNELS
    ]

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        for timeline_fid in range(timeline_start, timeline_end + 1):
            output_row: dict[str, str | int] = {
                "fid": timeline_fid - alignment.anchor_fid
            }
            for recording, offset in zip(recordings, offsets):
                local_fid = timeline_fid - offset
                source_row = recording.rows_by_fid.get(
                    recording.first_fid + local_fid
                )
                for channel in CHANNELS:
                    output_row[f"{recording.name}_{channel}"] = (
                        source_row[channel] if source_row is not None else ""
                    )
            writer.writerow(output_row)

    return timeline_start - alignment.anchor_fid, timeline_end - alignment.anchor_fid, (
        timeline_end - timeline_start + 1
    )


def main() -> None:
    args = parse_args()
    if args.spike_deviation <= 0:
        raise ValueError("--spike-deviation must be positive")
    if args.cluster_gap_fids < 0:
        raise ValueError("--cluster-gap-fids cannot be negative")
    if args.min_cluster_samples < 1:
        raise ValueError("--min-cluster-samples must be at least 1")
    if args.match_tolerance_fids < 0:
        raise ValueError("--match-tolerance-fids cannot be negative")

    first = load_recording(args.first_csv)
    second = load_recording(args.second_csv)
    ensure_distinct_names(first, second)
    first_peaks = detect_jump_peaks(
        first,
        args.spike_deviation,
        args.cluster_gap_fids,
        args.min_cluster_samples,
    )
    second_peaks = detect_jump_peaks(
        second,
        args.spike_deviation,
        args.cluster_gap_fids,
        args.min_cluster_samples,
    )
    alignment = align_recordings(
        first, second, first_peaks, second_peaks, args.match_tolerance_fids
    )
    first_output_fid, last_output_fid, row_count = write_merged_csv(
        args.output, first, second, alignment
    )

    print(f"{first.name} jump peaks (local fid): {list(first_peaks)}")
    print(f"{second.name} jump peaks (local fid): {list(second_peaks)}")
    print(f"matched jump peaks: {list(alignment.matched_peaks)}")
    print(f"{second.name} start offset relative to {first.name}: {alignment.second_offset}")
    print(f"fid=0 jump position on the pre-anchor timeline: {alignment.anchor_fid}")
    print(
        f"wrote {row_count} rows ({first_output_fid} <= fid <= {last_output_fid}) "
        f"to {args.output}"
    )


if __name__ == "__main__":
    main()
