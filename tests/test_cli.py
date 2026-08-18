from threading import Event

from gait_analysis import cli


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
