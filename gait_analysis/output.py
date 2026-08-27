"""Normalization and artifact writing for reviewed gait cycles."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .segmenter import QUALITY_ACCEPTED, QUALITY_REJECTED, Cycle

DISCRETE_COLUMNS = {
    "segment_id", "packet_type", "source_mode", "frame_fid", "note", "walk_fid",
    "walk_state", "walk_out", "walk_pattern", "walk_err_code", "cfg_fid",
    "cfg_gait_model", "cfg_gait_mode", "cfg_side_is_left",
}
IDENTIFIER_COLUMNS = {"t_ms", "frame_fid", "walk_fid", "cfg_fid", "note", "packet_type", "source_mode"}
REVIEW_DECISIONS = {"forced_accept", "forced_reject"}


@dataclass(frozen=True)
class SavedReviewDecision:
    """A manual decision paired with the cycle identity that produced it."""

    cycle_index: int
    start_row: int
    end_row: int
    start_ms: float | None
    end_ms: float | None
    state_path: str
    accepted: bool
    user_decision: str


def _parse_optional_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        raise ValueError("timestamp must be numeric")
    return float(value)


def _parse_accepted(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        if value.lower() == "true":
            return True
        if value.lower() == "false":
            return False
    raise ValueError("accepted must be a boolean")


def _saved_decision(record: dict[str, object]) -> SavedReviewDecision | None:
    """Validate one persisted record and return its explicit manual decision."""
    required = {"cycle_index", "start_row", "end_row", "start_ms", "end_ms", "state_path", "accepted", "user_decision"}
    if not required.issubset(record):
        raise ValueError("review record is missing required fields")
    user_decision = record["user_decision"]
    if user_decision not in {"auto", *REVIEW_DECISIONS}:
        raise ValueError("review record has an unknown user decision")
    if user_decision not in REVIEW_DECISIONS:
        return None
    accepted = _parse_accepted(record["accepted"])
    if accepted != (user_decision == "forced_accept"):
        raise ValueError("review decision does not match accepted state")
    state_path = record["state_path"]
    if not isinstance(state_path, str):
        raise ValueError("state path must be a string")
    return SavedReviewDecision(
        cycle_index=int(record["cycle_index"]),
        start_row=int(record["start_row"]),
        end_row=int(record["end_row"]),
        start_ms=_parse_optional_float(record["start_ms"]),
        end_ms=_parse_optional_float(record["end_ms"]),
        state_path=state_path,
        accepted=accepted,
        user_decision=user_decision,
    )


def _read_review_records(path: Path) -> list[dict[str, object]]:
    if path.suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list) or not all(isinstance(record, dict) for record in payload):
            raise ValueError("review JSON must contain a list of records")
        return payload
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def load_saved_review_decisions(output_dir: Path, stem: str) -> tuple[Path | None, list[SavedReviewDecision]]:
    """Load manual decisions from JSON first, then CSV if the JSON is unusable."""
    for path in (output_dir / f"{stem}_cycle_review.json", output_dir / f"{stem}_cycle_review.csv"):
        if not path.is_file():
            continue
        try:
            decisions = [_saved_decision(record) for record in _read_review_records(path)]
            manual_decisions = [decision for decision in decisions if decision is not None]
            if len({decision.cycle_index for decision in manual_decisions}) != len(manual_decisions):
                raise ValueError("review has duplicate manual cycle indexes")
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            continue
        return path, manual_decisions
    return None, []


def restore_saved_review_decisions(
    cycles: list[Cycle], decisions: list[SavedReviewDecision]
) -> tuple[int, int]:
    """Restore decisions only where the saved and current cycle identities match."""
    cycles_by_index = {cycle.index: cycle for cycle in cycles}
    restored = 0
    skipped = 0
    # Replay only manual decisions after verifying the full segmentation identity.
    # A changed source file or timing configuration leaves that cycle automatic.
    for decision in decisions:
        cycle = cycles_by_index.get(decision.cycle_index)
        if cycle is None or (
            cycle.start_row,
            cycle.end_row,
            cycle.start_ms,
            cycle.end_ms,
            "→".join(map(str, cycle.state_path)),
        ) != (
            decision.start_row,
            decision.end_row,
            decision.start_ms,
            decision.end_ms,
            decision.state_path,
        ):
            skipped += 1
            continue
        cycle.accepted = decision.accepted
        cycle.user_decision = decision.user_decision
        cycle.reason = "accepted by user" if decision.accepted else "rejected by user"
        cycle.quality_status = QUALITY_ACCEPTED if decision.accepted else QUALITY_REJECTED
        restored += 1
    return restored, skipped


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
        "segment_type": cycle.segment_type,
        "step_type": cycle.step_type,
        "step_code": cycle.step_code,
        "walk_out_values": ",".join(map(str, sorted(cycle.walk_out_values))),
        "walk_out_pattern": "→".join(map(str, cycle.walk_out_pattern)),
        "cycle_ms": duration,
        "stance_ms": stance,
        "swing_ms": swing,
        "swing_phase_ms": cycle.swing_phase_ms,
        "confirmation_wrap_ms": cycle.confirmation_wrap_ms,
        "stance_percent": cycle.stance_percent,
        "swing_percent": (100 * swing / duration) if swing is not None and duration else None,
        "has_full_phase_timing": cycle.has_full_phase_timing,
        "cluster_size": cycle.cluster_size,
        "cluster_stance_median_ms": cycle.cluster_stance_median_ms,
        "cluster_swing_median_ms": cycle.cluster_swing_median_ms,
        "cluster_stance_percent_median": cycle.cluster_stance_percent_median,
        "quality_status": cycle.quality_status,
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
        if not cycle.accepted or not cycle.has_full_phase_timing:
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


def summarize_normalized_cycles(
    fields: list[str], records: list[dict[str, float | int]]
) -> tuple[list[str], list[dict[str, float]]]:
    """Calculate continuous-channel mean and sample SD at each gait-percent point."""
    channels = [
        field
        for field in fields
        if field not in {"cycle_index", "gait_percent", *IDENTIFIER_COLUMNS, *DISCRETE_COLUMNS}
    ]
    summary_fields = ["gait_percent", *(f"{channel}_{statistic}" for channel in channels for statistic in ("mean", "sd"))]
    records_by_percent: dict[float, list[dict[str, float | int]]] = {}
    for record in records:
        gait_percent = float(record["gait_percent"])
        records_by_percent.setdefault(gait_percent, []).append(record)

    summary: list[dict[str, float]] = []
    for gait_percent, cycle_records in sorted(records_by_percent.items()):
        result: dict[str, float] = {"gait_percent": gait_percent}
        for channel in channels:
            values = np.array(
                [float(record.get(channel, np.nan)) for record in cycle_records],
                dtype=float,
            )
            values = values[np.isfinite(values)]
            result[f"{channel}_mean"] = float(np.mean(values)) if len(values) else np.nan
            result[f"{channel}_sd"] = float(np.std(values, ddof=1)) if len(values) > 1 else np.nan
        summary.append(result)
    return summary_fields, summary


def write_normalized_summary(
    output_dir: Path, stem: str, fields: list[str], records: list[dict[str, float]]
) -> Path:
    """Write the per-gait-percent continuous-channel summary artifact."""
    path = output_dir / f"{stem}_normalized_cycles_summary.csv"
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
    return path
