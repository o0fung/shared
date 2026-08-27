from threading import Event
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from gait_analysis import cli
from gait_analysis.output import SavedReviewDecision, restore_saved_review_decisions
from gait_analysis.segmenter import Cycle


runner = CliRunner()


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


def test_artifact_dir_uses_input_data_root_when_called_from_nested_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    csv_file = tmp_path / "data" / "Joint coordinates" / "P1 ZGJ" / "test Akr_ZGJ LEFT_P1.csv"
    csv_file.parent.mkdir(parents=True)
    csv_file.touch()
    monkeypatch.chdir(csv_file.parent)

    assert cli._artifact_dir(Path(csv_file.name)) == tmp_path / "output" / "Joint coordinates" / "P1 ZGJ"


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


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("y", "write"),
        ("yes", "write"),
        ("r", "review"),
        ("review", "review"),
        ("", "abort"),
        ("no", "abort"),
        ("unexpected", "abort"),
    ],
)
def test_parse_write_action(value: str, expected: str) -> None:
    assert cli._parse_write_action(value) == expected


def test_interactive_review_repeats_after_revise_choice(monkeypatch, tmp_path: Path) -> None:
    cycle = Cycle(
        index=2,
        start_row=10,
        end_row=20,
        start_ms=100.0,
        end_ms=300.0,
        state_path=[1, 2, 5, 6, 7],
    )
    prompt_values = iter(["2", "", "", "2"])
    actions = iter(["review", "write"])
    refreshed_decisions: list[tuple[bool, str]] = []

    monkeypatch.setattr(cli, "_prompt_text", lambda *_: next(prompt_values))
    monkeypatch.setattr(cli, "_confirm_write", lambda _: next(actions))
    monkeypatch.setattr(cli, "_show_review", lambda _: None)
    monkeypatch.setattr(
        cli,
        "refresh_trial_review",
        lambda _, cycles, __: refreshed_decisions.append((cycles[0].accepted, cycles[0].user_decision)),
    )

    cli._review_decisions_interactively([cycle], object(), True, tmp_path / "review.png")

    assert refreshed_decisions == [(True, "forced_accept"), (False, "forced_reject")]


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


def test_load_bulk_jobs_resolves_paths_and_supports_per_file_options(tmp_path: Path) -> None:
    walk_csv = tmp_path / "data" / "walk.csv"
    coordinates_csv = tmp_path / "data" / "coordinates.csv"
    walk_csv.parent.mkdir()
    walk_csv.touch()
    coordinates_csv.touch()
    manifest = tmp_path / "jobs.json"
    manifest.write_text(
        """{
          "segment": ["data/walk.csv"],
          "review-coordinates": [
            {"csv_file": "data/coordinates.csv", "options": {"start_index": 3}}
          ]
        }""",
        encoding="utf-8",
    )

    assert cli._load_bulk_jobs(manifest) == [
        cli.BulkJob("segment", walk_csv.resolve(), {}),
        cli.BulkJob("review-coordinates", coordinates_csv.resolve(), {"start_index": 3}),
    ]


@pytest.mark.parametrize(
    "contents",
    [
        "[]",
        "{}",
        '{"unknown": []}',
        '{"segment": "data/walk.csv"}',
        '{"segment": [42]}',
        '{"segment": [{"options": {}}]}',
        '{"segment": [{"csv_file": "data/walk.csv", "options": {"unknown": true}}]}',
        '{"segment": [{"csv_file": "data/walk.csv", "options": {"points": 1}}]}',
    ],
)
def test_load_bulk_jobs_rejects_invalid_manifest_shapes(tmp_path: Path, contents: str) -> None:
    manifest = tmp_path / "jobs.json"
    manifest.write_text(contents, encoding="utf-8")

    with pytest.raises(typer.BadParameter):
        cli._load_bulk_jobs(manifest)


def test_load_bulk_jobs_rejects_invalid_json(tmp_path: Path) -> None:
    manifest = tmp_path / "jobs.json"
    manifest.write_text("[", encoding="utf-8")

    with pytest.raises(typer.BadParameter, match="invalid JSON"):
        cli._load_bulk_jobs(manifest)


def test_bulk_runs_command_groups_in_order_and_overrides_file_options(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    paths = {name: data_dir / f"{name}.csv" for name in ("walk_01", "walk_02", "coordinates_01", "coordinates_02")}
    for path in paths.values():
        path.touch()
    manifest = tmp_path / "jobs.json"
    manifest.write_text(
        """{
          "segment": [
            "data/walk_01.csv",
            {"csv_file": "data/walk_02.csv", "options": {"points": 51, "no_plot": true}}
          ],
          "review-coordinates": [
            "data/coordinates_01.csv",
            {"csv_file": "data/coordinates_02.csv", "options": {"start_index": 4, "ankle_joint_scale": 0.8}}
          ]
        }""",
        encoding="utf-8",
    )
    calls: list[tuple[str, Path, dict[str, object]]] = []
    monkeypatch.setattr(cli, "_run_segment", lambda path, **kwargs: calls.append(("segment", path, kwargs)))
    monkeypatch.setattr(
        cli,
        "_run_review_coordinates",
        lambda path, **kwargs: calls.append(("review-coordinates", path, kwargs)),
    )

    result = runner.invoke(cli.app, ["bulk", str(manifest), "--points", "25", "--start-index", "2"])

    assert result.exit_code == 0, result.output
    assert [(command, path) for command, path, _ in calls] == [
        ("segment", paths["walk_01"].resolve()),
        ("segment", paths["walk_02"].resolve()),
        ("review-coordinates", paths["coordinates_01"].resolve()),
        ("review-coordinates", paths["coordinates_02"].resolve()),
    ]
    assert calls[0][2]["points"] == 25
    assert calls[1][2]["points"] == 51
    assert calls[1][2]["no_plot"] is True
    assert calls[0][2]["yes"] is True
    assert calls[0][2]["no_show_review_plot"] is True
    assert calls[2][2] == {"start_index": 2, "ankle_joint_scale": 1.0}
    assert calls[3][2] == {"start_index": 4, "ankle_joint_scale": 0.8}
    assert "Completed 4/4 job(s); 0 failed." in result.output


def test_bulk_continues_after_processing_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    first_csv = tmp_path / "data" / "first.csv"
    second_csv = tmp_path / "data" / "second.csv"
    first_csv.parent.mkdir()
    first_csv.touch()
    second_csv.touch()
    manifest = tmp_path / "jobs.json"
    manifest.write_text(
        '{"review-coordinates": ["data/first.csv", "data/second.csv"]}',
        encoding="utf-8",
    )
    calls: list[Path] = []

    def run_coordinate_review(path: Path, **_: object) -> None:
        calls.append(path)
        if path == first_csv.resolve():
            raise RuntimeError("processing failed")

    monkeypatch.setattr(cli, "_run_review_coordinates", run_coordinate_review)

    result = runner.invoke(cli.app, ["bulk", str(manifest)])

    assert result.exit_code == 1, result.output
    assert calls == [first_csv.resolve(), second_csv.resolve()]
    assert "processing failed" in result.output
    assert "Completed 1/2 job(s); 1 failed." in result.output
