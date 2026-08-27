"""Typer commands for gait-cycle review and coordinate-angle calculation."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import json
from pathlib import Path
import sys
from typing import Callable, Literal, TypeVar

import typer
from rich.console import Console
from rich.table import Table

from .output import (
    cycle_report,
    load_saved_review_decisions,
    normalize_cycles,
    read_csv,
    restore_saved_review_decisions,
    write_normalized,
    summarize_normalized_cycles,
    write_normalized_summary,
    write_review,
)
from .plotting import (
    DEFAULT_CHANNELS,
    close_trial_review,
    create_trial_review,
    open_trial_review,
    plot_normalized,
    plot_r_statistic,
    process_trial_review_events,
    refresh_trial_review,
    save_trial_review,
)
from .coordinates import CoordinateCsv, write_computed_angles
from .segmenter import (
    QUALITY_ACCEPTED,
    QUALITY_REJECTED,
    SegmentationConfig,
    apply_session_timing_quality,
    segment_rows,
)

app = typer.Typer(help="Segment rr_app walk CSVs and derive coordinate angles.")
console = Console()
PromptValue = TypeVar("PromptValue")
BulkCommand = Literal["segment", "review-coordinates"]


@dataclass(frozen=True)
class BulkJob:
    """A validated manifest job with options specific to its command."""

    command: BulkCommand
    csv_file: Path
    options: dict[str, object]


BULK_OPTION_CONSTRAINTS: dict[BulkCommand, dict[str, tuple[str, float | None]]] = {
    "segment": {
        "points": ("integer", 2),
        "accept": ("string", None),
        "reject": ("string", None),
        "no_plot": ("boolean", None),
        "plot_channels": ("string", None),
        "robust_z_max": ("number", 0),
        "cluster_log_duration_tolerance": ("number", 0),
        "cluster_stance_percent_tolerance": ("number", 0),
        "cluster_min_cycles": ("integer", 2),
    },
    "review-coordinates": {
        "start_index": ("integer", 1),
        "ankle_joint_scale": ("number", None),
    },
}


@app.callback()
def main() -> None:
    """Analyze causal gait cycles from rr_app walk telemetry."""


def _parse_indices(value: str) -> set[int]:
    indices: set[int] = set()
    if not value.strip():
        return indices
    for token in (item.strip() for item in value.split(",")):
        if not token:
            continue
        bounds = token.split("-", maxsplit=1)
        try:
            if len(bounds) == 2:
                indices.update(range(int(bounds[0]), int(bounds[1]) + 1))
            else:
                indices.add(int(bounds[0]))
        except ValueError as error:
            raise typer.BadParameter(f"invalid index selection {token!r}; use 1,3-5") from error
    return indices


def _artifact_dir(csv_file: Path) -> Path:
    """Mirror an input parent beneath its enclosing data/ directory into output/."""
    resolved_file = csv_file.resolve()
    # Commands can be launched from a data subdirectory. Find the nearest
    # enclosing data root from the input path rather than interpreting data/
    # relative to the shell's current working directory.
    data_root = next((parent for parent in resolved_file.parents if parent.name == "data"), None)
    if data_root is None:
        raise typer.BadParameter("CSV must be located under a data directory", param_hint="csv_file")
    relative_parent = resolved_file.parent.relative_to(data_root)
    return data_root.parent / "output" / relative_parent


def _prompt_while_review_open(prompt: Callable[[], PromptValue], review_window: object | None) -> PromptValue:
    """Read terminal input off the GUI thread so macOS keeps processing tools."""
    if review_window is None:
        return prompt()
    with ThreadPoolExecutor(max_workers=1) as executor:
        result = executor.submit(prompt)
        while not result.done():
            process_trial_review_events(review_window)
        return result.result()


def _prompt_text(label: str, default: str, review_window: object | None) -> str:
    """Use Click normally, but keep GUI and stdin work on separate threads."""
    if review_window is None:
        return typer.prompt(label, default=default)
    console.print(f"{label} [{default}]: ", end="")
    value = _prompt_while_review_open(sys.stdin.readline, review_window)
    if value == "":
        raise typer.Abort()
    return value.rstrip("\r\n") or default


def _parse_write_action(value: str) -> Literal["write", "review", "abort"]:
    """Interpret the final prompt, treating unknown input as a safe abort."""
    normalized = value.strip().lower()
    if normalized in {"y", "yes"}:
        return "write"
    if normalized in {"r", "review"}:
        return "review"
    return "abort"


def _confirm_write(review_window: object | None) -> Literal["write", "review", "abort"]:
    prompt = "Write review, normalized CSV, and plot? (y=write / r=return to review / n=abort)"
    if review_window is None:
        return _parse_write_action(typer.prompt(prompt, default="n"))
    console.print(f"{prompt}: ", end="")
    value = _prompt_while_review_open(sys.stdin.readline, review_window)
    return _parse_write_action(value)


def _show_review(cycles: list) -> None:
    table = Table(title="Causal gait-cycle review")
    for column in ("Index", "Rows", "State path", "Type", "walk_out pattern", "Cycle ms", "Stance ms (%)", "Swing ms (%)", "Decision / reason"):
        table.add_column(column)
    for cycle in cycles:
        report = cycle_report(cycle)
        stance = report["stance_ms"]
        swing = report["swing_ms"]
        stance_text = "-" if stance is None else f"{stance:.0f} ({report['stance_percent']:.1f}%)"
        swing_text = "-" if swing is None else f"{swing:.0f} ({report['swing_percent']:.1f}%)"
        decision = cycle.quality_status.upper()
        reason = cycle.reason or "valid"
        table.add_row(
            str(cycle.index),
            f"{cycle.start_row}-{cycle.end_row}",
            str(report["state_path"]),
            str(report["step_code"] or report["step_type"]),
            str(report["walk_out_pattern"]) or "-",
            "-" if report["cycle_ms"] is None else f"{report['cycle_ms']:.0f}",
            stance_text,
            swing_text,
            f"{decision}: {reason}",
            style="green" if cycle.quality_status == QUALITY_ACCEPTED else "yellow" if cycle.quality_status == "review" else "red",
        )
    console.print(table)


def _apply_forced_decisions(cycles: list, forced_accept: set[int], forced_reject: set[int]) -> None:
    """Apply current-run choices after restored decisions so explicit input wins."""
    for cycle in cycles:
        if cycle.index in forced_accept:
            cycle.accepted, cycle.user_decision, cycle.reason = True, "forced_accept", "accepted by user"
            cycle.quality_status = QUALITY_ACCEPTED
        elif cycle.index in forced_reject:
            cycle.accepted, cycle.user_decision, cycle.reason = False, "forced_reject", "rejected by user"
            cycle.quality_status = QUALITY_REJECTED


def _review_decisions_interactively(
    cycles: list,
    review_window: object | None,
    review_window_is_shown: bool,
    trial_plot_path: Path,
) -> None:
    """Collect and display overrides until the operator writes or aborts.

    Each pass leaves earlier choices applied so operators can inspect the
    refreshed plot and alter only the indexes they reconsidered.
    """
    active_review_window = review_window if review_window_is_shown else None
    while True:
        console.print("The review plot remains open while you enter index ranges below.")
        forced_accept = _parse_indices(
            _prompt_text("Force accept indexes (blank keeps current decision)", "", active_review_window)
        )
        forced_reject = _parse_indices(
            _prompt_text("Force reject indexes (blank keeps current decision)", "", active_review_window)
        )
        if forced_accept & forced_reject:
            raise typer.BadParameter("--accept and --reject selections overlap")
        _apply_forced_decisions(cycles, forced_accept, forced_reject)

        if review_window is not None:
            refresh_trial_review(review_window, cycles, trial_plot_path)
        _show_review(cycles)

        action = _confirm_write(active_review_window)
        if action == "write":
            return
        if action == "abort":
            raise typer.Abort()
        console.print("Returning to accept/reject review.")


def _run_segment(
    csv_file: Path,
    *,
    points: int = 101,
    accept: str = "",
    reject: str = "",
    yes: bool = False,
    no_plot: bool = False,
    no_show_review_plot: bool = False,
    plot_channels: str = ",".join(DEFAULT_CHANNELS),
    robust_z_max: float = 3.5,
    cluster_log_duration_tolerance: float = 0.35,
    cluster_stance_percent_tolerance: float = 10,
    cluster_min_cycles: int = 5,
) -> None:
    """Execute the segment workflow independently of Typer argument parsing."""
    headers, rows = read_csv(csv_file)
    if not {"t_ms", "walk_state"}.issubset(headers):
        raise typer.BadParameter("CSV must contain t_ms and walk_state columns")
    config = SegmentationConfig(
        robust_z_max=robust_z_max,
        cluster_log_duration_tolerance=cluster_log_duration_tolerance,
        cluster_stance_percent_tolerance=cluster_stance_percent_tolerance,
        cluster_min_cycles=cluster_min_cycles,
    )
    cycles = segment_rows(rows, config)
    apply_session_timing_quality(cycles, config)
    artifact_dir = _artifact_dir(csv_file)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    review_path, saved_decisions = load_saved_review_decisions(artifact_dir, csv_file.stem)
    if review_path is not None:
        restored, skipped = restore_saved_review_decisions(cycles, saved_decisions)
        console.print(
            f"Restored {restored} saved manual decision(s) from [bold]{review_path}[/bold]"
            f"; skipped {skipped} that no longer match."
        )
    trial_plot_path = artifact_dir / f"{csv_file.stem}_trial_review.png"
    _show_review(cycles)
    review_window = create_trial_review(rows, cycles)
    if review_window is not None:
        save_trial_review(review_window, trial_plot_path)
    shown = review_window is not None and not no_show_review_plot and open_trial_review(review_window)
    console.print(f"Review plot: [bold]{trial_plot_path}[/bold]")
    if not no_show_review_plot and not shown:
        console.print("Interactive review window unavailable; wrote the PNG for inspection.")

    try:
        forced_accept = _parse_indices(accept)
        forced_reject = _parse_indices(reject)
        if forced_accept & forced_reject:
            raise typer.BadParameter("--accept and --reject selections overlap")
        if not yes and not accept and not reject:
            _review_decisions_interactively(cycles, review_window, shown, trial_plot_path)
        else:
            _apply_forced_decisions(cycles, forced_accept, forced_reject)
            if review_window is not None:
                refresh_trial_review(review_window, cycles, trial_plot_path)
            _show_review(cycles)
            if not yes:
                action = _confirm_write(review_window if shown else None)
                if action == "abort":
                    raise typer.Abort()
                if action == "review":
                    _review_decisions_interactively(cycles, review_window, shown, trial_plot_path)

        stem = csv_file.stem
        review_csv, review_json = write_review(artifact_dir, stem, cycles)
        fields, normalized = normalize_cycles(headers, rows, cycles, points)
        normalized_csv = write_normalized(artifact_dir, stem, fields, normalized)
        summary_fields, summary = summarize_normalized_cycles(fields, normalized)
        summary_csv = write_normalized_summary(artifact_dir, stem, summary_fields, summary)
        console.print(f"Wrote [bold]{review_csv}[/bold], {review_json}, {normalized_csv}, and {summary_csv}")
        if not no_plot and normalized:
            plot_path = artifact_dir / f"{stem}_normalized_cycles.png"
            plot_normalized(normalized, [value.strip() for value in plot_channels.split(",")], plot_path)
            console.print(f"Wrote [bold]{plot_path}[/bold]")
            r_statistic_plot_path = artifact_dir / f"{stem}_normalized_cycles_r_statistic.png"
            if plot_r_statistic(summary, r_statistic_plot_path):
                console.print(f"Wrote [bold]{r_statistic_plot_path}[/bold]")
    finally:
        close_trial_review(review_window)


def _run_review_coordinates(csv_file: Path, *, start_index: int = 1, ankle_joint_scale: float = 1.0) -> None:
    """Execute the coordinate-angle workflow independently of Typer argument parsing."""
    try:
        source = CoordinateCsv.from_csv(csv_file, start_index=start_index)
    except ValueError as error:
        raise typer.BadParameter(str(error), param_hint="csv_file") from error
    artifact_dir = _artifact_dir(csv_file)
    try:
        output_path, metadata_path, undefined_rows = write_computed_angles(
            artifact_dir,
            csv_file.stem,
            source,
            ankle_joint_scale,
        )
    except ValueError as error:
        raise typer.BadParameter(str(error), param_hint="--ankle-joint-scale") from error
    warning = f"; {undefined_rows} row(s) had a zero-length segment" if undefined_rows else ""
    console.print(f"Wrote [bold]{output_path}[/bold] and {metadata_path}{warning}")


@app.command()
def segment(
    csv_file: Path = typer.Argument(..., exists=True, readable=True, help="rr_app walk CSV to analyze."),
    points: int = typer.Option(101, min=2, help="Samples on the normalized 0–100% grid."),
    accept: str = typer.Option("", help="Cycle indexes/ranges to force accept, e.g. 2,5-7."),
    reject: str = typer.Option("", help="Cycle indexes/ranges to force reject, e.g. 3,8-9."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the interactive review confirmation."),
    no_plot: bool = typer.Option(False, help="Do not generate the post-confirmation normalized-cycle PNG."),
    no_show_review_plot: bool = typer.Option(False, help="Do not open the post-table Matplotlib review window."),
    plot_channels: str = typer.Option(",".join(DEFAULT_CHANNELS), help="Comma-separated normalized channels to plot."),
    robust_z_max: float = typer.Option(3.5, min=0, help="Median/MAD timing outlier z-score threshold."),
    cluster_log_duration_tolerance: float = typer.Option(
        0.35, min=0, help="Maximum log-duration difference for initial cluster neighbours."
    ),
    cluster_stance_percent_tolerance: float = typer.Option(
        10, min=0, help="Maximum stance-percent difference for initial cluster neighbours."
    ),
    cluster_min_cycles: int = typer.Option(5, min=2, help="Minimum cycles required for automatic timing acceptance."),
) -> None:
    """Review walk-state cycles, then write accepted normalized telemetry."""
    _run_segment(
        csv_file,
        points=points,
        accept=accept,
        reject=reject,
        yes=yes,
        no_plot=no_plot,
        no_show_review_plot=no_show_review_plot,
        plot_channels=plot_channels,
        robust_z_max=robust_z_max,
        cluster_log_duration_tolerance=cluster_log_duration_tolerance,
        cluster_stance_percent_tolerance=cluster_stance_percent_tolerance,
        cluster_min_cycles=cluster_min_cycles,
    )


@app.command()
def review_coordinates(
    csv_file: Path = typer.Argument(..., exists=True, readable=True, help="Coordinate CSV with ankle, foot, and knee X/Y columns."),
    start_index: int = typer.Option(1, min=1, help="One-based first data-row index to include."),
    ankle_joint_scale: float = typer.Option(1.0, help="Final multiplier for the centered detrended ankle joint angle."),
) -> None:
    """Append signed leg, foot, and ankle-joint angles to a coordinate CSV."""
    _run_review_coordinates(csv_file, start_index=start_index, ankle_joint_scale=ankle_joint_scale)


def _manifest_error(message: str) -> typer.BadParameter:
    """Create a manifest error with a consistent Typer parameter reference."""
    return typer.BadParameter(message, param_hint="manifest")


def _validate_bulk_options(command: BulkCommand, entry_number: int, options: object) -> dict[str, object]:
    """Validate command-specific JSON options before starting any manifest job."""
    if options is None:
        return {}
    if not isinstance(options, dict):
        raise _manifest_error(f"{command} entry {entry_number} options must be an object")

    constraints = BULK_OPTION_CONSTRAINTS[command]
    unknown = set(options) - set(constraints)
    if unknown:
        names = ", ".join(sorted(str(name) for name in unknown))
        raise _manifest_error(f"{command} entry {entry_number} has unsupported option(s): {names}")

    validated: dict[str, object] = {}
    for name, value in options.items():
        expected_type, minimum = constraints[name]
        valid = (
            (expected_type == "boolean" and isinstance(value, bool))
            or (expected_type == "string" and isinstance(value, str))
            or (expected_type == "integer" and type(value) is int and (minimum is None or value >= minimum))
            or (
                expected_type == "number"
                and type(value) in {int, float}
                and (minimum is None or value >= minimum)
            )
        )
        if not valid:
            limit = "" if minimum is None else f" greater than or equal to {minimum:g}"
            raise _manifest_error(
                f"{command} entry {entry_number} option {name!r} must be a {expected_type}{limit}"
            )
        validated[name] = value
    return validated


def _load_bulk_jobs(manifest: Path) -> list[BulkJob]:
    """Load a grouped JSON manifest and resolve every job path from its folder."""
    try:
        contents = json.loads(manifest.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise _manifest_error(f"invalid JSON: {error.msg}") from error
    except OSError as error:
        raise _manifest_error(str(error)) from error
    if not isinstance(contents, dict):
        raise _manifest_error("manifest must be an object with segment and/or review-coordinates arrays")

    allowed_commands = set(BULK_OPTION_CONSTRAINTS)
    unknown = set(contents) - allowed_commands
    if unknown:
        names = ", ".join(sorted(str(name) for name in unknown))
        raise _manifest_error(f"manifest has unsupported command group(s): {names}")

    jobs: list[BulkJob] = []
    for command in ("segment", "review-coordinates"):
        entries = contents.get(command, [])
        if not isinstance(entries, list):
            raise _manifest_error(f"{command} must be an array")
        for entry_number, entry in enumerate(entries, start=1):
            if isinstance(entry, str):
                csv_path, options = entry, {}
            elif isinstance(entry, dict):
                if set(entry) - {"csv_file", "options"}:
                    raise _manifest_error(f"{command} entry {entry_number} has unsupported fields")
                csv_path = entry.get("csv_file")
                options = entry.get("options")
            else:
                raise _manifest_error(f"{command} entry {entry_number} must be a path string or object")
            if not isinstance(csv_path, str) or not csv_path.strip():
                raise _manifest_error(f"{command} entry {entry_number} csv_file must be a non-empty path string")
            path = Path(csv_path)
            resolved_path = path.resolve() if path.is_absolute() else (manifest.parent / path).resolve()
            jobs.append(BulkJob(command, resolved_path, _validate_bulk_options(command, entry_number, options)))
    if not jobs:
        raise _manifest_error("manifest must contain at least one job")
    return jobs


@app.command()
def bulk(
    manifest: Path = typer.Argument(..., exists=True, readable=True, help="Grouped JSON manifest of target CSV paths."),
    points: int = typer.Option(101, min=2, help="Samples on the segment normalized 0–100% grid."),
    accept: str = typer.Option("", help="Cycle indexes/ranges to force accept for every segment job."),
    reject: str = typer.Option("", help="Cycle indexes/ranges to force reject for every segment job."),
    no_plot: bool = typer.Option(False, help="Do not generate normalized-cycle PNGs for segment jobs."),
    plot_channels: str = typer.Option(",".join(DEFAULT_CHANNELS), help="Comma-separated normalized channels to plot."),
    robust_z_max: float = typer.Option(3.5, min=0, help="Median/MAD timing outlier z-score threshold."),
    cluster_log_duration_tolerance: float = typer.Option(0.35, min=0, help="Maximum log-duration difference for cluster neighbours."),
    cluster_stance_percent_tolerance: float = typer.Option(10, min=0, help="Maximum stance-percent difference for cluster neighbours."),
    cluster_min_cycles: int = typer.Option(5, min=2, help="Minimum cycles required for automatic timing acceptance."),
    start_index: int = typer.Option(1, min=1, help="One-based first data-row index for coordinate jobs."),
    ankle_joint_scale: float = typer.Option(1.0, help="Final multiplier for coordinate-job ankle joint angle."),
) -> None:
    """Run grouped segment and coordinate-review jobs from a JSON manifest."""
    jobs = _load_bulk_jobs(manifest)
    results: list[tuple[Path, str, str]] = []
    segment_defaults = {
        "points": points,
        "accept": accept,
        "reject": reject,
        "no_plot": no_plot,
        "plot_channels": plot_channels,
        "robust_z_max": robust_z_max,
        "cluster_log_duration_tolerance": cluster_log_duration_tolerance,
        "cluster_stance_percent_tolerance": cluster_stance_percent_tolerance,
        "cluster_min_cycles": cluster_min_cycles,
    }
    coordinate_defaults = {"start_index": start_index, "ankle_joint_scale": ankle_joint_scale}

    # Groups run in a fixed command order while retaining each array's order.
    # Merge per-file options after CLI defaults, then isolate failures so a bad
    # source does not discard later results. Segment jobs never prompt or open a GUI.
    for index, job in enumerate(jobs, start=1):
        console.print(f"[bold]({index}/{len(jobs)}) {job.command}:[/bold] {job.csv_file}")
        try:
            if not job.csv_file.is_file():
                raise FileNotFoundError(f"CSV file does not exist: {job.csv_file}")
            if job.command == "segment":
                _run_segment(job.csv_file, yes=True, no_show_review_plot=True, **(segment_defaults | job.options))
            else:
                _run_review_coordinates(job.csv_file, **(coordinate_defaults | job.options))
        except Exception as error:
            detail = str(error) or error.__class__.__name__
            results.append((job.csv_file, "failed", detail))
            console.print(f"[red]Failed:[/red] {detail}")
        else:
            results.append((job.csv_file, "completed", ""))
            console.print("[green]Completed.[/green]")

    table = Table(title="Bulk processing summary")
    table.add_column("CSV path")
    table.add_column("Status")
    table.add_column("Details")
    for csv_file, status, detail in results:
        table.add_row(str(csv_file), status, detail, style="green" if status == "completed" else "red")
    console.print(table)
    failed = sum(status == "failed" for _, status, _ in results)
    console.print(f"Completed {len(results) - failed}/{len(results)} job(s); {failed} failed.")
    if failed:
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
