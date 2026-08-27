"""Typer commands for gait-cycle review and coordinate-angle calculation."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
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
    write_review,
)
from .plotting import (
    DEFAULT_CHANNELS,
    close_trial_review,
    create_trial_review,
    open_trial_review,
    plot_normalized,
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
        console.print(f"Wrote [bold]{review_csv}[/bold], {review_json}, and {normalized_csv}")
        if not no_plot and normalized:
            plot_path = artifact_dir / f"{stem}_normalized_cycles.png"
            plot_normalized(normalized, [value.strip() for value in plot_channels.split(",")], plot_path)
            console.print(f"Wrote [bold]{plot_path}[/bold]")
    finally:
        close_trial_review(review_window)


@app.command()
def review_coordinates(
    csv_file: Path = typer.Argument(..., exists=True, readable=True, help="Coordinate CSV with ankle, foot, and knee X/Y columns."),
    start_index: int = typer.Option(1, min=1, help="One-based first data-row index to include."),
    ankle_joint_scale: float = typer.Option(1.0, help="Final multiplier for the centered detrended ankle joint angle."),
) -> None:
    """Append signed leg, foot, and ankle-joint angles to a coordinate CSV."""
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


if __name__ == "__main__":
    app()
