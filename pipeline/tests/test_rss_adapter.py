"""Offline tests for the generic RSS/Atom adapter (Stage 1-3C).

Every behavior is exercised with an INJECTED ``urlopen`` stub -- no real
network, no real RSS data, no real feed URLs are touched. The goal is to
prove the adapter parses RSS 2.0 / Atom correctly, isolates bad entries,
verifies ``original_url`` against ``allowed_domains``, honors max_items,
and handles HTTP 403/429/retry/timeouts -- all from in-memory fixtures.
"""

from __future__ import annotations

import hashlib
import socket
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError

import pytest

from pipeline.adapters.base import AdapterError
from pipeline.adapters.registry import _ADAPTER_REGISTRY, build_adapter
from pipeline.adapters.rss import RSSAdapter, parse_rss_response
from pipeline.models import LegalStatus, SourceConfig, SourceType
from pipeline.stages import canonicalize_url

# ---------------------------------------------------------------------------
# Offline harness
# ---------------------------------------------------------------------------


class _Resp:
    """Minimal http response stand-in (supports context manager + read)."""

    def __init__(self, body: str, headers: dict | None = None) -> None:
        self._body = body.encode("utf-8") if isinstance(body, str) else body
        self.headers = headers or {}

    def __enter__(self) -> "_Resp":
        return self

    def __exit__(self, *_a: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


class _Stub:
    """urlopen stub: returns 200 with a body, or raises a configured error."""

    def __init__(
        self,
        body: str | None = None,
        code: int = 200,
        headers: dict | None = None,
        exc: BaseException | None = None,
    ) -> None:
        self._body = body
        self._code = code
        self._headers = headers or {}
        self._exc = exc
        self.calls: list = []

    def __call__(self, req: object, timeout: int) -> _Resp:
        self.calls.append((req, timeout))
        if self._exc is not None:
            raise self._exc
        if self._code != 200:
            raise HTTPError(str(req), self._code, "err", self._headers, None)
        return _Resp(self._body, self._headers)


class _ThenOk:
    """urlopen stub that fails once (with ``exc``) then returns 200."""

    def __init__(self, exc: BaseException, body: str, headers: dict | None = None) -> None:
        self._exc = exc
        self._ok = _Resp(body, headers)
        self.calls: list = []

    def __call__(self, req: object, timeout: int) -> _Resp:
        self.calls.append((req, timeout))
        if len(self.calls) == 1:
            raise self._exc
        return self._ok


def _rss_config(**over: object) -> SourceConfig:
    """Build a valid RSS SourceConfig (all required fields present)."""
    base = dict(
        id="openai_blog",
        name="Test RSS",
        category="ai_official",
        type=SourceType.RSS,
        enabled=True,
        priority=1,
        max_items=20,
        timeout=15,
        retry_count=2,
        rate_limit="1/5s",
        legal_status=LegalStatus.OFFICIAL_RSS,
        endpoint="https://example.com/feed.xml",
        allowed_domains=["example.com"],
    )
    base.update(over)
    return SourceConfig(**base)


def _rss_xml(items: list[dict], ns: bool = False) -> str:
    """Build an RSS 2.0 document from a list of item dicts.

    Optional fields are only emitted when present, so a test can build a
    malformed entry (e.g. missing ``title`` / ``link`` / ``pub``).
    """
    dc = ' xmlns:dc="http://purl.org/dc/elements/1.1/"' if ns else ""
    out = ['<?xml version="1.0"?>', f'<rss version="2.0"{dc}>', "  <channel>",
           "    <title>Test Feed</title>"]
    for it in items:
        out.append("    <item>")
        if "title" in it:
            out.append(f'      <title>{it["title"]}</title>')
        if "link" in it:
            out.append(f'      <link>{it["link"]}</link>')
        if "guid" in it:
            out.append(f'      <guid>{it["guid"]}</guid>')
        if "desc" in it:
            out.append(f'      <description>{it["desc"]}</description>')
        if "pub" in it:
            out.append(f'      <pubDate>{it["pub"]}</pubDate>')
        if "author" in it:
            out.append(f'      <author>{it["author"]}</author>')
        if "cat" in it:
            out.append(f'      <category>{it["cat"]}</category>')
        out.append("    </item>")
    out.append("  </channel>")
    out.append("</rss>")
    return "\n".join(out)


def _atom_xml(entries: list[dict], ns: bool = True) -> str:
    """Build an Atom document from a list of entry dicts.

    Optional fields are only emitted when present.
    """
    ns_attr = ' xmlns="http://www.w3.org/2005/Atom"' if ns else ""
    out = ['<?xml version="1.0"?>', f"<feed{ns_attr}>", "  <title>Atom</title>"]
    for e in entries:
        out.append("  <entry>")
        if "title" in e:
            out.append(f'    <title>{e["title"]}</title>')
        if "link" in e:
            out.append(f'    <link href="{e["link"]}" rel="alternate"/>')
        if "id" in e:
            out.append(f'    <id>{e["id"]}</id>')
        if "summary" in e:
            out.append(f'    <summary>{e["summary"]}</summary>')
        if "published" in e:
            out.append(f'    <published>{e["published"]}</published>')
        if "updated" in e:
            out.append(f'    <updated>{e["updated"]}</updated>')
        out.append("  </entry>")
    out.append("</feed>")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# 1. RSS 2.0 normal
# ---------------------------------------------------------------------------


def test_rss_2_0_normal():
    xml = _rss_xml([
        {"title": "One", "link": "https://example.com/one", "guid": "g1",
         "desc": "d1", "pub": "Tue, 24 Jul 2026 10:00:00 GMT"},
        {"title": "Two", "link": "https://example.com/two", "guid": "g2",
         "desc": "d2", "pub": "Wed, 25 Jul 2026 11:00:00 GMT"},
        {"title": "Three", "link": "https://example.com/three", "guid": "g3",
         "desc": "d3", "pub": "Thu, 26 Jul 2026 12:00:00 GMT"},
    ])
    cfg = _rss_config()
    items = parse_rss_response(xml, cfg, datetime(2026, 7, 24, tzinfo=timezone.utc))
    assert len(items) == 3
    assert items[0].title == "One"
    assert items[0].original_url == "https://example.com/one"
    assert items[0].source_item_id == "g1"


# ---------------------------------------------------------------------------
# 2. Atom normal
# ---------------------------------------------------------------------------


def test_atom_normal():
    xml = _atom_xml([
        {"title": "A1", "link": "https://example.com/a1", "id": "id1",
         "summary": "s1", "published": "2026-07-24T10:00:00Z"},
        {"title": "A2", "link": "https://example.com/a2", "id": "id2",
         "summary": "s2", "published": "2026-07-25T10:00:00Z"},
    ])
    cfg = _rss_config()
    items = parse_rss_response(xml, cfg, datetime(2026, 7, 24, tzinfo=timezone.utc))
    assert len(items) == 2
    assert items[0].title == "A1"
    assert items[0].original_url == "https://example.com/a1"
    assert items[0].metadata["feed_type"] == "atom"


# ---------------------------------------------------------------------------
# 3. XML namespace handling
# ---------------------------------------------------------------------------


def test_namespace_rss_and_atom():
    # RSS with an extra namespace prefix must still parse by local name.
    xml_rss = _rss_xml([
        {"title": "N1", "link": "https://example.com/n1", "guid": "ng1",
         "pub": "Tue, 24 Jul 2026 10:00:00 GMT"},
    ], ns=True)
    cfg = _rss_config()
    items = parse_rss_response(xml_rss, cfg, datetime(2026, 7, 24, tzinfo=timezone.utc))
    assert len(items) == 1
    assert items[0].original_url == "https://example.com/n1"
    # Atom is inherently namespaced; verify it parses regardless.
    xml_atom = _atom_xml([
        {"title": "AN1", "link": "https://example.com/an1", "id": "aid1",
         "published": "2026-07-24T10:00:00Z"},
    ], ns=True)
    items2 = parse_rss_response(xml_atom, cfg, datetime(2026, 7, 24, tzinfo=timezone.utc))
    assert len(items2) == 1
    assert items2[0].metadata["feed_type"] == "atom"


# ---------------------------------------------------------------------------
# 4. Empty feed
# ---------------------------------------------------------------------------


def test_empty_feed():
    cfg = _rss_config()
    rss = '<?xml version="1.0"?><rss version="2.0"><channel><title>x</title></channel></rss>'
    atom = '<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><title>x</title></feed>'
    assert parse_rss_response(rss, cfg, datetime(2026, 7, 24, tzinfo=timezone.utc)) == []
    assert parse_rss_response(atom, cfg, datetime(2026, 7, 24, tzinfo=timezone.utc)) == []


# ---------------------------------------------------------------------------
# 5. max_items
# ---------------------------------------------------------------------------


def test_max_items():
    items = [
        {"title": f"P{i}", "link": f"https://example.com/p{i}", "guid": f"g{i}",
         "pub": "Tue, 24 Jul 2026 10:00:00 GMT"}
        for i in range(3)
    ]
    # max_items is enforced by fetch(), not by parse_rss_response().
    cfg = _rss_config(max_items=2)
    stub = _Stub(body=_rss_xml(items))
    out = RSSAdapter(cfg, urlopen=stub).fetch()
    assert len(out) == 2
    assert [o.title for o in out] == ["P0", "P1"]


# ---------------------------------------------------------------------------
# 6 / 7. RSS / Atom multi entry
# ---------------------------------------------------------------------------


def test_rss_multi_entry():
    items = [
        {"title": f"R{i}", "link": f"https://example.com/r{i}", "guid": f"rg{i}",
         "pub": "Tue, 24 Jul 2026 10:00:00 GMT"}
        for i in range(5)
    ]
    cfg = _rss_config()
    out = parse_rss_response(_rss_xml(items), cfg, datetime(2026, 7, 24, tzinfo=timezone.utc))
    assert len(out) == 5


def test_atom_multi_entry():
    entries = [
        {"title": f"A{i}", "link": f"https://example.com/a{i}", "id": f"aid{i}",
         "published": "2026-07-24T10:00:00Z"}
        for i in range(4)
    ]
    cfg = _rss_config()
    out = parse_rss_response(_atom_xml(entries), cfg, datetime(2026, 7, 24, tzinfo=timezone.utc))
    assert len(out) == 4


# ---------------------------------------------------------------------------
# 8. Single entry missing title -> skip
# ---------------------------------------------------------------------------


def test_single_missing_title():
    items = [
        {"link": "https://example.com/good", "guid": "g0",
         "pub": "Tue, 24 Jul 2026 10:00:00 GMT"},
        {"title": "HasTitle", "link": "https://example.com/ok", "guid": "g1",
         "pub": "Tue, 24 Jul 2026 10:00:00 GMT"},
    ]
    cfg = _rss_config()
    out = parse_rss_response(_rss_xml(items), cfg, datetime(2026, 7, 24, tzinfo=timezone.utc))
    assert len(out) == 1
    assert out[0].source_item_id == "g1"


# ---------------------------------------------------------------------------
# 9. Single entry missing url -> skip
# ---------------------------------------------------------------------------


def test_single_missing_url():
    items = [
        {"title": "NoLink", "guid": "g0",
         "pub": "Tue, 24 Jul 2026 10:00:00 GMT"},
        {"title": "HasLink", "link": "https://example.com/ok", "guid": "g1",
         "pub": "Tue, 24 Jul 2026 10:00:00 GMT"},
    ]
    cfg = _rss_config()
    out = parse_rss_response(_rss_xml(items), cfg, datetime(2026, 7, 24, tzinfo=timezone.utc))
    assert len(out) == 1
    assert out[0].source_item_id == "g1"


# ---------------------------------------------------------------------------
# 10. Single entry with malicious url -> skip
# ---------------------------------------------------------------------------


def test_single_malicious_url():
    items = [
        {"title": "Evil", "link": "https://evil.com/x", "guid": "g0",
         "pub": "Tue, 24 Jul 2026 10:00:00 GMT"},
        {"title": "Good", "link": "https://example.com/ok", "guid": "g1",
         "pub": "Tue, 24 Jul 2026 10:00:00 GMT"},
    ]
    cfg = _rss_config()
    out = parse_rss_response(_rss_xml(items), cfg, datetime(2026, 7, 24, tzinfo=timezone.utc))
    assert len(out) == 1
    assert out[0].source_item_id == "g1"


# ---------------------------------------------------------------------------
# 11. Suffix-forgery domain (github.com.evil.com) -> skip
# ---------------------------------------------------------------------------


def test_suffix_forgery_github_com_evil():
    items = [
        {"title": "Forged", "link": "https://github.com.evil.com/x", "guid": "g0",
         "pub": "Tue, 24 Jul 2026 10:00:00 GMT"},
    ]
    # allowed_domains like github: only the real host is allowed.
    cfg = _rss_config(allowed_domains=["github.com"],
                        endpoint="https://api.github.com/feeds")
    out = parse_rss_response(_rss_xml(items), cfg, datetime(2026, 7, 24, tzinfo=timezone.utc))
    assert out == []


# ---------------------------------------------------------------------------
# 12. allowed_domains (positive: exact + subdomain)
# ---------------------------------------------------------------------------


def test_allowed_domains():
    items = [
        {"title": "Exact", "link": "https://example.com/a", "guid": "g0",
         "pub": "Tue, 24 Jul 2026 10:00:00 GMT"},
        {"title": "Sub", "link": "https://blog.example.com/b", "guid": "g1",
         "pub": "Tue, 24 Jul 2026 10:00:00 GMT"},
    ]
    cfg = _rss_config()
    out = parse_rss_response(_rss_xml(items), cfg, datetime(2026, 7, 24, tzinfo=timezone.utc))
    assert len(out) == 2


# ---------------------------------------------------------------------------
# 13. source_item_id from RSS guid
# ---------------------------------------------------------------------------


def test_source_item_id_guid():
    items = [{"title": "T", "link": "https://example.com/x", "guid": "stable-guid-123",
              "pub": "Tue, 24 Jul 2026 10:00:00 GMT"}]
    cfg = _rss_config()
    out = parse_rss_response(_rss_xml(items), cfg, datetime(2026, 7, 24, tzinfo=timezone.utc))
    assert out[0].source_item_id == "stable-guid-123"


# ---------------------------------------------------------------------------
# 14. source_item_id from Atom id
# ---------------------------------------------------------------------------


def test_source_item_id_atom_id():
    entries = [{"title": "T", "link": "https://example.com/x", "id": "atom-id-xyz",
                "published": "2026-07-24T10:00:00Z"}]
    cfg = _rss_config()
    out = parse_rss_response(_atom_xml(entries), cfg, datetime(2026, 7, 24, tzinfo=timezone.utc))
    assert out[0].source_item_id == "atom-id-xyz"


# ---------------------------------------------------------------------------
# 15. source_item_id fallback to sha256(url)[:16]
# ---------------------------------------------------------------------------


def test_source_item_id_fallback_hash():
    link = "https://example.com/no-id"
    items = [{"title": "T", "link": link,
              "pub": "Tue, 24 Jul 2026 10:00:00 GMT"}]
    cfg = _rss_config()
    out = parse_rss_response(_rss_xml(items), cfg, datetime(2026, 7, 24, tzinfo=timezone.utc))
    expected = hashlib.sha256(canonicalize_url(link).encode("utf-8")).hexdigest()[:16]
    assert out[0].source_item_id == expected


# ---------------------------------------------------------------------------
# 16. source_item_id stability (same input -> same id)
# ---------------------------------------------------------------------------


def test_source_item_id_stability():
    link = "https://example.com/stable"
    items = [{"title": "T", "link": link,
              "pub": "Tue, 24 Jul 2026 10:00:00 GMT"}]
    cfg = _rss_config()
    xml = _rss_xml(items)
    a = parse_rss_response(xml, cfg, datetime(2026, 7, 24, tzinfo=timezone.utc))
    b = parse_rss_response(xml, cfg, datetime(2026, 7, 24, tzinfo=timezone.utc))
    assert a[0].source_item_id == b[0].source_item_id
    assert len(a[0].source_item_id) == 16


# ---------------------------------------------------------------------------
# 17. published_at from RFC822 (RSS pubDate)
# ---------------------------------------------------------------------------


def test_published_at_rfc822():
    items = [{"title": "T", "link": "https://example.com/x", "guid": "g0",
              "pub": "Tue, 24 Jul 2026 10:00:00 GMT"}]
    cfg = _rss_config()
    out = parse_rss_response(_rss_xml(items), cfg, datetime(2026, 7, 24, tzinfo=timezone.utc))
    assert out[0].published_at == datetime(2026, 7, 24, 10, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# 18. published_at from ISO 8601
# ---------------------------------------------------------------------------


def test_published_at_iso8601():
    # Atom ISO.
    entries = [{"title": "T", "link": "https://example.com/x", "id": "i",
                "published": "2026-07-24T10:00:00Z"}]
    cfg = _rss_config()
    out = parse_rss_response(_atom_xml(entries), cfg, datetime(2026, 7, 24, tzinfo=timezone.utc))
    assert out[0].published_at == datetime(2026, 7, 24, 10, 0, tzinfo=timezone.utc)
    # RSS pubDate carrying an ISO string is also parsed (iso tried first).
    items = [{"title": "T", "link": "https://example.com/x", "guid": "g0",
              "pub": "2026-07-24T09:30:00+00:00"}]
    out2 = parse_rss_response(_rss_xml(items), cfg, datetime(2026, 7, 24, tzinfo=timezone.utc))
    assert out2[0].published_at == datetime(2026, 7, 24, 9, 30, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# 19. Atom published preferred over updated
# ---------------------------------------------------------------------------


def test_published_vs_updated_atom():
    entries = [{"title": "T", "link": "https://example.com/x", "id": "i",
                "published": "2026-07-24T10:00:00Z",
                "updated": "2026-07-25T10:00:00Z"}]
    cfg = _rss_config()
    out = parse_rss_response(_atom_xml(entries), cfg, datetime(2026, 7, 24, tzinfo=timezone.utc))
    assert out[0].published_at == datetime(2026, 7, 24, 10, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# 20. Illegal time -> skip
# ---------------------------------------------------------------------------


def test_illegal_time_skip():
    items = [
        {"title": "Bad", "link": "https://example.com/bad", "guid": "g0", "pub": "not-a-date"},
        {"title": "Good", "link": "https://example.com/ok", "guid": "g1",
         "pub": "Tue, 24 Jul 2026 10:00:00 GMT"},
    ]
    cfg = _rss_config()
    out = parse_rss_response(_rss_xml(items), cfg, datetime(2026, 7, 24, tzinfo=timezone.utc))
    assert len(out) == 1
    assert out[0].source_item_id == "g1"


# ---------------------------------------------------------------------------
# 21. Missing time -> skip
# ---------------------------------------------------------------------------


def test_missing_time_skip():
    items = [
        {"title": "NoTime", "link": "https://example.com/x", "guid": "g0"},
        {"title": "Good", "link": "https://example.com/ok", "guid": "g1",
         "pub": "Tue, 24 Jul 2026 10:00:00 GMT"},
    ]
    cfg = _rss_config()
    out = parse_rss_response(_rss_xml(items), cfg, datetime(2026, 7, 24, tzinfo=timezone.utc))
    assert len(out) == 1
    assert out[0].source_item_id == "g1"


# ---------------------------------------------------------------------------
# 22. Malformed XML -> AdapterError
# ---------------------------------------------------------------------------


def test_malformed_xml():
    cfg = _rss_config()
    with pytest.raises(AdapterError):
        parse_rss_response("<<<not xml", cfg, datetime(2026, 7, 24, tzinfo=timezone.utc))


# ---------------------------------------------------------------------------
# 23. Top-level structure anomaly -> AdapterError
# ---------------------------------------------------------------------------


def test_top_level_structure_anomaly():
    cfg = _rss_config()
    # Valid XML but wrong root element.
    with pytest.raises(AdapterError):
        parse_rss_response(
            '<html><body>hi</body></html>', cfg,
            datetime(2026, 7, 24, tzinfo=timezone.utc),
        )
    # RSS root but no <channel>.
    with pytest.raises(AdapterError):
        parse_rss_response(
            '<?xml version="1.0"?><rss version="2.0"><title>x</title></rss>',
            cfg, datetime(2026, 7, 24, tzinfo=timezone.utc),
        )


# ---------------------------------------------------------------------------
# 24. 403 auth (no rate-limit signal) -> no retry
# ---------------------------------------------------------------------------


def test_403_auth_no_retry():
    stub = _Stub(code=403, headers={})  # no X-RateLimit-* -> auth/permission
    cfg = _rss_config()
    with pytest.raises(AdapterError):
        RSSAdapter(cfg, urlopen=stub).fetch()
    assert len(stub.calls) == 1  # immediately fails, no retry


# ---------------------------------------------------------------------------
# 25. 403 rate-limit -> retry then succeed
# ---------------------------------------------------------------------------


def test_403_rate_limit_retry():
    reset_ts = str(int((datetime.now(timezone.utc) + timedelta(days=1)).timestamp()))
    err = HTTPError("u", 403, "e",
                    {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": reset_ts}, None)
    body = _rss_xml([{"title": "T", "link": "https://example.com/x", "guid": "g0",
                      "pub": "Tue, 24 Jul 2026 10:00:00 GMT"}])
    stub = _ThenOk(err, body)
    slept: list = []
    cfg = _rss_config()
    out = RSSAdapter(cfg, urlopen=stub, sleep=lambda s: slept.append(s)).fetch()
    assert len(out) == 1
    assert len(stub.calls) == 2  # retried once


# ---------------------------------------------------------------------------
# 26. 429 with Retry-After -> retry then succeed
# ---------------------------------------------------------------------------


def test_429_retry_after():
    err = HTTPError("u", 429, "e", {"Retry-After": "1"}, None)
    body = _atom_xml([{"title": "T", "link": "https://example.com/x", "id": "i",
                       "published": "2026-07-24T10:00:00Z"}])
    stub = _ThenOk(err, body)
    slept: list = []
    cfg = _rss_config()
    out = RSSAdapter(cfg, urlopen=stub, sleep=lambda s: slept.append(s)).fetch()
    assert len(out) == 1
    assert len(stub.calls) == 2


# ---------------------------------------------------------------------------
# 27. Retry-After parsing
# ---------------------------------------------------------------------------


def test_retry_after_parsing():
    assert RSSAdapter._parse_retry_after("30") == 30.0
    assert RSSAdapter._parse_retry_after("0") == 0.0
    assert RSSAdapter._parse_retry_after(None) == 1.0
    assert RSSAdapter._parse_retry_after("garbage") == 1.0
    assert RSSAdapter._parse_retry_after("120") == 60.0  # capped


# ---------------------------------------------------------------------------
# 28. retry_count behavior
# ---------------------------------------------------------------------------


def test_retry_count():
    # retry_count=0 -> only 1 attempt, then AdapterError.
    stub0 = _Stub(code=429, headers={"Retry-After": "0"})
    cfg0 = _rss_config(retry_count=0)
    with pytest.raises(AdapterError):
        RSSAdapter(cfg0, urlopen=stub0).fetch()
    assert len(stub0.calls) == 1
    # retry_count=2 -> 3 attempts before giving up.
    stub2 = _Stub(code=429, headers={"Retry-After": "0"})
    cfg2 = _rss_config(retry_count=2)
    with pytest.raises(AdapterError):
        RSSAdapter(cfg2, urlopen=stub2).fetch()
    assert len(stub2.calls) == 3


# ---------------------------------------------------------------------------
# 29. rate_limit interval is honored
# ---------------------------------------------------------------------------


def test_rate_limit():
    slept: list = []
    cfg = _rss_config(rate_limit="1/2s")
    adapter = RSSAdapter(cfg, sleep=lambda s: slept.append(s))
    adapter._rate_limit_wait()
    adapter._rate_limit_wait()  # second call should wait ~2s
    assert len(slept) == 1
    assert abs(slept[0] - 2.0) < 0.5


# ---------------------------------------------------------------------------
# 30. Network exception (URLError)
# ---------------------------------------------------------------------------


def test_network_exception():
    stub = _Stub(exc=URLError("network down"))
    cfg = _rss_config()
    with pytest.raises(AdapterError):
        RSSAdapter(cfg, urlopen=stub).fetch()


# ---------------------------------------------------------------------------
# 31. Timeout
# ---------------------------------------------------------------------------


def test_timeout():
    stub = _Stub(exc=socket.timeout("timed out"))
    cfg = _rss_config()
    with pytest.raises(AdapterError):
        RSSAdapter(cfg, urlopen=stub).fetch()


# ---------------------------------------------------------------------------
# 32. TimeoutError (generic)
# ---------------------------------------------------------------------------


def test_timeout_error():
    stub = _Stub(exc=TimeoutError("took too long"))
    cfg = _rss_config()
    with pytest.raises(AdapterError):
        RSSAdapter(cfg, urlopen=stub).fetch()


# ---------------------------------------------------------------------------
# 33. Single bad entry isolation (mixed feed)
# ---------------------------------------------------------------------------


def test_single_bad_data_isolation():
    items = [
        {"title": "Good1", "link": "https://example.com/a", "guid": "g0",
         "pub": "Tue, 24 Jul 2026 10:00:00 GMT"},
        {"title": "MissingLink", "guid": "g1",
         "pub": "Tue, 24 Jul 2026 10:00:00 GMT"},
        {"title": "Good2", "link": "https://example.com/b", "guid": "g2",
         "pub": "Tue, 24 Jul 2026 10:00:00 GMT"},
    ]
    cfg = _rss_config()
    out = parse_rss_response(_rss_xml(items), cfg, datetime(2026, 7, 24, tzinfo=timezone.utc))
    assert len(out) == 2
    assert {o.source_item_id for o in out} == {"g0", "g2"}


# ---------------------------------------------------------------------------
# 34. metadata carries public fields only
# ---------------------------------------------------------------------------


def test_metadata():
    items = [{"title": "T", "link": "https://example.com/x", "guid": "g0",
              "desc": "summary text", "author": "Jane", "cat": "ml",
              "pub": "Tue, 24 Jul 2026 10:00:00 GMT"}]
    cfg = _rss_config()
    out = parse_rss_response(_rss_xml(items), cfg, datetime(2026, 7, 24, tzinfo=timezone.utc))
    meta = out[0].metadata
    assert meta["feed_type"] == "rss"
    assert meta["author"] == "Jane"
    assert meta["categories"] == ["ml"]
    assert "token" not in meta and "secret" not in meta


# ---------------------------------------------------------------------------
# 35. original_url is the real feed link, not forged
# ---------------------------------------------------------------------------


def test_real_url_not_forged():
    link = "https://example.com/path/to/article?ref=foo"
    items = [{"title": "T", "link": link, "guid": "g0",
              "pub": "Tue, 24 Jul 2026 10:00:00 GMT"}]
    cfg = _rss_config()
    out = parse_rss_response(_rss_xml(items), cfg, datetime(2026, 7, 24, tzinfo=timezone.utc))
    assert out[0].original_url == link  # byte-identical, no substitution


# ---------------------------------------------------------------------------
# 36. Registry wiring
# ---------------------------------------------------------------------------


def test_registry():
    assert _ADAPTER_REGISTRY.get("openai_blog") is RSSAdapter
    adapter = build_adapter(_rss_config(enabled=True))
    assert isinstance(adapter, RSSAdapter)
    # Unknown source id -> ValueError.
    with pytest.raises(ValueError):
        build_adapter(_rss_config(id="does_not_exist"))


# ---------------------------------------------------------------------------
# 37. Disabled source -> fetch returns []
# ---------------------------------------------------------------------------


def test_disabled_source():
    cfg = _rss_config(enabled=False)
    adapter = RSSAdapter(cfg, urlopen=_Stub(body="<rss/>"))
    assert adapter.fetch() == []


# ---------------------------------------------------------------------------
# 38. No production data is written (data/2026 never created)
# ---------------------------------------------------------------------------


def test_no_data_2026_written(tmp_path, monkeypatch):
    """The RSS Adapter's fetch() must never write production data to
    disk -- independent of whether a previous real Pipeline run has
    already populated this checkout's data/2026 (Local-first). Run
    inside a throwaway dir so any accidental write would land under
    tmp_path and be detected. Fully decoupled from the project data/."""
    body = _rss_xml([{"title": "T", "link": "https://example.com/x", "guid": "g0",
                      "pub": "Tue, 24 Jul 2026 10:00:00 GMT"}])
    stub = _Stub(body=body)
    cfg = _rss_config()
    monkeypatch.chdir(tmp_path)
    out = RSSAdapter(cfg, urlopen=stub).fetch()
    assert len(out) == 1
    # The adapter never touches the filesystem; no data/2026 produced
    # under its cwd (now the throwaway tmp_path).
    assert not (tmp_path / "data" / "2026").exists()
    assert not (tmp_path / "data").exists()
