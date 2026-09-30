"""Lossless factoring of observation timestamps out of stored JSON text."""

from __future__ import annotations

import hashlib
import json

OBSERVATION_FIELDS = frozenset({"first_seen_at", "last_seen_at", "last_checked_at"})


def timestamp_spans(text: str) -> list[tuple[int, int]]:
    decoder = json.JSONDecoder()
    cursor = 0

    def whitespace(offset):
        while offset < len(text) and text[offset] in " \t\r\n":
            offset += 1
        return offset

    cursor = whitespace(cursor)
    if cursor >= len(text) or text[cursor] != "{":
        raise ValueError("normalized sighting must be a JSON object")
    cursor = whitespace(cursor + 1)
    spans = []
    while cursor < len(text) and text[cursor] != "}":
        key, cursor = decoder.raw_decode(text, cursor)
        cursor = whitespace(cursor)
        if not isinstance(key, str) or text[cursor : cursor + 1] != ":":
            raise ValueError("invalid normalized sighting JSON")
        start = whitespace(cursor + 1)
        _, cursor = decoder.raw_decode(text, start)
        if key in OBSERVATION_FIELDS:
            spans.append((start, cursor))
        cursor = whitespace(cursor)
        if text[cursor : cursor + 1] == ",":
            cursor = whitespace(cursor + 1)
            if text[cursor : cursor + 1] == "}":
                raise ValueError("invalid trailing JSON comma")
        elif text[cursor : cursor + 1] != "}":
            raise ValueError("invalid normalized sighting JSON")
    if text[cursor : cursor + 1] != "}" or whitespace(cursor + 1) != len(text):
        raise ValueError("invalid normalized sighting JSON")
    return spans


def replace_spans(text, spans, values):
    pieces = []
    cursor = 0
    for (start, end), value in zip(spans, values, strict=True):
        pieces.extend((text[cursor:start], value))
        cursor = end
    pieces.append(text[cursor:])
    return "".join(pieces)


def split_observation(normalized_json: str) -> tuple[str, str]:
    spans = timestamp_spans(normalized_json)
    values = [normalized_json[start:end] for start, end in spans]
    template = replace_spans(normalized_json, spans, ["null"] * len(spans))
    return template, json.dumps(values, ensure_ascii=False, separators=(",", ":"))


def restore_observation(template: str, observation_json: str) -> str:
    values = json.loads(observation_json)
    if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
        raise ValueError("invalid observation values")
    return replace_spans(template, timestamp_spans(template), values)


def storage_digest(source, source_id, template, raw_metadata_json, raw_item_json):
    # Separate from article content_hash; include every retained byte and scope by identity.
    payload = json.dumps(
        [1, source, source_id, template, raw_metadata_json, raw_item_json],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()
    return "sha256:" + hashlib.sha256(payload).hexdigest()
