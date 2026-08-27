"""White-theme Matplotlib plots for interactive review and normalized cycles."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import matplotlib

import matplotlib.pyplot as plt
import numpy as np

from .segmenter import QUALITY_ACCEPTED, QUALITY_REVIEW, Cycle


DEFAULT_CHANNELS = ("walk_state", "walk_pos_rad", "walk_vel_rad_s", "walk_tq_nm", "walk_tilt_forward_deg", "walk_gyr_y")
TRIAL_REVIEW_CHANNELS = (
    "walk_tilt_forward_deg",
    "walk_gyr_z",
    "walk_tq_nm",
    "walk_pos_rad",
    "walk_out",
    "walk_state",
)
DISCRETE_TRIAL_CHANNELS = {"walk_out", "walk_state"}


@dataclass
class TrialReviewFigure:
    figure: object
    axes: list[object]
    timestamps: np.ndarray
    overlay_artists: list[object]


def plot_normalized(records: list[dict[str, float | int]], channels: list[str], output_path: Path, width: float = 12) -> None:
    available = [channel for channel in channels if any(channel in row for row in records)]
    if not available:
        return
    by_cycle: dict[int, list[dict[str, float | int]]] = defaultdict(list)
    for row in records:
        by_cycle[int(row["cycle_index"])].append(row)
    figure, axes = plt.subplots(len(available), 1, figsize=(width, max(3, 2.4 * len(available))), sharex=True)
    if len(available) == 1:
        axes = [axes]
    for axis, channel in zip(axes, available):
        stacked = []
        for cycle_records in by_cycle.values():
            x = [float(row["gait_percent"]) for row in cycle_records]
            y = [float(row[channel]) for row in cycle_records]
            axis.plot(x, y, color="#1976D2", alpha=0.24, linewidth=0.8)
            stacked.append(y)
        axis.plot(x, np.nanmean(np.asarray(stacked), axis=0), color="#D32F2F", linewidth=2, label="mean")
        axis.axhline(0, color="#888888", alpha=0.35, linewidth=0.7)
        axis.grid(alpha=0.15)
        axis.set_ylabel(channel)
        axis.legend(loc="upper right")
    axes[-1].set_xlabel("Gait cycle (%)")
    figure.suptitle("Accepted gait cycles: individual overlays and mean")
    figure.tight_layout()
    figure.savefig(output_path, dpi=180, facecolor="white")
    plt.close(figure)


def statistic_summary_series(summary: list[dict[str, float]]) -> dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """Return publication angle and torque means with their sample SDs."""
    required = {
        "gait_percent",
        "ankle_joint_angle_deg_mean",
        "ankle_joint_angle_deg_sd",
        "leg_tilt_angle_deg_mean",
        "leg_tilt_angle_deg_sd",
        "foot_tilt_angle_deg_mean",
        "foot_tilt_angle_deg_sd",
        "walk_tq_nm_mean",
        "walk_tq_nm_sd",
    }
    if not summary or not required.issubset(summary[0]):
        return {}
    gait_percent = np.asarray([record["gait_percent"] for record in summary], dtype=float)
    ankle_mean = np.asarray([record["ankle_joint_angle_deg_mean"] for record in summary], dtype=float)
    ankle_sd = np.asarray([record["ankle_joint_angle_deg_sd"] for record in summary], dtype=float)
    leg_mean = np.asarray([record["leg_tilt_angle_deg_mean"] for record in summary], dtype=float)
    leg_sd = np.asarray([record["leg_tilt_angle_deg_sd"] for record in summary], dtype=float)
    foot_mean = np.asarray([record["foot_tilt_angle_deg_mean"] for record in summary], dtype=float)
    foot_sd = np.asarray([record["foot_tilt_angle_deg_sd"] for record in summary], dtype=float)
    torque_mean = np.asarray([record["walk_tq_nm_mean"] for record in summary], dtype=float)
    torque_sd = np.asarray([record["walk_tq_nm_sd"] for record in summary], dtype=float)

    return {
        "Ankle Joint Angle": (gait_percent, ankle_mean, ankle_sd),
        "Leg Tilt Angle": (gait_percent, leg_mean, leg_sd),
        "Foot Tilt Angle": (gait_percent, foot_mean, foot_sd),
        "Torque Output": (gait_percent, torque_mean, torque_sd),
    }


def plot_r_statistic(summary: list[dict[str, float]], output_path: Path) -> bool:
    """Write four mean ± sample-SD gait angle and torque panels."""
    series = statistic_summary_series(summary)
    if not series:
        return False
    figure, axes = plt.subplots(4, 1, figsize=(7.2, 10.4), sharex=True)
    gait_ticks = (0, 25, 50, 75, 100)
    for axis, (title, (gait_percent, mean, sd)) in zip(axes, series.items()):
        axis.plot(gait_percent, mean, color="#1A1A1A", linewidth=1.8)
        axis.fill_between(gait_percent, mean - sd, mean + sd, color="#4D4D4D", alpha=0.22, linewidth=0)
        axis.axhline(0, color="#7F7F7F", linewidth=0.7)
        axis.set_title(title, loc="left", fontsize=11, fontweight="bold")
        axis.set_xlim(0, 100)
        axis.set_xticks(gait_ticks)
        if title == "Torque Output":
            axis.set_ylabel("Torque Output (Nm)")
        else:
            axis.set_ylabel("Angle (°)")
        axis.grid(axis="both", color="#D9D9D9", linewidth=0.6)
    axes[-1].set_xticks(gait_ticks, labels=("0%", "25%", "50%", "75%", "100%"))
    axes[-1].set_xlabel("Gait cycle (%)")
    figure.tight_layout()
    figure.savefig(output_path, dpi=300, facecolor="white", bbox_inches="tight")
    plt.close(figure)
    return True


def _numeric(values: list[str | None]) -> np.ndarray:
    """Preserve missing telemetry as NaN so matplotlib draws visible gaps."""
    parsed: list[float] = []
    for value in values:
        try:
            parsed.append(float(value) if value not in (None, "") else np.nan)
        except ValueError:
            parsed.append(np.nan)
    return np.asarray(parsed)


def _draw_cycle_overlays(review: TrialReviewFigure, cycles: list[Cycle]) -> None:
    for artist in review.overlay_artists:
        artist.remove()
    review.overlay_artists.clear()
    timestamps = review.timestamps
    axes = review.axes

    # Each candidate's source rows are already causally determined. Shading and
    # labels give the terminal selection indexes a direct visual counterpart
    # without changing segmentation decisions.
    for cycle in cycles:
        start_index = cycle.start_row - 1
        end_index = cycle.end_row - 1
        if not 0 <= start_index < len(timestamps) or not 0 <= end_index < len(timestamps):
            continue
        start = timestamps[start_index]
        # Quality color represents stance only: a transition into state 6 begins
        # swing, so keep states 6–7 unshaded. Incomplete candidates without a
        # state-6 entry retain their final-row span to show their review status.
        stance_end_ms = cycle.phase_entry_ms.get(6)
        if stance_end_ms is not None and np.isfinite(stance_end_ms):
            end = stance_end_ms / 1_000
        else:
            end = cycle.end_ms / 1_000 if cycle.end_ms is not None and np.isfinite(cycle.end_ms) else timestamps[end_index]
        if not np.isfinite(start) or not np.isfinite(end):
            continue
        color = (
            "#2E7D32" if cycle.quality_status == QUALITY_ACCEPTED
            else "#F9A825" if cycle.quality_status == QUALITY_REVIEW
            else "#C62828"
        )
        alpha = 0.07 if cycle.quality_status == QUALITY_ACCEPTED else 0.12
        review.overlay_artists.extend(axis.axvspan(start, end, color=color, alpha=alpha, linewidth=0) for axis in axes)
        review.overlay_artists.append(
            axes[0].annotate(
                str(cycle.index) if cycle.step_code is None else f"{cycle.index} ({cycle.step_code})",
                xy=(start, 0.98 - ((cycle.index - 1) % 3) * 0.12),
                xycoords=("data", "axes fraction"),
                xytext=(2, 0),
                textcoords="offset points",
                color=color,
                fontsize=7,
                va="top",
                fontweight="bold",
            )
        )
    review.figure.canvas.draw_idle()


def create_trial_review(rows: list[dict[str, str]], cycles: list[Cycle]) -> TrialReviewFigure | None:
    """Create an adjustable full-trial figure without opening or closing it."""
    timestamps = _numeric([row.get("t_ms") for row in rows]) / 1_000
    available = [channel for channel in TRIAL_REVIEW_CHANNELS if any(row.get(channel, "") != "" for row in rows)]
    if not available:
        return None
    figure, axes = plt.subplots(len(available), 1, figsize=(14, max(4, 2.2 * len(available))), sharex=True)
    if len(available) == 1:
        axes = [axes]
    for axis, channel in zip(axes, available):
        values = _numeric([row.get(channel) for row in rows])
        if channel in DISCRETE_TRIAL_CHANNELS:
            axis.step(timestamps, values, where="post", color="#1565C0", linewidth=0.9)
        else:
            axis.plot(timestamps, values, color="#1565C0", linewidth=0.8)
        axis.axhline(0, color="#888888", alpha=0.3, linewidth=0.7)
        axis.grid(alpha=0.15)
        axis.set_ylabel(channel)
    axes[-1].set_xlabel("Trial time (s)")
    figure.suptitle("Full trial review: green accepted, yellow review, red rejected; labels are cycle indexes")
    figure.tight_layout()
    review = TrialReviewFigure(figure=figure, axes=list(axes), timestamps=timestamps, overlay_artists=[])
    _draw_cycle_overlays(review, cycles)
    return review


def save_trial_review(review: TrialReviewFigure, output_path: Path) -> None:
    review.figure.savefig(output_path, dpi=180, facecolor="white")


def refresh_trial_review(review: TrialReviewFigure, cycles: list[Cycle], output_path: Path) -> None:
    """Update acceptance shading after terminal overrides and rewrite the PNG."""
    _draw_cycle_overlays(review, cycles)
    save_trial_review(review, output_path)


def open_trial_review(review: TrialReviewFigure) -> bool:
    backend_is_interactive = not matplotlib.get_backend().lower().endswith("agg")
    if not backend_is_interactive:
        return False
    plt.show(block=False)
    plt.pause(0.1)
    return True


def process_trial_review_events(review: TrialReviewFigure, interval_s: float = 0.05) -> None:
    """Keep the native Matplotlib toolbar responsive during terminal input."""
    if plt.fignum_exists(review.figure.number):
        plt.pause(interval_s)


def close_trial_review(review: TrialReviewFigure | None) -> None:
    if review is not None:
        plt.close(review.figure)


def plot_trial_review(rows: list[dict[str, str]], cycles: list[Cycle], output_path: Path, *, show: bool = False) -> bool:
    """Compatibility wrapper for static exports and blocking inspection."""
    review = create_trial_review(rows, cycles)
    if review is None:
        return False
    save_trial_review(review, output_path)
    shown = open_trial_review(review) if show else False
    if show and shown:
        plt.show()
    close_trial_review(review)
    return shown
