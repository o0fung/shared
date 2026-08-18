"""Normalization and artifact writing for reviewed gait cycles."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np

from .segmenter import Cycle

DISCRETE_COLUMNS = {
    "segment_id", "packet_type", "source_mode", "frame_fid", "note", "walk_fid",
    "walk_state", "walk_out", "walk_pattern", "walk_err_code", "cfg_fid",
    "cfg_gait_model", "cfg_gait_mode", "cfg_side_is_left",
}
IDENTIFIER_COLUMNS = {"t_ms", "frame_fid", "walk_fid", "cfg_fid", "note", "packet_type", "source_mode"}


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        return reader.fieldnames or [], list(reader)


def cycle_report(cycle: Cycle) -> dict[str, object]:
    duration = cycle.duration_ms
    stance = cycle.stance_ms
    swing = cycle.swing_ms
    return {
        "cycle_index": cycle.index,
        "start_row": cycle.start_row,
        "end_row": cycle.end_row,
        "start_ms": cycle.start_ms,
        "end_ms": cycle.end_ms,
        "state_path": "→".join(map(str, cycle.state_path)),
        "cycle_ms": duration,
        "stance_ms": stance,
        "swing_ms": swing,
        "stance_percent": (100 * stance / duration) if stance is not None and duration else None,
        "swing_percent": (100 * swing / duration) if swing is not None and duration else None,
        "accepted": cycle.accepted,
        "user_decision": cycle.user_decision,
        "reason": cycle.reason,
    }


def write_review(output_dir: Path, stem: str, cycles: list[Cycle]) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    reports = [cycle_report(cycle) for cycle in cycles]
    csv_path = output_dir / f"{stem}_cycle_review.csv"
    json_path = output_dir / f"{stem}_cycle_review.json"
    fieldnames = list(reports[0]) if reports else ["cycle_index", "accepted", "reason"]
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(reports)
    json_path.write_text(json.dumps(reports, indent=2), encoding="utf-8")
    return csv_path, json_path


def _numeric_columns(headers: list[str], rows: list[dict[str, str]]) -> list[str]:
    columns: list[str] = []
    for header in headers:
        if header in IDENTIFIER_COLUMNS:
            continue
        values = [row.get(header, "") for row in rows if row.get(header, "") != ""]
        if values:
            try:
                [float(value) for value in values]
            except ValueError:
                continue
            columns.append(header)
    return columns


def normalize_cycles(
    headers: list[str],
    rows: list[dict[str, str]],
    cycles: list[Cycle],
    points: int,
) -> tuple[list[str], list[dict[str, float | int]]]:
    """Resample reviewed cycles without interpolating discrete telemetry fields."""
    if points < 2:
        raise ValueError("points must be at least 2")
    columns = _numeric_columns(headers, rows)
    percent = np.linspace(0.0, 100.0, points)
    normalized: list[dict[str, float | int]] = []
    for cycle in cycles:
        if not cycle.accepted:
            continue
        source = rows[cycle.start_row - 1:cycle.end_row]
        timestamps = np.array([float(row["t_ms"]) for row in source], dtype=float)
        timestamps = timestamps - timestamps[0]
        target = np.linspace(0.0, timestamps[-1], points)
        for position, gait_percent in enumerate(percent):
            record: dict[str, float | int] = {"cycle_index": cycle.index, "gait_percent": round(float(gait_percent), 6)}
            nearest = int(np.abs(timestamps - target[position]).argmin())
            for column in columns:
                values = np.array([float(row[column]) if row.get(column, "") != "" else np.nan for row in source], dtype=float)
                valid = ~np.isnan(values)
                if not valid.any():
                    continue
                if column in DISCRETE_COLUMNS:
                    record[column] = int(values[nearest]) if np.isfinite(values[nearest]) else int(values[valid][0])
                else:
                    record[column] = float(np.interp(target[position], timestamps[valid], values[valid]))
            normalized.append(record)
    return ["cycle_index", "gait_percent", *columns], normalized


def write_normalized(output_dir: Path, stem: str, fields: list[str], records: list[dict[str, float | int]]) -> Path:
    path = output_dir / f"{stem}_normalized_cycles.csv"
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
    return path
