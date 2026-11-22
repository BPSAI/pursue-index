"""``--allow-over-cap``: lift the growth cap for named cards, with a stated reason."""

from __future__ import annotations

import argparse
from typing import Any


def add_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--allow-over-cap",
        type=lambda v: frozenset(c.strip() for c in v.split(",") if c.strip()),
        default=frozenset(),
        metavar="CARD_ID[,CARD_ID...]",
        help="Lift the x2-last-size byte cap for exactly these cards in this run (the "
        "absolute ceiling still applies). Requires --reason.",
    )
    parser.add_argument("--reason", default="", help="Why the cap is lifted; printed with the cards.")


def validate(parser: argparse.ArgumentParser, args: Any) -> None:
    if args.allow_over_cap and not args.reason.strip():
        parser.error("--allow-over-cap requires --reason TEXT")
    if args.reason.strip() and not args.allow_over_cap:
        parser.error("--reason only applies with --allow-over-cap")


def announce(args: Any) -> None:
    if args.allow_over_cap:
        print(
            f"[r2-archive] OVER-CAP ALLOWED for {', '.join(sorted(args.allow_over_cap))}: "
            f"{args.reason.strip()}"
        )
