"""Guard: the vision stage's live paths are reachable only when asked for.

The vision stage calls a vision model, so an invocation that spends must be one
somebody chose to make. Two properties keep that true and are enforced here
rather than left to review, because both are invisible until a bill arrives:

1. No scheduled or triggered workflow runs the stage at all, so no automated
   context can reach the model.
2. Every parameter that turns on live work defaults to off, so a bare
   ``pursue vision run`` previews coverage and nothing else.
"""

from __future__ import annotations

import re
from pathlib import Path

import click

from pursue_index.cli.commands import app

_REPO_ROOT = Path(__file__).resolve().parents[2]
_WORKFLOW_DIR = _REPO_ROOT / ".github" / "workflows"

# Any invocation of the stage, however it is spelled on the command line.
_VISION_INVOCATION = re.compile(r"\bvision\s+run\b")

# The parameters that turn on live examination, and the value each must carry
# when the operator has not named it.
_LIVE_PARAMS = {"run": False, "live_smoke": None}


def _vision_run_command() -> click.Command:
    """The ``pursue vision run`` command object, via the assembled CLI."""
    from typer.main import get_command

    node: click.Command = get_command(app)
    for name in ("vision", "run"):
        node = node.get_command(click.Context(node), name)  # type: ignore[attr-defined]
        assert node is not None, f"the CLI no longer exposes {name!r}"
    return node


def test_no_workflow_invokes_the_vision_stage() -> None:
    """No CI workflow runs the stage, so no automated path reaches the model."""
    offenders = sorted(
        path.name
        for path in _WORKFLOW_DIR.glob("*.yml")
        if _VISION_INVOCATION.search(path.read_text(encoding="utf-8"))
    )
    assert offenders == [], (
        f"workflows invoking the vision stage: {offenders}. Live examination is "
        "operator-attended; CI may not reach it."
    )


def test_live_parameters_are_off_unless_named() -> None:
    """A bare invocation carries neither live flag, so it cannot examine anything."""
    defaults = {p.name: p.default for p in _vision_run_command().params}
    for name, expected in _LIVE_PARAMS.items():
        assert name in defaults, f"{name} is no longer a parameter of the stage"
        assert defaults[name] == expected, (
            f"--{name.replace('_', '-')} must default to {expected!r} so live "
            "examination stays something an operator asks for"
        )
