from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


class UrlError(ValueError):
    pass


_DROP = re.compile(r"^(utm_.*|b_source|b_medium|b_campaign)$", re.IGNORECASE)
_FT_SYN = re.compile(r"^syn-[A-Za-z0-9]+$")


def normalize_url(source: str, raw_url: str) -> str:
    try:
        parts = urlsplit(raw_url)
    except ValueError as exc:
        raise UrlError("invalid URL") from exc
    if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
        raise UrlError("URL must be absolute HTTP(S)")
    host = parts.hostname.lower()
    if parts.port and not (
        (parts.scheme.lower() == "http" and parts.port == 80)
        or (parts.scheme.lower() == "https" and parts.port == 443)
    ):
        host += f":{parts.port}"
    pairs = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not _DROP.match(k)
        and not (source == "ft" and _FT_SYN.match(k))
        and not (source == "berlingske" and k.lower() == "referrer" and v.lower() == "rss")
    ]
    return urlunsplit((parts.scheme.lower(), host, parts.path or "/", urlencode(sorted(pairs)), ""))
