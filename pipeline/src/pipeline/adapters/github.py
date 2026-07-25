"""GitHub data-source adapter (Stage 1-3B).

Implements the unified ``SourceAdapter`` contract (see ``adapters/base.py``)
for the **official GitHub Search Repositories API**
(``https://api.github.com/search/repositories``).

Responsibility boundary (per PROJECT_RULES section five / v2 section 2.2
step [1] / PIPELINE_DESIGN.md section 2):
    fetch() -> list[RawItem]
i.e. pull the source's raw entries and do the **source-specific**
parse into ``RawItem``. It does NOT normalize / validate / dedup /
cluster / score / cap / publish, and it never calls AI.

Design notes:
- Network uses the **standard library only** (``urllib`` + ``json``).
  No ``requests`` / ``httpx`` (Stage 1-3B constraint: no new deps).
- A ``urlopen`` callable is injectable so every behavior is unit-testable
  fully OFFLINE (no real network, no real API, no real data).
- Single-source failure isolation: an unrecoverable failure (HTTP exhaust,
  malformed top-level JSON) raises ``AdapterError`` which ``safe_fetch``
  catches, never aborting the whole run. A *single malformed repo entry*
  is skipped without dropping the rest (per Stage 1-3B spec section 11).
- Per-entry ``original_url`` is taken from ``html_url`` and verified
  against ``config.allowed_domains`` via ``verify_original_url`` BEFORE
  trust -- this defeats suffix forgery such as ``github.com.evil.com``
  (PROJECT_RULES red line: every ``original_url`` must be real and
  domain-consistent). ``api.github.com`` is the *endpoint* host only and
  is intentionally NOT part of ``allowed_domains``.
- Token is OPTIONAL and read from the ``GITHUB_TOKEN`` environment
  variable at request time. It is NEVER written to config / code / schema
  / fixtures / logs / metadata, and is NEVER printed. A missing token
  runs unauthenticated; an invalid token (401 / auth 403) raises
  ``AdapterError`` and is isolated -- never masked as success.
"""

from __future__ import annotations

import json
import os
import socket
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode

from ..models import SourceConfig
from ..raw import RawItem
from ..stages import verify_original_url
from .base import AdapterError

# A descriptive User-Agent per GitHub API etiquette (avoids generic
# "Python-urllib" throttling and is traceable to this project).
_USER_AGENT = (
    "daily-trend-radar/0.2.0 "
    "(github stage1-3B; +https://github.com/)"
)

# GitHub Search API hard caps.
_MAX_PER_PAGE = 100
_MAX_PAGES = 20


# ---------------------------------------------------------------------------
# Small pure helpers (self-contained; mirroring arxiv.py approach per
# Stage 1-3B section 17 -- intentionally NOT imported from arxiv to avoid
# cross-adapter coupling and to keep this file a standalone unit).
# ---------------------------------------------------------------------------


def parse_rate_limit(rate_limit: str) -> float:
    """Parse a ``"N/Ms"`` (or ``"N/M"``) limit into a min interval (seconds).

    ``"1/6s"`` -> 6.0s between requests. Unrecognized input falls back
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
# JSON parsing (pure, no IO)
# ---------------------------------------------------------------------------


class _SkipItem(Exception):
    """Internal: a repo entry is unusable and should be dropped (isolation)."""


def _parse_iso(value: object) -> Optional[datetime]:
    """Parse a GitHub ISO-8601 timestamp (``...Z``) to a UTC datetime."""
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


def _parse_repo(
    item: object,
    config: SourceConfig,
    fetched_at: datetime,
    allowed: list[str],
) -> RawItem:
    """Turn one GitHub repo object into a ``RawItem``. Raise ``_SkipItem`` on bad data."""
    if not isinstance(item, dict):
        raise _SkipItem("item is not an object")

    # source_item_id: stable global repo id (str). Skip if missing.
    raw_id = item.get("id")
    if raw_id is None:
        raise _SkipItem("missing id")
    source_item_id = str(raw_id)

    # original_url: MUST come from html_url (a real, traceable page).
    html_url = item.get("html_url")
    if not isinstance(html_url, str) or not html_url.strip():
        raise _SkipItem("missing html_url")
    if allowed and not verify_original_url(html_url, allowed, require_https=False):
        raise _SkipItem("html_url host not in allowed_domains")

    # title: full_name (owner/repo). Skip if missing.
    full_name = item.get("full_name")
    if not isinstance(full_name, str) or not full_name.strip():
        raise _SkipItem("missing full_name")

    # summary: raw description only (never AI). May be absent.
    description = item.get("description")
    summary = (
        description if isinstance(description, str) and description.strip() else None
    )

    # published_at: prefer pushed_at (the active/hot-signal time for a
    # "trending" radar), fall back to created_at. Skip only when BOTH
    # are missing/unparseable -- never fabricate a time.
    pushed_at = _parse_iso(item.get("pushed_at"))
    created_at = _parse_iso(item.get("created_at"))
    published_at = pushed_at or created_at
    if published_at is None:
        raise _SkipItem("missing/invalid pushed_at and created_at")

    owner = item.get("owner")
    owner_login = (
        owner.get("login") if isinstance(owner, dict) else None
    )

    # Carry the REAL GitHub fields as-is. No Token, no heat_raw fabrication.
    metadata: dict[str, object] = {
        "api_url": item.get("url"),
        "name": item.get("name"),
        "owner": owner_login,
        "stars": item.get("stargazers_count"),
        "forks": item.get("forks_count"),
        "watchers": item.get("watchers_count"),
        "open_issues": item.get("open_issues_count"),
        "language": item.get("language"),
        "pushed_at": item.get("pushed_at"),
        "created_at": item.get("created_at"),
        "updated_at": item.get("updated_at"),
    }

    return RawItem(
        source_id=config.id,
        source_name=config.name,
        original_url=html_url,
        title=full_name,
        source_item_id=source_item_id,
        fetched_at=fetched_at,
        lang="en",
        summary=summary,
        metadata=metadata,
        published_at=published_at,
    )


def parse_github_response(
    json_text: str,
    config: SourceConfig,
    fetched_at: datetime,
) -> list[RawItem]:
    """Pure parse of a GitHub Search response into ``RawItem[]`` (no IO).

    A malformed *entry* is skipped (single-item failure isolation) -- it
    never aborts the batch. A malformed *document* (not valid JSON, top
    level not an object, or ``items`` missing / not a list) raises
    ``AdapterError``, which ``safe_fetch`` isolates at the source level.
    """
    allowed = list(config.allowed_domains or [])
    try:
        data = json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise AdapterError(f"GitHub response is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise AdapterError("GitHub response top-level is not an object")
    items = data.get("items")
    if not isinstance(items, list):
        raise AdapterError("GitHub response 'items' is missing or not a list")

    out: list[RawItem] = []
    for item in items:
        try:
            raw = _parse_repo(item, config, fetched_at, allowed)
        except _SkipItem:
            # Single-entry isolation: drop this one, keep the rest.
            continue
        out.append(raw)
    return out


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
    return urllib.request.urlopen(url, timeout=timeout)


class GitHubAdapter:
    """``SourceAdapter`` for the official GitHub Search Repositories API.

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

    # -- URL building ------------------------------------------------------

    def _build_url(self, page: int, page_size: int) -> str:
        params = {
            "q": self.config.query or "",
            "sort": "stars",
            "order": "desc",
            "per_page": str(page_size),
            "page": str(page),
        }
        endpoint = (self.config.endpoint or "").rstrip("/")
        return f"{endpoint}?{urlencode(params)}"

    # -- headers (token optional, never stored/logged) ----------------------

    def _headers(self) -> dict:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": _USER_AGENT,
            "X-GitHub-Api-Version": "2022-11-28",
        }
        # Read the token fresh per request (rotation-safe). Never cached,
        # never written anywhere, never printed.
        token = os.environ.get("GITHUB_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

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
        """True only when GitHub headers indicate a *rate-limit* condition."""
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
        """Wait time for a rate-limited response, preferring GitHub's reset ts."""
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
                    # Auth failure (bad/missing token) -- never recovers by retry.
                    raise AdapterError(
                        f"GitHub HTTP 401 Unauthorized (token invalid/missing): {exc}"
                    ) from exc
                if code == 403:
                    if self._is_rate_limited(hdrs):
                        if attempt < attempts - 1:
                            self._sleep(min(self._rate_limit_wait_for(hdrs), 60.0))
                            continue
                        raise AdapterError(
                            f"GitHub rate-limited (403) after {attempts} attempts"
                        ) from exc
                    # Auth/permission 403 (NOT rate-limit) -> do NOT mask it.
                    raise AdapterError(
                        f"GitHub HTTP 403 Forbidden (auth/permission, not rate-limit): {exc}"
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
                        f"GitHub HTTP 429 after {attempts} attempts"
                    ) from exc
                # Other HTTP errors: retry with exponential backoff.
                if attempt < attempts - 1:
                    self._sleep(self._backoff(attempt))
                    continue
                raise AdapterError(f"GitHub HTTP {code}: {exc}") from exc
            except (URLError, socket.timeout, TimeoutError) as exc:
                last_exc = exc
                if attempt < attempts - 1:
                    self._sleep(self._backoff(attempt))
                    continue
                raise AdapterError(f"GitHub request failed: {exc}") from exc
        raise AdapterError(f"GitHub request failed: {last_exc}")  # pragma: no cover

    # -- public entry point ------------------------------------------------

    def fetch(self) -> list[RawItem]:
        if not self.config.enabled:
            return []
        max_items = self.config.max_items
        if max_items is None or max_items <= 0:
            return []
        page_size = min(max_items, _MAX_PER_PAGE)
        collected: list[RawItem] = []
        page = 1
        pages = 0
        while len(collected) < max_items and pages < _MAX_PAGES:
            remaining = max_items - len(collected)
            url = self._build_url(page, min(page_size, remaining))
            body = self._get(url)
            text = body.decode("utf-8", errors="replace")
            page_items = parse_github_response(text, self.config, self._now())
            if not page_items:
                break  # empty page => no more results
            collected.extend(page_items)
            page += 1
            pages += 1
        return collected[:max_items]
