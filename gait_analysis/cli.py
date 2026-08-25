"""Typer command line interface for causal gait-cycle review."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
from typing import Callable, TypeVar

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
from .segmenter import SegmentationConfig, segment_rows

app = typer.Typer(help="Causally segment and normalize rr_app walk CSV files.")
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
    """Mirror an input CSV's parent directory from data/ into output/."""
    data_root = Path("data").resolve()
    try:
        relative_parent = csv_file.resolve().parent.relative_to(data_root)
    except ValueError as error:
        raise typer.BadParameter(f"CSV must be located under {data_root}", param_hint="csv_file") from error
    return Path("output").resolve() / relative_parent


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


def _confirm_write(review_window: object | None) -> bool:
    if review_window is None:
        return typer.confirm("Write review, normalized CSV, and plot?")
    console.print("Write review, normalized CSV, and plot? [y/N]: ", end="")
    value = _prompt_while_review_open(sys.stdin.readline, review_window)
    return value.strip().lower() in {"y", "yes"}


def _show_review(cycles: list) -> None:
    table = Table(title="Causal gait-cycle review")
    for column in ("Index", "Rows", "State path", "Cycle ms", "Stance ms (%)", "Swing ms (%)", "Decision / reason"):
        table.add_column(column)
    for cycle in cycles:
        report = cycle_report(cycle)
        stance = report["stance_ms"]
        swing = report["swing_ms"]
        stance_text = "-" if stance is None else f"{stance:.0f} ({report['stance_percent']:.1f}%)"
        swing_text = "-" if swing is None else f"{swing:.0f} ({report['swing_percent']:.1f}%)"
        decision = "ACCEPT" if cycle.accepted else "REJECT"
        reason = cycle.reason or "valid"
        table.add_row(
            str(cycle.index),
            f"{cycle.start_row}-{cycle.end_row}",
            str(report["state_path"]),
            "-" if report["cycle_ms"] is None else f"{report['cycle_ms']:.0f}",
            stance_text,
            swing_text,
            f"{decision}: {reason}",
            style="green" if cycle.accepted else "red",
        )
    console.print(table)


def _apply_forced_decisions(cycles: list, forced_accept: set[int], forced_reject: set[int]) -> None:
    """Apply current-run choices after restored decisions so explicit input wins."""
    for cycle in cycles:
        if cycle.index in forced_accept:
            cycle.accepted, cycle.user_decision, cycle.reason = True, "forced_accept", "accepted by user"
        elif cycle.index in forced_reject:
            cycle.accepted, cycle.user_decision, cycle.reason = False, "forced_reject", "rejected by user"


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
    stance_max_ms: float = typer.Option(9_000, min=0, help="Maximum allowed stance-base dwell."),
    cycle_max_ms: float = typer.Option(10_000, min=0, help="Maximum allowed completed cycle duration."),
    wrap_max_ms: float = typer.Option(2_000, min=0, help="Maximum MID_SWING-to-contact confirmation duration."),
) -> None:
    """Review walk-state cycles, then write accepted normalized telemetry."""
    headers, rows = read_csv(csv_file)
    if not {"t_ms", "walk_state"}.issubset(headers):
        raise typer.BadParameter("CSV must contain t_ms and walk_state columns")
    config = SegmentationConfig(stance_max_ms=stance_max_ms, cycle_max_ms=cycle_max_ms, wrap_max_ms=wrap_max_ms)
    cycles = segment_rows(rows, config)
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
            console.print("The review plot remains open while you enter index ranges below.")
            active_review_window = review_window if shown else None
            forced_accept = _parse_indices(
                _prompt_text("Force accept indexes (blank keeps restored or auto decision)", "", active_review_window)
            )
            forced_reject = _parse_indices(
                _prompt_text("Force reject indexes (blank keeps restored or auto decision)", "", active_review_window)
            )
        _apply_forced_decisions(cycles, forced_accept, forced_reject)

        if review_window is not None:
            refresh_trial_review(review_window, cycles, trial_plot_path)
        _show_review(cycles)
        active_review_window = review_window if shown else None
        if not yes and not _confirm_write(active_review_window):
            raise typer.Abort()

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


if __name__ == "__main__":
    app()
