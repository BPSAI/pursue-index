"""Polling tolerates a bounded number of unusable status responses.

A submitted job is already paid for, and its status endpoint answers many
times over the life of the job, so a single unusable answer part-way through
is not a reason to drop the job. Polling therefore carries a retry budget of
its own, counted across the poll and reset by every usable answer, and gives
up with a stated reason once the budget is spent. The budget is separate from
the wall-clock deadline: neither one substitutes for the other.
"""

from __future__ import annotations

import httpx
import pytest

from pursue_index.transcribe import client


def _resp(status_code: int, payload: dict[str, object]) -> httpx.Response:
    return httpx.Response(status_code, json=payload)


def test_a_single_unusable_status_response_does_not_drop_the_job() -> None:
    answers = iter([_resp(503, {}), _resp(200, {"status": "completed"})])

    def fake_get(url: str, **kwargs: object) -> httpx.Response:
        return next(answers)

    data = client.poll_transcript(
        "tid-1", api_key="k", get=fake_get, sleep=lambda s: None
    )
    assert data["status"] == "completed"


def test_a_transport_error_mid_poll_is_also_within_the_budget() -> None:
    answers: list[object] = [
        httpx.ConnectError("connection reset"),
        _resp(200, {"status": "completed"}),
    ]

    def fake_get(url: str, **kwargs: object) -> httpx.Response:
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer  # type: ignore[return-value]

    data = client.poll_transcript(
        "tid-1", api_key="k", get=fake_get, sleep=lambda s: None
    )
    assert data["status"] == "completed"


def test_the_budget_is_bounded_and_gives_up_with_a_stated_reason() -> None:
    attempts: list[int] = []

    def fake_get(url: str, **kwargs: object) -> httpx.Response:
        attempts.append(1)
        return _resp(503, {})

    with pytest.raises(client.SubmitError, match="503"):
        client.poll_transcript(
            "tid-1", api_key="k", get=fake_get, sleep=lambda s: None,
            max_poll_retries=2,
        )
    assert len(attempts) == 3  # the first answer plus the whole budget


def test_the_budget_resets_after_a_usable_answer() -> None:
    answers = iter(
        [
            _resp(503, {}),
            _resp(200, {"status": "processing"}),
            _resp(503, {}),
            _resp(200, {"status": "completed"}),
        ]
    )

    def fake_get(url: str, **kwargs: object) -> httpx.Response:
        return next(answers)

    data = client.poll_transcript(
        "tid-1", api_key="k", get=fake_get, sleep=lambda s: None,
        max_poll_retries=1,
    )
    assert data["status"] == "completed"


def test_the_wall_clock_deadline_still_applies_while_retrying() -> None:
    clock = iter([0.0, 0.0, 5.0, 11.0, 12.0, 13.0])

    def fake_now() -> float:
        return next(clock)

    def fake_get(url: str, **kwargs: object) -> httpx.Response:
        return _resp(503, {})

    with pytest.raises(client.PollTimeoutError):
        client.poll_transcript(
            "tid-1", api_key="k", get=fake_get, timeout_s=10.0,
            poll_interval_s=1.0, sleep=lambda s: None, now=fake_now,
            max_poll_retries=10,
        )
