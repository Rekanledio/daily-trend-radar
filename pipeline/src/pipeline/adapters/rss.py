"""Generic RSS / Atom feed adapter (Stage 1-3C).

Implements the unified ``SourceAdapter`` contract (see ``adapters/base.py``)
for **RSS 2.0** and **Atom** feeds. One generic class serves every RSS
source (AI official blogs, tech-media outlets, ...) -- the differences are
pure ``SourceConfig`` (endpoint / allowed_domains / category), per the
Stage 1-3C decision (Q14: a single ``RSSAdapter``, not separate
``OfficialRSSAdapter`` / ``TechRSSAdapter`` classes).

Responsibility boundary (PROJECT_RULES section five / v2 section 2.2
step [1] / PIPELINE_DESIGN.md section 2):
    fetch() -> list[RawItem]
i.e. pull the feed and do the **source-specific** parse into ``RawItem``.
It does NOT normalize / validate / dedup / cluster / score / cap /
publish, and it never calls AI.

Design notes:
- Network + XML parsing use the **standard library only**
  (``urllib`` + ``xml.etree.ElementTree`` + ``email.utils``).
  No ``feedparser`` / ``requests`` / ``httpx`` (Stage 1-3C constraint:
  no new deps; do NOT add feedparser to pyproject.toml).
- A ``urlopen`` callable is injectable so every behavior is unit-testable
  fully OFFLINE (no real network, no real data).
- Single-source failure isolation: an unrecoverable failure (HTTP
  exhaust, malformed top-level XML, unsupported root) raises
  ``AdapterError`` which ``safe_fetch`` catches, never aborting the
  whole run. A *single malformed entry* is skipped without dropping
  the rest (per Stage 1-3C spec section ten).
- Per-entry ``original_url`` is taken from the real feed ``<link>``
  (RSS) or ``<link href>`` (Atom) and verified against
  ``config.allowed_domains`` via ``verify_original_url`` BEFORE trust
  -- this defeats suffix forgery such as ``github.com.evil.com``
  (PROJECT_RULES red line: every ``original_url`` must be real and
  domain-consistent). The endpoint host is NOT part of ``allowed_domains``.
- No token, no auth: RSS/Atom sources are public. No secret is read,
  stored, logged, or printed.
- Namespaces are handled by **local-name** matching, so both plain
  RSS 2.0 and namespaced Atom (``http://www.w3.org/2005/Atom``) parse
  uniformly (no silent breakage when a feed adds a namespace prefix).
"""

from __future__ import annotations

import hashlib
import socket
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Callable, Optional
from urllib.error import HTTPError, URLError
from xml.etree.ElementTree import Element, ParseError

from ..models import SourceConfig
from ..raw import RawItem
from ..stages import canonicalize_url, verify_original_url
from .base import AdapterError

# A descriptive User-Agent per feed etiquette (avoids generic
# "Python-urllib" throttling and is traceable to this project).
_USER_AGENT = (
    "daily-trend-radar/0.2.0 "
    "(rss stage1-3C; +https://github.com/)"
)


# ---------------------------------------------------------------------------
# Small pure helpers (self-contained; per Stage 1-3C we intentionally do NOT
# import from github/arxiv to avoid cross-adapter coupling -- each adapter is
# a standalone, independently testable unit).
# ---------------------------------------------------------------------------


def parse_rate_limit(rate_limit: str) -> float:
    """Parse a ``"N/Ms"`` (or ``"N/M"``) limit into a min interval (seconds).

    ``"1/5s"`` -> 5.0s between requests. Unrecognized input falls back
    to ``0.0`` (no enforced delay).
    """
    if not rate_limit:
        return 0.0
    try:
        parts = rate_limit.lower().split("/")
        count = float(parts[0])
        window = parts[1]
        if window.endswith("s"):
            window = window[:-1]
        period = float(window)
        if count <= 0 or period <= 0:
            return 0.0
        return period / count
    except (ValueError, IndexError):
        return 0.0


# ---------------------------------------------------------------------------
# Date parsing (pure, no IO). RSS uses RFC822/RFC2822; Atom uses ISO 8601.
# ---------------------------------------------------------------------------


def _parse_iso(value: object) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp (``...Z``) to a UTC datetime."""
    if not isinstance(value, str) or not value.strip():
        return None
    txt = value.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_rfc822(value: object) -> Optional[datetime]:
    """Parse an RFC822/RFC2822 date (RSS ``pubDate``) to a UTC datetime."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        dt = parsedate_to_datetime(value.strip())
    except (TypeError, ValueError):
        return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_date(value: object) -> Optional[datetime]:
    """Parse a feed date, trying ISO 8601 first then RFC822.

    Returns a UTC-aware datetime, or ``None`` if unparseable.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    iso = _parse_iso(value.strip())
    if iso is not None:
        return iso
    return _parse_rfc822(value.strip())


# ---------------------------------------------------------------------------
# XML namespace-agnostic helpers (match on the LOCAL tag name so namespaced
# Atom and plain RSS 2.0 both work).
# ---------------------------------------------------------------------------


def _local(tag: str) -> str:
    """Return the local part of a (possibly namespaced) tag."""
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _find(elem: Element, name: str) -> Optional[Element]:
    """First direct child whose local tag name == ``name``."""
    for child in elem:
        if _local(child.tag) == name:
            return child
    return None


def _findall(elem: Element, name: str) -> list[Element]:
    """All direct children whose local tag name == ``name``."""
    return [c for c in elem if _local(c.tag) == name]


def _text_of(elem: Optional[Element]) -> Optional[str]:
    """Stripped text of an element, or ``None`` if empty."""
    if elem is None:
        return None
    if elem.text and elem.text.strip():
        return elem.text.strip()
    return None


# ---------------------------------------------------------------------------
# Per-entry field extraction (pure)
# ---------------------------------------------------------------------------


class _SkipItem(Exception):
    """Internal: an entry is unusable and should be dropped (isolation)."""


def _entry_link(entry: Element) -> Optional[str]:
    """Extract the canonical entry URL.

    RSS: ``<link>url</link>`` (text).
    Atom: ``<link href="..." rel="alternate"/>`` (prefer ``rel=alternate``,
    then any ``href``, then link text). Returns ``None`` if no usable URL.
    """
    links = _findall(entry, "link")
    if not links:
        return None
    href: Optional[str] = None
    alternate: Optional[str] = None
    for link in links:
        h = link.get("href")
        if h:
            if link.get("rel") == "alternate":
                alternate = h
            elif href is None:
                href = h
    chosen = alternate or href
    if chosen:
        return chosen.strip()
    for link in links:
        txt = _text_of(link)
        if txt:
            return txt
    return None


def _entry_author(entry: Element) -> Optional[str]:
    """Best-effort public author name (RSS ``<author>`` or Atom ``author``)."""
    author = _find(entry, "author")
    if author is None:
        return None
    name = _find(author, "name")
    if name is not None:
        t = _text_of(name)
        if t:
            return t
    email_el = _find(author, "email")
    if email_el is not None:
        t = _text_of(email_el)
        if t:
            return t
    return _text_of(author)


def _entry_categories(entry: Element) -> list[str]:
    """Public category terms (RSS ``<category>`` or Atom ``category@term``)."""
    cats: list[str] = []
    for c in _findall(entry, "category"):
        term = c.get("term")
        if term:
            cats.append(term)
        else:
            t = _text_of(c)
            if t:
                cats.append(t)
    return cats


def _build_source_item_id(raw_id: object, original_url: str) -> str:
    """Stable per-source id: prefer the feed's guid/id; else hash the URL.

    Never uses the current time, a random number, or an array index.
    """
    if raw_id is not None and str(raw_id).strip():
        return str(raw_id).strip()
    return hashlib.sha256(
        canonicalize_url(original_url).encode("utf-8")
    ).hexdigest()[:16]


def _parse_entry(
    entry: Element,
    config: SourceConfig,
    fetched_at: datetime,
    allowed: list[str],
    feed_type: str,
) -> RawItem:
    """Turn one feed entry into a ``RawItem``. Raise ``_SkipItem`` on bad data."""
    # title: required (a missing title is a malformed entry -> skip).
    title = _text_of(_find(entry, "title"))
    if not title:
        raise _SkipItem("missing title")

    # original_url: required, real, and domain-verified.
    link = _entry_link(entry)
    if not link:
        raise _SkipItem("missing link")
    if allowed and not verify_original_url(link, allowed, require_https=True):
        raise _SkipItem("link host not in allowed_domains")

    # source_item_id: stable guid/id, else sha256(url)[:16].
    id_tag = "guid" if feed_type == "rss" else "id"
    raw_id = _text_of(_find(entry, id_tag))
    source_item_id = _build_source_item_id(raw_id, link)

    # summary: raw source text only (never AI). May be absent.
    summary_tag = "description" if feed_type == "rss" else "summary"
    summary = _text_of(_find(entry, summary_tag))

    # published_at: source-provided time, normalized to UTC.
    if feed_type == "rss":
        date_el = _find(entry, "pubDate")
    else:
        # Atom: prefer <published>, fall back to <updated>.
        # NOTE: do NOT use ``or`` on Element results -- a leaf element
        # (text only, no children) is falsy under Element.__bool__,
        # so the truthiness test would wrongly skip it (and a standard
        # DeprecationWarning flags exactly this). Check ``is not None``.
        published_el = _find(entry, "published")
        updated_el = _find(entry, "updated")
        date_el = published_el if published_el is not None else updated_el
    published_at = _parse_date(_text_of(date_el) if date_el is not None else None)
    if published_at is None:
        raise _SkipItem("missing/invalid date")

    # Carry REAL public fields only. No token, no heat fabrication.
    metadata: dict[str, object] = {
        "feed_type": feed_type,
        "author": _entry_author(entry),
        "categories": _entry_categories(entry),
    }
    if feed_type == "atom":
        updated = _find(entry, "updated")
        if updated is not None:
            ut = _text_of(updated)
            if ut:
                metadata["updated_at"] = ut

    return RawItem(
        source_id=config.id,
        source_name=config.name,
        original_url=link,
        title=title,
        published_at=published_at,
        source_item_id=source_item_id,
        fetched_at=fetched_at,
        lang="en",
        summary=summary,
        metadata=metadata,
    )


def parse_rss_response(
    xml_text: str,
    config: SourceConfig,
    fetched_at: datetime,
) -> list[RawItem]:
    """Pure parse of an RSS 2.0 / Atom feed into ``RawItem[]`` (no IO).

    A malformed *entry* is skipped (single-item failure isolation) -- it
    never aborts the batch. A malformed *document* (not valid XML, an
    unsupported root, or an RSS feed missing ``<channel>``) raises
    ``AdapterError``, which ``safe_fetch`` isolates at the source level.
    An empty-but-valid feed yields ``[]`` (degraded, not an error).
    """
    allowed = list(config.allowed_domains or [])
    try:
        root = ET.fromstring(xml_text)
    except ParseError as exc:
        raise AdapterError(f"RSS/Atom feed is not valid XML: {exc}") from exc
    if not isinstance(root, Element):
        raise AdapterError("RSS/Atom root is not an XML element")

    local = _local(root.tag)
    if local == "rss":
        feed_type = "rss"
        channel = _find(root, "channel")
        if channel is None:
            raise AdapterError("RSS feed is missing <channel>")
        entries = _findall(channel, "item")
    elif local == "feed":
        feed_type = "atom"
        entries = _findall(root, "entry")
    else:
        raise AdapterError(
            f"Unsupported feed root '<{local}>' (expected rss/feed)"
        )

    out: list[RawItem] = []
    for entry in entries:
        try:
            raw = _parse_entry(entry, config, fetched_at, allowed, feed_type)
        except _SkipItem:
            # Single-entry isolation: drop this one, keep the rest.
            continue
        out.append(raw)
    return out


# ---------------------------------------------------------------------------
# Adapter (network + orchestration)
# ---------------------------------------------------------------------------


def _default_urlopen(url: str, timeout: int) -> object:
    """Default opener using the standard library (injected for testability)."""
    return urllib.request.urlopen(url, timeout=timeout)


class RSSAdapter:
    """``SourceAdapter`` for RSS 2.0 / Atom feeds.

    Constructed with its ``SourceConfig`` (id/name/category/type/enabled/
    timeout/retry_count/rate_limit/allowed_domains/...). ``fetch()`` returns
    ``list[RawItem]``.
    """

    def __init__(
        self,
        config: SourceConfig,
        urlopen: Callable[[str, int], object] = _default_urlopen,
        now_provider: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config = config
        self.source_id = config.id
        self.category = config.category
        self._urlopen = urlopen
        self._now = now_provider
        self._sleep = sleep
        self._last_request_at: Optional[float] = None

    # -- headers (public RSS, no token) ----------------------------------

    def _headers(self) -> dict:
        return {
            "Accept": (
                "application/rss+xml, application/atom+xml, "
                "application/xml, text/xml"
            ),
            "User-Agent": _USER_AGENT,
        }

    # -- rate limiting -----------------------------------------------------

    def _rate_limit_wait(self) -> None:
        interval = parse_rate_limit(self.config.rate_limit)
        if interval <= 0:
            return
        now = time.monotonic()
        if self._last_request_at is not None:
            waited = now - self._last_request_at
            if waited < interval:
                self._sleep(interval - waited)
        self._last_request_at = time.monotonic()

    # -- retry / backoff helpers ------------------------------------------

    @staticmethod
    def _backoff(attempt: int) -> float:
        return min(2.0 ** attempt, 30.0)

    @staticmethod
    def _parse_retry_after(value: object) -> float:
        if not value:
            return 1.0
        try:
            secs = float(str(value))
        except (ValueError, TypeError):
            return 1.0
        return min(secs, 60.0)

    @staticmethod
    def _is_rate_limited(hdrs: object) -> bool:
        """True only when response headers indicate a *rate-limit* condition."""
        if hdrs is None:
            return False
        remaining = getattr(hdrs, "get", lambda *_: None)("X-RateLimit-Remaining")
        reset = getattr(hdrs, "get", lambda *_: None)("X-RateLimit-Reset")
        if remaining is not None and str(remaining).strip() == "0":
            return True
        if reset is not None:
            return True
        return False

    def _rate_limit_wait_for(self, hdrs: object) -> float:
        """Wait time for a rate-limited response, preferring the reset ts."""
        if hdrs is None:
            reset = None
        else:
            reset = hdrs.get("X-RateLimit-Reset")  # type: ignore[union-attr]
        if reset is not None:
            try:
                reset_ts = float(str(reset))
                now_ts = datetime.now(timezone.utc).timestamp()
                wait = max(0.0, reset_ts - now_ts)
                if wait > 0:
                    return min(wait, 60.0)
            except (ValueError, TypeError):
                pass
        retry_after = (
            None if hdrs is None else hdrs.get("Retry-After")  # type: ignore[union-attr]
        )
        return max(
            self._parse_retry_after(retry_after),
            parse_rate_limit(self.config.rate_limit),
        )

    # -- HTTP with retry / 403 / 429 handling ----------------------------

    def _get(self, url: str) -> bytes:
        attempts = 1 + max(0, self.config.retry_count)
        last_exc: Optional[Exception] = None
        for attempt in range(attempts):
            try:
                self._rate_limit_wait()
                req = urllib.request.Request(url, headers=self._headers())
                with self._urlopen(req, self.config.timeout) as resp:
                    body = resp.read()
                    if isinstance(body, str):
                        return body.encode("utf-8")
                    return body
            except HTTPError as exc:
                last_exc = exc
                code = exc.code
                hdrs = getattr(exc, "headers", None)
                if code == 401:
                    # Auth failure (should not happen for public RSS) -- no retry.
                    raise AdapterError(
                        f"RSS HTTP 401 Unauthorized: {exc}"
                    ) from exc
                if code == 403:
                    if self._is_rate_limited(hdrs):
                        if attempt < attempts - 1:
                            self._sleep(min(self._rate_limit_wait_for(hdrs), 60.0))
                            continue
                        raise AdapterError(
                            f"RSS rate-limited (403) after {attempts} attempts"
                        ) from exc
                    # Auth/permission 403 (NOT rate-limit) -> do NOT mask it.
                    raise AdapterError(
                        f"RSS HTTP 403 Forbidden (auth/permission, not rate-limit): {exc}"
                    ) from exc
                if code == 429:
                    if attempt < attempts - 1:
                        retry_after = (
                            hdrs.get("Retry-After") if hdrs is not None else None
                        )
                        wait = max(
                            self._parse_retry_after(retry_after),
                            parse_rate_limit(self.config.rate_limit),
                        )
                        self._sleep(min(wait, 60.0))
                        continue
                    raise AdapterError(
                        f"RSS HTTP 429 after {attempts} attempts"
                    ) from exc
                # Other HTTP errors: retry with exponential backoff.
                if attempt < attempts - 1:
                    self._sleep(self._backoff(attempt))
                    continue
                raise AdapterError(f"RSS HTTP {code}: {exc}") from exc
            except (URLError, socket.timeout, TimeoutError) as exc:
                last_exc = exc
                if attempt < attempts - 1:
                    self._sleep(self._backoff(attempt))
                    continue
                raise AdapterError(f"RSS request failed: {exc}") from exc
        raise AdapterError(f"RSS request failed: {last_exc}")  # pragma: no cover

    # -- public entry point ------------------------------------------------

    def fetch(self) -> list[RawItem]:
        if not self.config.enabled:
            return []
        max_items = self.config.max_items
        if max_items is None or max_items <= 0:
            return []
        endpoint = self.config.endpoint
        if not endpoint or not endpoint.strip():
            raise AdapterError("RSS source has no endpoint configured")
        body = self._get(endpoint)
        text = body.decode("utf-8", errors="replace")
        items = parse_rss_response(text, self.config, self._now())
        return items[:max_items]
