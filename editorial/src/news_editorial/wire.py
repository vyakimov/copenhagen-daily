"""Recognise agency wire copy carried by a publisher, from the article's own sign-off."""

from __future__ import annotations

import re
from typing import Any

_TAG = re.compile(r"<[^>]+>")


def wire_agency(article: dict[str, Any], signoffs: dict[str, str]) -> str | None:
    """The agency whose sign-off ends an unsigned article, else None.

    A wire piece closes on the agency's name alone, or shared with a foreign agency ("RITZAU/AFP").
    A byline makes the article the outlet's own, and a mention or a photo credit is not a sign-off.
    """
    if article.get("authors"):
        return None
    words = _TAG.sub(" ", article.get("description") or "").split()
    if not words:
        return None
    for agency, signoff in signoffs.items():
        if words[-1] == signoff or words[-1].startswith(signoff + "/"):
            return agency
    return None
