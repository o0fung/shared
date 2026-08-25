from threading import Event
from pathlib import Path

import pytest
import typer

from gait_analysis import cli
from gait_analysis.output import SavedReviewDecision, restore_saved_review_decisions
from gait_analysis.segmenter import Cycle


def test_artifact_dir_mirrors_nested_data_parent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    csv_file = tmp_path / "data" / "Joint coordinates" / "P1 ZGJ" / "rr_20260821_110517" / "walk.csv"
    csv_file.parent.mkdir(parents=True)
    csv_file.touch()
    monkeypatch.chdir(tmp_path)

    assert cli._artifact_dir(csv_file) == (
        tmp_path / "output" / "Joint coordinates" / "P1 ZGJ" / "rr_20260821_110517"
    )


def test_artifact_dir_mirrors_supplementary_data_parent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    csv_file = tmp_path / "data" / "Joint coordinates" / "P1 ZGJ" / "test Akr_ZGJ LEFT_P1.csv"
    csv_file.parent.mkdir(parents=True)
    csv_file.touch()
    monkeypatch.chdir(tmp_path)

    assert cli._artifact_dir(csv_file) == tmp_path / "output" / "Joint coordinates" / "P1 ZGJ"


def test_artifact_dir_rejects_csv_outside_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    csv_file = tmp_path / "outside.csv"
    csv_file.touch()
    (tmp_path / "data").mkdir()
    monkeypatch.chdir(tmp_path)

    with pytest.raises(typer.BadParameter, match="CSV must be located under"):
        cli._artifact_dir(csv_file)


def test_parse_indices_ignores_empty_comma_tokens() -> None:
    assert cli._parse_indices("12-15,") == {12, 13, 14, 15}
    assert cli._parse_indices(",2,,4-5,") == {2, 4, 5}


def test_prompt_pumps_review_events_until_terminal_input_finishes(monkeypatch) -> None:
    release = Event()
    calls: list[object] = []

    def prompt() -> str:
        release.wait(timeout=1)
        return "done"

    def pump(review: object) -> None:
        calls.append(review)
        release.set()

    monkeypatch.setattr(cli, "process_trial_review_events", pump)
    review = object()
    assert cli._prompt_while_review_open(prompt, review) == "done"
    assert calls
    assert all(call is review for call in calls)


def test_current_forced_decision_overrides_restored_decision() -> None:
    cycle = Cycle(
        index=2,
        start_row=10,
        end_row=20,
        start_ms=100.0,
        end_ms=300.0,
        state_path=[1, 2, 5, 6, 7],
    )
    saved = SavedReviewDecision(
        cycle_index=2,
        start_row=10,
        end_row=20,
        start_ms=100.0,
        end_ms=300.0,
        state_path="1→2→5→6→7",
        accepted=False,
        user_decision="forced_reject",
    )

    assert restore_saved_review_decisions([cycle], [saved]) == (1, 0)
    cli._apply_forced_decisions([cycle], {2}, set())

    assert (cycle.accepted, cycle.user_decision, cycle.reason) == (
        True,
        "forced_accept",
        "accepted by user",
    )
