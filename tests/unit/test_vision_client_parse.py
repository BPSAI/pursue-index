"""Parsing a vision reply into the page shape the sidecar schema defines.

The parser is the boundary between a free-form reply and a structured page,
so it is where an ``observations`` list becomes the entries the schema
defines. Reaching the parser requires no API call: it takes the reply text
directly.
"""

from __future__ import annotations

import json

from pursue_index.vision.client import _parse_response


def test_a_fenced_json_reply_parses_into_the_page_shape() -> None:
    payload = {
        "image_type": "photograph",
        "description": "A described image.",
        "visible_text": "",
        "observations": [{"claim": "A concrete claim", "confidence": "high"}],
    }
    parsed = _parse_response("```json\n" + json.dumps(payload) + "\n```")
    assert parsed["description"] == "A described image."
    assert parsed["observations"][0]["claim"] == "A concrete claim"
    assert parsed["observations"][0]["kind"] == "observation"


def test_observations_that_do_not_carry_a_claim_are_left_out() -> None:
    payload = {
        "description": "A described image.",
        "observations": ["a bare string", {"kind": "observation"},
                         {"claim": "A concrete claim"}],
    }
    parsed = _parse_response(json.dumps(payload))
    assert [o["claim"] for o in parsed["observations"]] == ["A concrete claim"]


def test_observations_given_as_a_bare_object_yield_an_empty_list() -> None:
    parsed = _parse_response(json.dumps({"description": "x", "observations": {}}))
    assert parsed["observations"] == []


def test_a_reply_that_is_not_json_keeps_its_text_as_the_description() -> None:
    parsed = _parse_response("The image shows a hangar.")
    assert parsed["description"] == "The image shows a hangar."
    assert parsed["observations"] == []
