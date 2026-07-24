"""ArXiv data-source adapter (Stage 1-3A).

Implements the unified ``SourceAdapter`` contract (see ``adapters/base.py``)
for the **official ArXiv Atom API** (``http://export.arxiv.org/api/query``).

Responsibility boundary (per PROJECT_RULES section five / v2 section 2.2
step [1] / PIPELINE_DESIGN.md section 2):
    fetch() -> list[RawItem]
i.e. pull the source's raw entries and do the **source-specific**
parse into ``RawItem``. It does NOT normalize / validate / dedup /
cluster / score / cap / publish, and it never calls AI.

Design notes:
- Network uses the **standard library only** (``urllib`` +
  ``xml.etree.ElementTree``). No ``requests`` / ``httpx``.
- A ``urlopen`` callable is injectable so every behavior is unit-testable
  fully OFFLINE (no real network, no real API, no real data).
- Single-source failure isolation: an unrecoverable failure (HTTP exhaust,
  XML parse error) raises ``AdapterError`` which ``safe_fetch`` catches,
  never aborting the whole run. A *single malformed entry* is skipped
  without dropping the rest.
- Per-entry ``original_url`` is built from the ArXiv id, but the *source*
  id host is verified against ``config.allowed_domains`` via
  ``verify_original_url`` BEFORE trust -- this defeats suffix forgery
  such as ``arxiv.org.evil.com`` (PROJECT_RULES red line: every
  ``original_url`` must be real and domain-consistent).
"""

from __future__ import annotations

import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from xml.etree import ElementTree as ET

from ..models import SourceConfig
from ..raw import RawItem
from ..stages import verify_original_url
from .base import AdapterError

# ArXiv Atom namespace (the feed root carries xmlns=".../2005/Atom").
_ATOM_NS = "http://www.w3.org/2005/Atom"
_ARXIV_HOST = "arxiv.org"

# ArXiv's API etiquette REQUIRES a descriptive User-Agent (it throttles the
# generic ``Python-urllib`` default with HTTP 429). Identifies the client
# per https://info.arxiv.org/help/api/tou.html -- a real, traceable UA.
_USER_AGENT = (
    "daily-trend-radar-pipeline/0.2.0 "
    "(arxiv stage1-4A; +https://github.com/)"
)


# ---------------------------------------------------------------------------
# Small pure helpers
# ---------------------------------------------------------------------------


def parse_rate_limit(rate_limit: str) -> float:
    """Parse a ``"N/Ms"`` (or ``"N/M"``) limit into a min interval (seconds).

    ``"1/3s"`` -> 3.0s between requests; ``"2/1s"`` -> 0.5s.
    Unrecognized input falls back to ``0.0`` (no enforced delay).
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
# XML parsing (pure, no IO)
# ---------------------------------------------------------------------------


class _SkipEntry(Exception):
    """Internal: an entry is unusable and should be dropped (isolation)."""


def _parse_iso(el: Optional[ET.Element]) -> Optional[datetime]:
    """Parse an ArXiv ``<published>/<updated>`` element to a UTC datetime."""
    if el is None or not (el.text or "").strip():
        return None
    txt = el.text.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_entry(
    entry: ET.Element,
    config: SourceConfig,
    fetched_at: datetime,
    allowed: list[str],
) -> RawItem:
    """Turn one ``<entry>`` into a ``RawItem``. Raise ``_SkipEntry`` on bad data."""
    id_el = entry.find(f"{{{_ATOM_NS}}}id")
    if id_el is None or not (id_el.text or "").strip():
        raise _SkipEntry("missing <id>")
    raw_id = id_el.text.strip()

    # Suffix-forgery defense: the <id> is expected to be a real ArXiv URL.
    # Verify its host is in the source's allowed set BEFORE trusting it,
    # so "http://arxiv.org.evil.com/abs/999" is rejected here.
    if allowed and not verify_original_url(raw_id, allowed, require_https=False):
        raise _SkipEntry("<id> host not in allowed_domains")

    # ArXiv id = the last path segment of the <id> URL.
    arxiv_id = raw_id.rstrip("/").split("/")[-1]
    if not arxiv_id:
        raise _SkipEntry("empty arxiv id")

    # Always emit a clean, traceable https abstract URL.
    original_url = f"https://{_ARXIV_HOST}/abs/{arxiv_id}"

    title_el = entry.find(f"{{{_ATOM_NS}}}title")
    title = (title_el.text or "").strip() if title_el is not None else ""
    if not title:
        raise _SkipEntry("missing <title>")

    summary_el = entry.find(f"{{{_ATOM_NS}}}summary")
    summary = (summary_el.text or "").strip() if summary_el is not None else None

    published_at = _parse_iso(entry.find(f"{{{_ATOM_NS}}}published"))
    updated_at = _parse_iso(entry.find(f"{{{_ATOM_NS}}}updated"))

    authors: list[str] = []
    for a in entry.findall(f"{{{_ATOM_NS}}}author"):
        name = a.find(f"{{{_ATOM_NS}}}name")
        if name is not None and (name.text or "").strip():
            authors.append(name.text.strip())

    categories = [
        c.get("term")
        for c in entry.findall(f"{{{_ATOM_NS}}}category")
        if c.get("term")
    ]

    primary_el = entry.find(f"{{{_ATOM_NS}}}primary_category")
    primary = primary_el.get("term") if primary_el is not None else None

    metadata: dict[str, object] = {
        "arxiv_id": arxiv_id,
        "authors": authors,
        "categories": categories,
        "primary_category": primary,
        "updated_at": (
            updated_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            if updated_at is not None
            else None
        ),
    }

    return RawItem(
        source_id=config.id,
        source_name=config.name,
        original_url=original_url,
        title=title,
        published_at=published_at,
        source_item_id=arxiv_id,
        fetched_at=fetched_at,
        lang="en",
        summary=summary,
        metadata=metadata,
    )


def parse_arxiv_feed(
    xml_text: str,
    config: SourceConfig,
    fetched_at: datetime,
) -> list[RawItem]:
    """Pure parse of an ArXiv Atom response into ``RawItem[]`` (no IO).

    A malformed *entry* is skipped (single-item failure isolation) -- it
    never aborts the batch. A malformed *document* (XML parse error)
    raises ``AdapterError``, which ``safe_fetch`` isolates at the source
    level.
    """
    allowed = list(config.allowed_domains or [])
    try:
        root = ET.fromstring(xml_text.encode("utf-8"))
    except ET.ParseError as exc:
        raise AdapterError(f"ArXiv Atom XML parse failed: {exc}") from exc

    items: list[RawItem] = []
    for entry in root.findall(f"{{{_ATOM_NS}}}entry"):
        try:
            item = _parse_entry(entry, config, fetched_at, allowed)
        except _SkipEntry:
            # Single-entry isolation: drop this one, keep the rest.
            continue
        items.append(item)
    return items


# ---------------------------------------------------------------------------
# Adapter (network + orchestration)
# ---------------------------------------------------------------------------


@dataclass
class _Response:
    """Minimal stand-in for an ``http.client.HTTPResponse`` in tests."""

    body: bytes
    headers: dict = None  # type: ignore[assignment]

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body


def _default_urlopen(url: str, timeout: int) -> object:
    """Default opener using the standard library (injected for testability)."""
    import urllib.request

    return urllib.request.urlopen(url, timeout=timeout)


class ArxivAdapter:
    """``SourceAdapter`` for the official ArXiv Atom API.

    Constructed with its ``SourceConfig`` (id/name/category/timeout/
    retry_count/rate_limit/allowed_domains/...). ``fetch()`` returns
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

    # -- URL building -------------------------------------------------------

    def _build_url(self, start: int, page_size: int) -> str:
        params = {
            "search_query": self.config.query or "",
            "start": str(start),
            "max_results": str(page_size),
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
        endpoint = (self.config.endpoint or "").rstrip("/")
        return f"{endpoint}?{urlencode(params)}"

    # -- rate limiting ------------------------------------------------------

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

    # -- HTTP with retry / 429 handling -------------------------------------

    @staticmethod
    def _backoff(attempt: int) -> float:
        return min(2.0 ** attempt, 30.0)

    @staticmethod
    def _parse_retry_after(value: Optional[str]) -> float:
        if not value:
            return 1.0
        try:
            secs = float(value)
        except ValueError:
            return 1.0
        return min(secs, 60.0)

    def _get(self, url: str) -> bytes:
        attempts = 1 + max(0, self.config.retry_count)
        last_exc: Optional[Exception] = None
        for attempt in range(attempts):
            try:
                self._rate_limit_wait()
                req = urllib.request.Request(
                    url, headers={"User-Agent": _USER_AGENT}
                )
                with self._urlopen(req, self.config.timeout) as resp:
                    body = resp.read()
                    if isinstance(body, str):
                        return body.encode("utf-8")
                    return body
            except HTTPError as exc:
                last_exc = exc
                if attempt < attempts - 1:
                    if exc.code == 429:
                        # Honor BOTH the server's Retry-After AND the source's
                        # own rate-limit interval (ArXiv requires >=3s between
                        # requests). Re-hitting faster only sustains the 429.
                        hdrs = getattr(exc, "headers", None)
                        retry_after = hdrs.get("Retry-After") if hdrs is not None else None
                        wait = max(
                            self._parse_retry_after(retry_after),
                            parse_rate_limit(self.config.rate_limit),
                        )
                        self._sleep(min(wait, 60.0))
                    else:
                        self._sleep(self._backoff(attempt))
                    continue
                raise AdapterError(
                    f"ArXiv HTTP {exc.code} after {attempts} attempts"
                ) from exc
            except URLError as exc:
                last_exc = exc
                if attempt < attempts - 1:
                    self._sleep(self._backoff(attempt))
                    continue
                raise AdapterError(f"ArXiv request failed: {exc}") from exc
        raise AdapterError(f"ArXiv request failed: {last_exc}")  # pragma: no cover

    # -- public entry point ------------------------------------------------

    def fetch(self) -> list[RawItem]:
        if not self.config.enabled:
            return []
        max_items = max(1, self.config.max_items)
        page_size = min(max_items, 20)  # ArXiv-safe page ceiling
        collected: list[RawItem] = []
        start = 0
        pages = 0
        while len(collected) < max_items and pages < 20:
            remaining = max_items - len(collected)
            url = self._build_url(start, min(page_size, remaining))
            xml_bytes = self._get(url)
            xml_text = xml_bytes.decode("utf-8", errors="replace")
            page_items = parse_arxiv_feed(xml_text, self.config, self._now())
            if not page_items:
                break  # empty page => no more results
            collected.extend(page_items)
            start += len(page_items)
            pages += 1
        return collected[:max_items]
