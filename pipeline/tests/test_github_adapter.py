"""Offline tests for the GitHub adapter (Stage1-3B).

NO real network, NO real API, NO real data. Every test runs fully offline:
- Fixture/parse tests exercise the pure ``parse_github_response`` /
  ``parse_rate_limit`` / ``_parse_retry_after`` / ``_build_url`` helpers.
- Behavior tests exercise ``GitHubAdapter.fetch`` with an injected ``urlopen``
  stub (no sockets touched). The stub receives a ``urllib.request.Request``
  exactly like the real ``_default_urlopen`` would.

The one real-network smoke check (allowed by the user, never written to
data/ and never committed) is performed manually outside this suite.
"""

from __future__ import annotations

import email
import json
import socket
import types
from datetime import datetime, timezone
from email.message import Message
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse

import pytest

from pipeline.adapters.github import (
    AdapterError,
    GitHubAdapter,
    _Response,
    parse_github_response,
    parse_rate_limit,
)
from pipeline.adapters.registry import _ADAPTER_REGISTRY, build_registry
from pipeline.models import LegalStatus, SourceConfig, SourceType, TrendStatus, ScoreBreakdown
from pipeline.stages import verify_original_url, build_trend

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

_FIXED_NOW = datetime(2026, 7, 24, 9, 0, 0, tzinfo=timezone.utc)


def _mini_cfg(max_items: int, enabled: bool = True):
    """Minimal stand-in for SourceConfig for the defensive ``max_items<=0``
    branch. SourceConfig itself enforces ``ge=1, le=20`` (models.py),
    so a <=0 value cannot be constructed via the real model -- but the
    adapter's guard still exists and must be covered. ``fetch()`` only
    reads ``.enabled`` and ``.max_items`` here, which a SimpleNamespace
    satisfies without touching the production model."""

    return types.SimpleNamespace(
        id="github", category="opensource", enabled=enabled, max_items=max_items
    )


def _github_config(**over) -> SourceConfig:
    base = dict(
        id="github",
        name="GitHub",
        category="opensource",
        type=SourceType.API,
        enabled=True,
        priority=2,
        max_items=20,
        timeout=15,
        retry_count=2,
        rate_limit="1/6s",
        legal_status=LegalStatus.OFFICIAL_API,
        terms_url=(
            "https://docs.github.com/en/site-policy/"
            "github-acceptable-use-policies"
        ),
        endpoint="https://api.github.com/search/repositories",
        query="stars:>1000 pushed:>2026-06-24",
        allowed_domains=["github.com"],
    )
    base.update(over)
    return SourceConfig(**base)


def _repo(
    rid=123456,
    full_name="octo/cat",
    html_url=None,
    created_at="2026-01-01T00:00:00Z",
    **extra,
):
    owner = full_name.split("/")[0]
    name = full_name.split("/")[-1]
    item = {
        "id": rid,
        "full_name": full_name,
        "html_url": html_url or f"https://github.com/{full_name}",
        "description": "A cool repo",
        "created_at": created_at,
        "url": f"https://api.github.com/repos/{full_name}",
        "name": name,
        "owner": {"login": owner},
        "stargazers_count": 100,
        "forks_count": 10,
        "watchers_count": 5,
        "open_issues_count": 3,
        "language": "Python",
        "pushed_at": "2026-06-01T00:00:00Z",
        "updated_at": "2026-06-02T00:00:00Z",
    }
    item.update(extra)
    return item


def _resp(*repos) -> str:
    return json.dumps(
        {
            "total_count": len(repos),
            "incomplete_results": False,
            "items": list(repos),
        }
    )


class _Stub:
    """Injectable ``urlopen``. ``errors[i]`` is raised on the i-th call;
    afterwards ``payloads`` are returned in order (last one repeats)."""

    def __init__(self, payloads=(), errors=()):
        self.payloads = list(payloads)
        self.errors = list(errors)
        self.calls = []  # list of (url, headers-dict)
        self._i = 0

    def __call__(self, req, timeout):
        url = getattr(req, "full_url", str(req))
        headers = dict(getattr(req, "headers", {}) or {})
        self.calls.append((url, headers))
        i = self._i
        self._i += 1
        if i < len(self.errors):
            raise self.errors[i]
        pi = i - len(self.errors)
        if self.payloads:
            body = self.payloads[min(pi, len(self.payloads) - 1)]
        else:
            body = b"{}"
        return _Response(body)


def _http_error(code: int, headers: Message | None = None) -> HTTPError:
    return HTTPError(
        "https://api.github.com/search/repositories",
        code,
        "err",
        headers,
        None,
    )


def _hdr(text: str) -> Message:
    return email.message_from_string(text)


# ---------------------------------------------------------------------------
# 1. Happy-path JSON parse (per-field mapping)
# ---------------------------------------------------------------------------


def test_parse_happy_path_fields():
    cfg = _github_config()
    items = parse_github_response(_resp(_repo()), cfg, _FIXED_NOW)
    assert len(items) == 1
    it = items[0]
    assert it.source_id == "github"
    assert it.source_name == "GitHub"
    assert it.source_item_id == "123456"
    assert it.title == "octo/cat"
    assert it.summary == "A cool repo"
    assert it.original_url == "https://github.com/octo/cat"
    # published_at now prefers pushed_at (2026-06-01) over created_at (2026-01-01).
    assert it.published_at == datetime(2026, 6, 1, 0, 0, 0, tzinfo=timezone.utc)
    assert it.fetched_at == _FIXED_NOW
    assert it.lang == "en"


def test_parse_metadata_fields():
    cfg = _github_config()
    items = parse_github_response(_resp(_repo()), cfg, _FIXED_NOW)
    md = items[0].metadata
    assert md["api_url"] == "https://api.github.com/repos/octo/cat"
    assert md["name"] == "cat"
    assert md["owner"] == "octo"
    assert md["stars"] == 100
    assert md["forks"] == 10
    assert md["watchers"] == 5
    assert md["open_issues"] == 3
    assert md["language"] == "Python"
    assert md["pushed_at"] == "2026-06-01T00:00:00Z"
    assert md["updated_at"] == "2026-06-02T00:00:00Z"
    # Token must NEVER leak into metadata.
    assert "token" not in md
    assert "Authorization" not in md


def test_parse_summary_absent_is_none():
    cfg = _github_config()
    items = parse_github_response(
        _resp(_repo(description=None)), cfg, _FIXED_NOW
    )
    assert items[0].summary is None


# ---------------------------------------------------------------------------
# 2. Empty response
# ---------------------------------------------------------------------------


def test_parse_empty_items_returns_empty():
    cfg = _github_config()
    items = parse_github_response(_resp(), cfg, _FIXED_NOW)
    assert items == []


def test_fetch_empty_page_no_error():
    stub = _Stub(payloads=(_resp().encode(),))
    a = GitHubAdapter(
        _github_config(), urlopen=stub, now_provider=lambda: _FIXED_NOW, sleep=lambda s: None
    )
    assert a.fetch() == []


# ---------------------------------------------------------------------------
# 3. max_items
# ---------------------------------------------------------------------------


def test_fetch_max_items_one():
    stub = _Stub(payloads=(_resp(*[_repo(rid=i) for i in range(5)]).encode(),))
    a = GitHubAdapter(
        _github_config(max_items=1),
        urlopen=stub,
        now_provider=lambda: _FIXED_NOW,
        sleep=lambda s: None,
    )
    items = a.fetch()
    assert len(items) == 1
    # First page already satisfies max_items -> no second request.
    assert len(stub.calls) == 1


def test_fetch_max_items_twenty():
    page = _resp(*[_repo(rid=i) for i in range(20)]).encode()
    stub = _Stub(payloads=(page, _resp().encode()))
    a = GitHubAdapter(
        _github_config(max_items=20),
        urlopen=stub,
        now_provider=lambda: _FIXED_NOW,
        sleep=lambda s: None,
    )
    items = a.fetch()
    assert len(items) == 20


def test_fetch_max_items_zero_returns_empty():
    # SourceConfig forbids max_items<=0 (ge=1), so we exercise the
    # adapter's defensive guard via a minimal stand-in config.
    a = GitHubAdapter(
        _mini_cfg(max_items=0),
        urlopen=lambda req, timeout: None,
        now_provider=lambda: _FIXED_NOW,
        sleep=lambda s: None,
    )
    assert a.fetch() == []


def test_fetch_max_items_negative_returns_empty():
    a = GitHubAdapter(
        _mini_cfg(max_items=-3),
        urlopen=lambda req, timeout: None,
        now_provider=lambda: _FIXED_NOW,
        sleep=lambda s: None,
    )
    assert a.fetch() == []


def test_fetch_max_items_less_than_results():
    page = _resp(*[_repo(rid=i) for i in range(5)]).encode()
    stub = _Stub(payloads=(page, _resp().encode()))
    a = GitHubAdapter(
        _github_config(max_items=20),
        urlopen=stub,
        now_provider=lambda: _FIXED_NOW,
        sleep=lambda s: None,
    )
    items = a.fetch()
    assert len(items) == 5  # page had only 5


def test_fetch_max_items_exceeds_results_paginated():
    # SourceConfig caps max_items at 20; prove cross-page accumulation
    # is sliced back to the cap (max_items=2).
    p1 = _resp(_repo(rid=1)).encode()
    p2 = _resp(*[_repo(rid=i) for i in range(2, 7)]).encode()
    stub = _Stub(payloads=(p1, p2, _resp().encode()))
    a = GitHubAdapter(
        _github_config(max_items=2),
        urlopen=stub,
        now_provider=lambda: _FIXED_NOW,
        sleep=lambda s: None,
    )
    items = a.fetch()
    assert len(items) == 2  # page1=1 then page2=5 -> sliced to 2
    assert len(stub.calls) == 2


# ---------------------------------------------------------------------------
# 4. Pagination
# ---------------------------------------------------------------------------


def test_pagination_stops_at_cap_20():
    # SourceConfig caps max_items at 20; prove pagination stops at the
    # cap with no extra page requested.
    p1 = _resp(*[_repo(rid=i) for i in range(15)]).encode()
    p2 = _resp(*[_repo(rid=1000 + i) for i in range(15)]).encode()
    stub = _Stub(payloads=(p1, p2, _resp().encode()))
    a = GitHubAdapter(
        _github_config(max_items=20),
        urlopen=stub,
        now_provider=lambda: _FIXED_NOW,
        sleep=lambda s: None,
    )
    items = a.fetch()
    assert len(items) == 20
    assert len(stub.calls) == 2  # page1 + page2, no page3


def test_pagination_empty_page_stops():
    p1 = _resp(*[_repo(rid=i) for i in range(5)]).encode()
    stub = _Stub(payloads=(p1, _resp().encode()))
    a = GitHubAdapter(
        _github_config(max_items=20),
        urlopen=stub,
        now_provider=lambda: _FIXED_NOW,
        sleep=lambda s: None,
    )
    items = a.fetch()
    assert len(items) == 5
    assert len(stub.calls) == 2  # fetched page2 (empty) then stopped


def test_pagination_no_extra_when_satisfied():
    p1 = _resp(*[_repo(rid=i) for i in range(10)]).encode()
    stub = _Stub(payloads=(p1, _resp().encode()))
    a = GitHubAdapter(
        _github_config(max_items=5),
        urlopen=stub,
        now_provider=lambda: _FIXED_NOW,
        sleep=lambda s: None,
    )
    items = a.fetch()
    assert len(items) == 5
    assert len(stub.calls) == 1  # first page already >= max_items


# ---------------------------------------------------------------------------
# 5/6. Malformed JSON / top-level structure
# ---------------------------------------------------------------------------


def test_parse_malformed_json_raises():
    cfg = _github_config()
    with pytest.raises(AdapterError):
        parse_github_response("not json at all {{{", cfg, _FIXED_NOW)


def test_parse_top_level_not_object_raises():
    cfg = _github_config()
    with pytest.raises(AdapterError):
        parse_github_response("[1,2,3]", cfg, _FIXED_NOW)


def test_parse_items_missing_raises():
    cfg = _github_config()
    with pytest.raises(AdapterError):
        parse_github_response('{"total_count": 1}', cfg, _FIXED_NOW)


def test_parse_items_not_list_raises():
    cfg = _github_config()
    with pytest.raises(AdapterError):
        parse_github_response('{"items": {"a": 1}}', cfg, _FIXED_NOW)


def test_fetch_malformed_json_raises():
    stub = _Stub(payloads=(b"totally not json",))
    a = GitHubAdapter(
        _github_config(), urlopen=stub, now_provider=lambda: _FIXED_NOW, sleep=lambda s: None
    )
    with pytest.raises(AdapterError):
        a.fetch()


# ---------------------------------------------------------------------------
# 7. Single bad entry isolation
# ---------------------------------------------------------------------------


def test_parse_single_bad_entry_isolated():
    good1 = _repo(rid=1)
    bad = {"id": 2, "full_name": "x/y"}  # no html_url / created_at
    good2 = _repo(rid=3)
    cfg = _github_config()
    items = parse_github_response(_resp(good1, bad, good2), cfg, _FIXED_NOW)
    assert [it.source_item_id for it in items] == ["1", "3"]


def test_fetch_single_bad_entry_isolated():
    bad = {"id": 2, "full_name": "x/y"}
    stub = _Stub(
        payloads=(_resp(_repo(rid=1), bad, _repo(rid=3)).encode(), _resp().encode())
    )
    a = GitHubAdapter(
        _github_config(), urlopen=stub, now_provider=lambda: _FIXED_NOW, sleep=lambda s: None
    )
    items = a.fetch()
    assert [it.source_item_id for it in items] == ["1", "3"]


# ---------------------------------------------------------------------------
# 8. HTTP 403 (auth vs rate-limit)
# ---------------------------------------------------------------------------


def test_fetch_403_auth_not_retried():
    hdr = _hdr("Content-Type: text/plain\n")  # no rate-limit headers
    stub = _Stub(errors=(_http_error(403, hdr),))
    a = GitHubAdapter(
        _github_config(retry_count=2),
        urlopen=stub,
        now_provider=lambda: _FIXED_NOW,
        sleep=lambda s: None,
    )
    with pytest.raises(AdapterError):
        a.fetch()
    assert len(stub.calls) == 1  # never retries an auth 403


def test_fetch_401_not_retried():
    stub = _Stub(errors=(_http_error(401),))
    a = GitHubAdapter(
        _github_config(retry_count=2),
        urlopen=stub,
        now_provider=lambda: _FIXED_NOW,
        sleep=lambda s: None,
    )
    with pytest.raises(AdapterError):
        a.fetch()
    assert len(stub.calls) == 1


def test_fetch_403_rate_limited_exhausted():
    future = int(datetime.now(timezone.utc).timestamp()) + 999
    hdr = _hdr(f"X-RateLimit-Remaining: 0\nX-RateLimit-Reset: {future}\n")
    stub = _Stub(errors=(_http_error(403, hdr), _http_error(403, hdr)))
    a = GitHubAdapter(
        _github_config(retry_count=1),  # attempts = 2
        urlopen=stub,
        now_provider=lambda: _FIXED_NOW,
        sleep=lambda s: None,
    )
    with pytest.raises(AdapterError):
        a.fetch()
    assert len(stub.calls) == 2


def test_rate_limit_wait_for_uses_reset():
    cfg = _github_config()
    a = GitHubAdapter(cfg, sleep=lambda s: None)
    future = int(datetime.now(timezone.utc).timestamp()) + 10
    msg = _hdr(f"X-RateLimit-Reset: {future}\n")
    wait = a._rate_limit_wait_for(msg)
    assert 9.0 <= wait <= 11.0


def test_is_rate_limited_flag():
    cfg = _github_config()
    a = GitHubAdapter(cfg, sleep=lambda s: None)
    assert a._is_rate_limited(_hdr("X-RateLimit-Remaining: 0\n")) is True
    future = int(datetime.now(timezone.utc).timestamp()) + 100
    assert a._is_rate_limited(_hdr(f"X-RateLimit-Reset: {future}\n")) is True
    assert a._is_rate_limited(_hdr("Content-Type: text/plain\n")) is False
    assert a._is_rate_limited(None) is False


# ---------------------------------------------------------------------------
# 9/10. HTTP 429 + Retry-After
# ---------------------------------------------------------------------------


def test_fetch_429_retry_after_then_success():
    hdr = _hdr("Retry-After: 0\n")
    stub = _Stub(payloads=(_resp(_repo()).encode(),), errors=(_http_error(429, hdr),))
    a = GitHubAdapter(
        _github_config(retry_count=2, max_items=1),
        urlopen=stub,
        now_provider=lambda: _FIXED_NOW,
        sleep=lambda s: None,
    )
    items = a.fetch()
    assert len(items) == 1
    assert len(stub.calls) == 2


def test_fetch_429_no_retry_after_then_success():
    rec = []
    stub = _Stub(payloads=(_resp(_repo()).encode(),), errors=(_http_error(429),))
    a = GitHubAdapter(
        _github_config(retry_count=2, rate_limit="1/1s", max_items=1),
        urlopen=stub,
        now_provider=lambda: _FIXED_NOW,
        sleep=lambda s: rec.append(s),
    )
    items = a.fetch()
    assert len(items) == 1
    assert len(stub.calls) == 2
    # fallback = max(parse_retry_after(None)=1.0, rate_limit 1.0) = 1.0
    assert rec and 0.9 <= rec[0] <= 1.1


def test_fetch_429_exhausted_raises():
    stub = _Stub(errors=(_http_error(429), _http_error(429), _http_error(429)))
    a = GitHubAdapter(
        _github_config(retry_count=2),
        urlopen=stub,
        now_provider=lambda: _FIXED_NOW,
        sleep=lambda s: None,
    )
    with pytest.raises(AdapterError):
        a.fetch()
    assert len(stub.calls) == 3


def test_parse_retry_after_variants():
    fn = GitHubAdapter._parse_retry_after
    assert fn("5") == 5.0
    assert fn("0") == 0.0
    assert fn(None) == 1.0
    assert fn("abc") == 1.0
    assert fn("1000") == 60.0  # capped


def test_parse_rate_limit_variants():
    assert parse_rate_limit("1/6s") == 6.0
    assert parse_rate_limit("2/1s") == 0.5
    assert parse_rate_limit("") == 0.0
    assert parse_rate_limit("garbage") == 0.0


# ---------------------------------------------------------------------------
# 11. retry_count semantics
# ---------------------------------------------------------------------------


def test_retry_count_zero_single_attempt_success():
    stub = _Stub(payloads=(_resp(_repo()).encode(),))
    a = GitHubAdapter(
        _github_config(retry_count=0, max_items=1),
        urlopen=stub,
        now_provider=lambda: _FIXED_NOW,
        sleep=lambda s: None,
    )
    assert len(a.fetch()) == 1
    assert len(stub.calls) == 1


def test_retry_count_zero_single_attempt_failure():
    stub = _Stub(errors=(_http_error(500),))
    a = GitHubAdapter(
        _github_config(retry_count=0),
        urlopen=stub,
        now_provider=lambda: _FIXED_NOW,
        sleep=lambda s: None,
    )
    with pytest.raises(AdapterError):
        a.fetch()
    assert len(stub.calls) == 1  # attempts = 1 + 0


def test_retry_count_two_three_attempts():
    stub = _Stub(
        errors=(_http_error(500), _http_error(500), _http_error(500))
    )
    a = GitHubAdapter(
        _github_config(retry_count=2),
        urlopen=stub,
        now_provider=lambda: _FIXED_NOW,
        sleep=lambda s: None,
    )
    with pytest.raises(AdapterError):
        a.fetch()
    assert len(stub.calls) == 3  # attempts = 1 + 2


# ---------------------------------------------------------------------------
# 12. Network exceptions
# ---------------------------------------------------------------------------


def test_fetch_urlerror_retries_then_fails():
    stub = _Stub(errors=(URLError("boom"), URLError("boom"), URLError("boom")))
    a = GitHubAdapter(
        _github_config(retry_count=2),
        urlopen=stub,
        now_provider=lambda: _FIXED_NOW,
        sleep=lambda s: None,
    )
    with pytest.raises(AdapterError):
        a.fetch()
    assert len(stub.calls) == 3


def test_fetch_socket_timeout_retries_then_fails():
    stub = _Stub(errors=(socket.timeout("timed out"), socket.timeout("timed out")))
    a = GitHubAdapter(
        _github_config(retry_count=1),
        urlopen=stub,
        now_provider=lambda: _FIXED_NOW,
        sleep=lambda s: None,
    )
    with pytest.raises(AdapterError):
        a.fetch()
    assert len(stub.calls) == 2


def test_fetch_timeout_error_retries_then_fails():
    stub = _Stub(errors=(TimeoutError("to"), TimeoutError("to")))
    a = GitHubAdapter(
        _github_config(retry_count=1),
        urlopen=stub,
        now_provider=lambda: _FIXED_NOW,
        sleep=lambda s: None,
    )
    with pytest.raises(AdapterError):
        a.fetch()
    assert len(stub.calls) == 2


def test_fetch_urlerror_then_success():
    stub = _Stub(payloads=(_resp(_repo()).encode(),), errors=(URLError("boom"),))
    a = GitHubAdapter(
        _github_config(retry_count=2, max_items=1),
        urlopen=stub,
        now_provider=lambda: _FIXED_NOW,
        sleep=lambda s: None,
    )
    assert len(a.fetch()) == 1
    assert len(stub.calls) == 2


# ---------------------------------------------------------------------------
# 13/14/15. URL validation (normal + malicious + allowed_domains)
# ---------------------------------------------------------------------------


def test_parse_normal_url_accepted():
    cfg = _github_config()
    items = parse_github_response(
        _resp(_repo(html_url="https://github.com/openai/example")), cfg, _FIXED_NOW
    )
    assert len(items) == 1
    assert items[0].original_url == "https://github.com/openai/example"


def test_parse_malicious_suffix_rejected():
    good = _repo(rid=1, html_url="https://github.com/openai/example")
    evil = _repo(rid=2, html_url="https://github.com.evil.com/openai/example")
    cfg = _github_config()
    items = parse_github_response(_resp(good, evil), cfg, _FIXED_NOW)
    assert [it.source_item_id for it in items] == ["1"]


def test_parse_notgithub_rejected():
    good = _repo(rid=1, html_url="https://github.com/openai/example")
    evil = _repo(rid=2, html_url="https://notgithub.com/openai/example")
    cfg = _github_config()
    items = parse_github_response(_resp(good, evil), cfg, _FIXED_NOW)
    assert [it.source_item_id for it in items] == ["1"]


def test_allowed_domains_per_verify_rule():
    # Reuse the real verify_original_url (do NOT re-implement).
    dom = ["github.com"]
    assert verify_original_url("https://github.com/x/y", dom, require_https=False) is True
    # Suffix match rule: www.github.com ends with ".github.com".
    assert verify_original_url("https://www.github.com/x/y", dom, require_https=False) is True
    assert verify_original_url("https://github.com.evil.com/x/y", dom, require_https=False) is False
    assert verify_original_url("https://notgithub.com/x/y", dom, require_https=False) is False


# ---------------------------------------------------------------------------
# 16. source_item_id stability
# ---------------------------------------------------------------------------


def test_source_item_id_stability():
    cfg = _github_config()
    ids = [
        parse_github_response(_resp(_repo(rid=123456)), cfg, _FIXED_NOW)[0].source_item_id
        for _ in range(3)
    ]
    assert ids == ["123456", "123456", "123456"]


# ---------------------------------------------------------------------------
# 17. published_at semantics: pushed_at preferred, created_at fallback
#     Stage 1-19A: published_at now uses pushed_at (hot/active signal)
#     instead of created_at (repo birth time).
# ---------------------------------------------------------------------------


def test_published_at_prefers_pushed_at():
    """When pushed_at is present and valid, published_at MUST equal pushed_at
    (not created_at). The default fixture has pushed_at=2026-06-01 and
    created_at=2026-01-01."""
    cfg = _github_config()
    items = parse_github_response(_resp(_repo()), cfg, _FIXED_NOW)
    it = items[0]
    assert it.published_at == datetime(2026, 6, 1, 0, 0, 0, tzinfo=timezone.utc)
    assert it.published_at != datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    # metadata still carries BOTH raw timestamps untouched:
    assert it.metadata["pushed_at"] == "2026-06-01T00:00:00Z"
    assert it.metadata["created_at"] == "2026-01-01T00:00:00Z"


def test_published_at_falls_back_to_created_when_no_pushed_at():
    """When pushed_at is missing (None), published_at falls back to created_at."""
    cfg = _github_config()
    items = parse_github_response(
        _resp(_repo(pushed_at=None)), cfg, _FIXED_NOW
    )
    it = items[0]
    assert it.published_at == datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    assert it.metadata["pushed_at"] is None


def test_published_at_falls_back_to_created_when_pushed_at_invalid():
    """When pushed_at is present but unparseable, fall back to created_at."""
    cfg = _github_config()
    items = parse_github_response(
        _resp(_repo(pushed_at="not-a-real-date")), cfg, _FIXED_NOW
    )
    it = items[0]
    assert it.published_at == datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


def test_published_at_skip_when_both_invalid():
    """When BOTH pushed_at and created_at are missing/unparseable, the item
    is safely skipped (never fabricates a time)."""
    cfg = _github_config()
    items = parse_github_response(
        _resp(_repo(pushed_at=None, created_at="garbage")), cfg, _FIXED_NOW
    )
    assert items == []


# ---------------------------------------------------------------------------
# 19. Token handling (offline, via _headers)
# ---------------------------------------------------------------------------


def test_headers_no_token(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    a = GitHubAdapter(_github_config(), sleep=lambda s: None)
    headers = a._headers()
    assert "Authorization" not in headers
    assert headers["Accept"] == "application/vnd.github+json"
    assert headers["User-Agent"].startswith("daily-trend-radar")


def test_headers_with_token(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    a = GitHubAdapter(_github_config(), sleep=lambda s: None)
    headers = a._headers()
    assert headers["Authorization"] == "Bearer test-token"


def test_fetch_injects_token_header(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    stub = _Stub(payloads=(_resp(_repo()).encode(),))
    a = GitHubAdapter(
        _github_config(), urlopen=stub, now_provider=lambda: _FIXED_NOW, sleep=lambda s: None
    )
    a.fetch()
    assert stub.calls[0][1].get("Authorization") == "Bearer test-token"


def test_token_never_in_metadata(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    cfg = _github_config()
    items = parse_github_response(_resp(_repo()), cfg, _FIXED_NOW)
    assert "token" not in items[0].metadata
    assert "Authorization" not in items[0].metadata


# ---------------------------------------------------------------------------
# 20. URL construction
# ---------------------------------------------------------------------------


def test_build_url_encodes_query_and_params():
    a = GitHubAdapter(_github_config(query="stars:>1000 pushed:>2026-06-24"), sleep=lambda s: None)
    url = a._build_url(2, 50)
    parts = urlparse(url)
    qs = parse_qs(parts.query)
    assert parts.scheme == "https"
    assert parts.netloc == "api.github.com"
    assert parts.path == "/search/repositories"
    assert qs["q"][0] == "stars:>1000 pushed:>2026-06-24"
    assert qs["sort"][0] == "stars"
    assert qs["order"][0] == "desc"
    assert qs["per_page"][0] == "50"
    assert qs["page"][0] == "2"


# ---------------------------------------------------------------------------
# 21. Registry
# ---------------------------------------------------------------------------


def test_registry_maps_github_and_arxiv():
    from pipeline.adapters.arxiv import ArxivAdapter

    assert _ADAPTER_REGISTRY["github"] is GitHubAdapter
    assert _ADAPTER_REGISTRY["arxiv"] is ArxivAdapter


def test_build_registry_includes_enabled_github():
    reg = build_registry([_github_config(enabled=True)])
    assert "github" in reg
    assert isinstance(reg["github"], GitHubAdapter)


def test_build_registry_keeps_arxiv_unaffected():
    from pipeline.adapters.arxiv import ArxivAdapter

    reg = build_registry(
        [
            _github_config(enabled=True),
            _github_config(id="arxiv", enabled=True),
        ]
    )
    # arxiv config above is malformed-ish; just ensure github present & arxiv
    # mapping still resolves via registry.
    assert "github" in reg
    assert _ADAPTER_REGISTRY["arxiv"] is ArxivAdapter


# ---------------------------------------------------------------------------
# 22. Disabled source
# ---------------------------------------------------------------------------


def test_disabled_source_not_run_by_registry():
    reg = build_registry([_github_config(enabled=False)])
    assert reg == {}


def test_disabled_source_fetch_returns_empty_no_request():
    calls = []

    def _no_call(req, timeout):
        calls.append(1)
        raise AssertionError("urlopen must not be called for disabled source")

    a = GitHubAdapter(
        _github_config(enabled=False),
        urlopen=_no_call,
        now_provider=lambda: _FIXED_NOW,
        sleep=lambda s: None,
    )
    assert a.fetch() == []
    assert calls == []


# ---------------------------------------------------------------------------
# 23. Production-data isolation
# ---------------------------------------------------------------------------


def test_no_production_data_written(tmp_path, monkeypatch):
    """The GitHub Adapter's fetch() must never write production data to
    disk -- independent of whether a previous real Pipeline run has
    already populated this checkout's data/2026 (Local-first: real
    run artifacts stay on the user's machine). Run inside a throwaway
    dir so any accidental filesystem write would land under tmp_path
    and be detected. Fully decoupled from the project data/."""
    # Page 1 returns 2 repos, page 2 is empty (realistic GitHub
    # pagination termination) so the adapter stops after 2 items.
    stub = _Stub(payloads=[_resp(_repo(), _repo(rid=99)), _resp()])
    adapter = GitHubAdapter(
        _github_config(enabled=True),
        urlopen=stub,
        now_provider=lambda: _FIXED_NOW,
        sleep=lambda s: None,
    )
    monkeypatch.chdir(tmp_path)
    items = adapter.fetch()
    assert len(items) == 2
    # Adapter must not have created any production data under its cwd.
    assert not (tmp_path / "data" / "2026").exists()
    assert not (tmp_path / "data").exists()


# ---------------------------------------------------------------------------
# 24. Boundary hardening (Stage 1-17B)
#     Lock current behavior for null numeric metrics, over-long description,
#     and the hardcoded ``lang="en"``. These are PURE parse tests -- no
#     network, no API, no production data. They only assert the adapter's
#     EXISTING behavior; none of them changes production logic.
# ---------------------------------------------------------------------------

# A description deliberately far longer than any "normal" summary (10k chars).
_LONG_DESCRIPTION = "A" * 10000


def test_parse_stars_none_preserved():
    """Stage 1-17B (audit gap 1): ``stargazers_count: null`` must NOT
    raise, must NOT be skipped, and must surface as ``metadata["stars"] is None``
    (no fabricated 0 / no coerced value)."""
    cfg = _github_config()
    items = parse_github_response(
        _resp(_repo(stargazers_count=None)), cfg, _FIXED_NOW
    )
    assert len(items) == 1  # not skipped
    assert items[0].metadata["stars"] is None


def test_parse_forks_none_preserved():
    """Stage 1-17B (audit gap 2): ``forks_count: null`` must NOT raise,
    must NOT be skipped, and must surface as ``metadata["forks"] is None``."""
    cfg = _github_config()
    items = parse_github_response(
        _resp(_repo(forks_count=None)), cfg, _FIXED_NOW
    )
    assert len(items) == 1  # not skipped
    assert items[0].metadata["forks"] is None


def test_parse_very_long_description_not_truncated():
    """Stage 1-17B (audit gap 3): an over-long ``description`` must NOT raise,
    must NOT be skipped, and ``summary`` must keep the FULL original content
    (no unexpected truncation). No length cap is added here -- we only lock
    the current pass-through behavior."""
    cfg = _github_config()
    items = parse_github_response(
        _resp(_repo(description=_LONG_DESCRIPTION)), cfg, _FIXED_NOW
    )
    assert len(items) == 1  # not skipped
    summary = items[0].summary
    assert summary is not None
    assert len(summary) == len(_LONG_DESCRIPTION)  # nothing truncated
    assert summary == _LONG_DESCRIPTION  # full, unchanged content retained


def test_parse_lang_hardcoded_en():
    """Stage 1-17B (audit gap 4): lock the current ``lang="en"`` behavior.

    The adapter sets ``RawItem.lang`` to the literal ``"en"`` regardless of the
    repo's real GitHub ``language`` field. This is distinct from
    ``metadata["language"]``, which faithfully carries the raw API value
    (``"Python"`` in this fixture) -- it is NOT coerced to ``"en"``.

    This test pins the *current* behavior only. Do NOT change production code
    to make ``metadata["language"]`` equal ``"en"``; that is a separate
    (deliberately deferred) design decision, not part of Stage 1-17B.
    """
    cfg = _github_config()
    items = parse_github_response(_resp(_repo()), cfg, _FIXED_NOW)
    it = items[0]
    assert it.lang == "en"  # hardcoded, language-agnostic
    # Raw API language is preserved separately, NOT forced to "en":
    assert it.metadata["language"] == "Python"


# ---------------------------------------------------------------------------
# 25. Publish-layer metadata passthrough (Stage 1-19A)
#     Verify that GitHub adapter metadata survives the full
#     RawItem -> NormalizedItem -> Trend chain and reaches the published
#     Trend model.  Pure offline: no API, no Pipeline, no data written.
# ---------------------------------------------------------------------------

_SB = ScoreBreakdown(
    authority=50, heat=50, freshness=50, multi_source=50, platform=50
)


def _github_trend(repo=None):
    """Parse a GitHub repo fixture -> RawItem -> NormalizedItem -> Trend.
    Returns the Trend so tests can assert its published metadata."""
    cfg = _github_config()
    raw_items = parse_github_response(_resp(repo or _repo()), cfg, _FIXED_NOW)
    assert raw_items, "fixture must produce at least one item"
    raw = raw_items[0]
    norm = raw.as_normalized("opensource")
    norm.canonical_url = norm.original_url  # simulate Normalize URL canon
    return build_trend(norm, hot_score=50.0, breakdown=_SB)


def test_publish_metadata_reaches_trend():
    """GitHub metadata (stars/forks/language/pushed_at/api_url/name/owner)
    must survive RawItem -> NormalizedItem -> Trend and appear on the
    published Trend model."""
    t = _github_trend()
    md = t.metadata
    assert md is not None
    assert md["stars"] == 100
    assert md["forks"] == 10
    assert md["language"] == "Python"
    assert md["pushed_at"] == "2026-06-01T00:00:00Z"
    assert md["created_at"] == "2026-01-01T00:00:00Z"
    assert md["updated_at"] == "2026-06-02T00:00:00Z"
    assert md["api_url"] == "https://api.github.com/repos/octo/cat"
    assert md["name"] == "cat"
    assert md["owner"] == "octo"


def test_publish_metadata_stars_none_preserved():
    """stars=None must survive the publish chain as None (no 0 fabrication)."""
    t = _github_trend(_repo(stargazers_count=None))
    assert t.metadata is not None
    assert t.metadata["stars"] is None


def test_publish_metadata_forks_none_preserved():
    """forks=None must survive the publish chain as None."""
    t = _github_trend(_repo(forks_count=None))
    assert t.metadata is not None
    assert t.metadata["forks"] is None


def test_publish_metadata_language_none_preserved():
    """language=None must survive the publish chain as None."""
    t = _github_trend(_repo(language=None))
    assert t.metadata is not None
    assert t.metadata["language"] is None
