"""Offline tests for the ArXiv adapter (Stage 1-3A).

NO real network, NO real API, NO real data. Every test runs fully offline:
- Fixture (parse) tests exercise the pure ``parse_arxiv_feed`` on a checked-in
  XML sample (``fixtures/arxiv_sample.xml``).
- Behavior tests exercise ``ArxivAdapter.fetch`` with an injected ``urlopen``
  stub (no sockets touched).

The one real-network smoke check (allowed by the user, never written to
data/ and never committed) is performed manually outside this suite.
"""

from __future__ import annotations

import email
import pathlib
from datetime import datetime, timezone
from email.message import Message
from urllib.error import HTTPError

import pytest

from pipeline.adapters import ArxivAdapter, parse_arxiv_feed
from pipeline.adapters.arxiv import AdapterError, _Response
from pipeline.models import LegalStatus, SourceConfig, SourceType

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_FIXTURE_PATH = pathlib.Path(__file__).parent / "fixtures" / "arxiv_sample.xml"
_FIXTURE_XML = _FIXTURE_PATH.read_text(encoding="utf-8")

_EMPTY_FEED = (
    b'<?xml version="1.0" encoding="UTF-8"?>'
    b'<feed xmlns="http://www.w3.org/2005/Atom"></feed>'
)

FIXED_NOW = datetime(2026, 7, 24, 9, 0, 0, tzinfo=timezone.utc)

_NS = "http://www.w3.org/2005/Atom"


def _arxiv_config(**over) -> SourceConfig:
    base = dict(
        id="arxiv",
        name="arXiv",
        category="ai_research",
        type=SourceType.API,
        enabled=True,
        priority=1,
        max_items=20,
        timeout=20,
        retry_count=2,
        rate_limit="1/3s",
        legal_status=LegalStatus.OFFICIAL_API,
        terms_url="https://arxiv.org/help/api/tou",
        endpoint="http://export.arxiv.org/api/query",
        query="cat:cs.AI OR cat:cs.CL OR cat:cs.LG",
        allowed_domains=["arxiv.org"],
    )
    base.update(over)
    return SourceConfig(**base)


def _entry_xml(
    eid: str,
    title: str = "Title",
    summary: str = "Summary",
    authors: tuple[str, ...] = ("A",),
    categories: tuple[str, ...] = ("cs.AI",),
    published: str = "2023-12-20T00:00:00Z",
    updated: str = "2024-01-15T00:00:00Z",
    has_published: bool = True,
    has_author: bool = True,
) -> str:
    pub = f"<published>{published}</published>" if has_published else ""
    auth = (
        "".join(f"<author><name>{a}</name></author>" for a in authors)
        if has_author
        else ""
    )
    cats = "".join(f'<category term="{c}"/>' for c in categories)
    return (
        f'<entry xmlns="{_NS}">'
        f"<id>{eid}</id>"
        f"<updated>{updated}</updated>{pub}"
        f"<title>{title}</title>"
        f"<summary>{summary}</summary>{auth}{cats}"
        f'<primary_category term="{categories[0]}"/>'
        f"</entry>"
    )


def _feed_xml(entries: list[str]) -> bytes:
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<feed xmlns="{_NS}">' + "".join(entries) + "</feed>"
    ).encode("utf-8")


class _Stub:
    """Injectable ``urlopen``. ``errors[i]`` is raised on the i-th call;
    afterwards ``payloads`` are returned in order (last one repeats)."""

    def __init__(self, payloads: tuple[bytes, ...] = (), errors: tuple[Exception, ...] = ()):
        self.payloads = list(payloads)
        self.errors = list(errors)
        self.calls: list[str] = []
        self._i = 0

    def __call__(self, url: str, timeout: int) -> _Response:
        self.calls.append(url)
        i = self._i
        self._i += 1
        if i < len(self.errors):
            raise self.errors[i]
        pi = i - len(self.errors)
        if self.payloads:
            body = self.payloads[min(pi, len(self.payloads) - 1)]
        else:
            body = _EMPTY_FEED
        return _Response(body)


def _http_error(code: int, headers: Message | None = None) -> HTTPError:
    return HTTPError(
        "http://export.arxiv.org/api/query", code, "err", headers, None
    )


# ---------------------------------------------------------------------------
# A. OFFLINE FIXTURE PARSE TESTS (16) -- pure parse_arxiv_feed
# ---------------------------------------------------------------------------


def test_parse_fixture_returns_three_items():
    items = parse_arxiv_feed(_FIXTURE_XML, _arxiv_config(), FIXED_NOW)
    assert len(items) == 3


def test_parse_title_stripped_of_whitespace():
    items = parse_arxiv_feed(_FIXTURE_XML, _arxiv_config(), FIXED_NOW)
    assert items[0].title == "A Nice Paper About Diffusion Models"


def test_parse_original_url_is_https_arxiv_shape():
    items = parse_arxiv_feed(_FIXTURE_XML, _arxiv_config(), FIXED_NOW)
    assert all(it.original_url.startswith("https://arxiv.org/abs/") for it in items)
    assert items[0].original_url == "https://arxiv.org/abs/2312.12345v1"


def test_parse_source_item_id_is_arxiv_id():
    items = parse_arxiv_feed(_FIXTURE_XML, _arxiv_config(), FIXED_NOW)
    assert items[0].source_item_id == "2312.12345v1"


def test_parse_published_at_parsed_to_utc():
    items = parse_arxiv_feed(_FIXTURE_XML, _arxiv_config(), FIXED_NOW)
    assert items[0].published_at == datetime(2023, 12, 20, 0, 0, 0, tzinfo=timezone.utc)


def test_parse_authors_in_metadata():
    items = parse_arxiv_feed(_FIXTURE_XML, _arxiv_config(), FIXED_NOW)
    assert items[0].metadata["authors"] == ["Alice Scientist", "Bob Researcher"]


def test_parse_categories_in_metadata():
    items = parse_arxiv_feed(_FIXTURE_XML, _arxiv_config(), FIXED_NOW)
    assert "cs.AI" in items[0].metadata["categories"]
    assert "cs.LG" in items[0].metadata["categories"]


def test_parse_updated_at_metadata_is_z_string():
    items = parse_arxiv_feed(_FIXTURE_XML, _arxiv_config(), FIXED_NOW)
    val = items[0].metadata["updated_at"]
    assert isinstance(val, str)
    assert val.endswith("Z")
    assert val == "2024-01-15T00:00:00Z"


def test_parse_arxiv_id_in_metadata():
    items = parse_arxiv_feed(_FIXTURE_XML, _arxiv_config(), FIXED_NOW)
    assert items[0].metadata["arxiv_id"] == "2312.12345v1"
    assert items[0].metadata["primary_category"] == "cs.AI"


def test_parse_summary_carried():
    items = parse_arxiv_feed(_FIXTURE_XML, _arxiv_config(), FIXED_NOW)
    assert items[0].summary is not None
    assert items[0].summary.startswith("We present a method")


def test_parse_lang_defaults_to_en():
    items = parse_arxiv_feed(_FIXTURE_XML, _arxiv_config(), FIXED_NOW)
    assert all(it.lang == "en" for it in items)


def test_parse_source_id_and_name_from_config():
    items = parse_arxiv_feed(_FIXTURE_XML, _arxiv_config(), FIXED_NOW)
    assert all(it.source_id == "arxiv" for it in items)
    assert all(it.source_name == "arXiv" for it in items)


def test_parse_fetched_at_set_to_provider():
    items = parse_arxiv_feed(_FIXTURE_XML, _arxiv_config(), FIXED_NOW)
    assert all(it.fetched_at == FIXED_NOW for it in items)


def test_parse_entry_without_published_is_none():
    items = parse_arxiv_feed(_FIXTURE_XML, _arxiv_config(), FIXED_NOW)
    # Entry #2 (2401.00099v2) has no <published>.
    assert items[1].source_item_id == "2401.00099v2"
    assert items[1].published_at is None


def test_parse_entry_without_author_yields_empty_list():
    items = parse_arxiv_feed(_FIXTURE_XML, _arxiv_config(), FIXED_NOW)
    # Entry #3 (2403.54321v1) has no <author>.
    assert items[2].source_item_id == "2403.54321v1"
    assert items[2].metadata["authors"] == []


def test_parse_invalid_xml_raises_adapter_error():
    with pytest.raises(AdapterError):
        parse_arxiv_feed("<feed><unclosed>", _arxiv_config(), FIXED_NOW)


# ---------------------------------------------------------------------------
# B. ADAPTER BEHAVIOR TESTS (9) -- fetch() with injected urlopen
# ---------------------------------------------------------------------------


def test_fetch_happy_path_returns_items():
    stub = _Stub(payloads=(_FIXTURE_XML.encode("utf-8"), _EMPTY_FEED))
    adapter = ArxivAdapter(
        _arxiv_config(), urlopen=stub, now_provider=lambda: FIXED_NOW, sleep=lambda s: None
    )
    items = adapter.fetch()
    assert len(items) == 3
    assert all(it.original_url.startswith("https://arxiv.org/abs/") for it in items)


def test_fetch_respects_max_items():
    five = _feed_xml([_entry_xml(f"http://arxiv.org/abs/2401.0000{i}v1") for i in range(5)])
    stub = _Stub(payloads=(five, _EMPTY_FEED))
    adapter = ArxivAdapter(
        _arxiv_config(max_items=2),
        urlopen=stub,
        now_provider=lambda: FIXED_NOW,
        sleep=lambda s: None,
    )
    items = adapter.fetch()
    assert len(items) == 2


def test_fetch_paginates_until_max_items():
    page1 = _feed_xml(
        [_entry_xml("http://arxiv.org/abs/2401.00001v1"),
         _entry_xml("http://arxiv.org/abs/2401.00002v1")]
    )
    page2 = _feed_xml(
        [_entry_xml("http://arxiv.org/abs/2401.00003v1"),
         _entry_xml("http://arxiv.org/abs/2401.00004v1")]
    )
    stub = _Stub(payloads=(page1, page2, _EMPTY_FEED))
    adapter = ArxivAdapter(
        _arxiv_config(max_items=4),
        urlopen=stub,
        now_provider=lambda: FIXED_NOW,
        sleep=lambda s: None,
    )
    items = adapter.fetch()
    assert len(items) == 4
    # Two HTTP requests (two non-empty pages) before hitting the cap.
    # (calls now hold urllib Request objects after the User-Agent change.)
    assert len(stub.calls) == 2
    assert "start=0" in stub.calls[0].full_url
    assert "start=2" in stub.calls[1].full_url


def test_fetch_retries_then_succeeds():
    stub = _Stub(
        payloads=(_FIXTURE_XML.encode("utf-8"),),
        errors=(_http_error(500),),
    )
    adapter = ArxivAdapter(
        _arxiv_config(max_items=3, retry_count=2),
        urlopen=stub,
        now_provider=lambda: FIXED_NOW,
        sleep=lambda s: None,
    )
    items = adapter.fetch()  # first call 500 -> retry -> 2nd call ok
    assert len(items) == 3
    assert len(stub.calls) == 2


def test_fetch_raises_adapter_error_after_retries():
    stub = _Stub(errors=(_http_error(500), _http_error(500), _http_error(500)))
    adapter = ArxivAdapter(
        _arxiv_config(retry_count=2),  # attempts = 1 + 2 = 3
        urlopen=stub,
        now_provider=lambda: FIXED_NOW,
        sleep=lambda s: None,
    )
    with pytest.raises(AdapterError):
        adapter.fetch()


def test_fetch_handles_429_retry_after():
    hdr = email.message_from_string("Retry-After: 0\n")
    stub = _Stub(
        payloads=(_FIXTURE_XML.encode("utf-8"),),
        errors=(_http_error(429, hdr),),
    )
    adapter = ArxivAdapter(
        _arxiv_config(max_items=3, retry_count=2),
        urlopen=stub,
        now_provider=lambda: FIXED_NOW,
        sleep=lambda s: None,
    )
    items = adapter.fetch()
    assert len(items) == 3
    assert len(stub.calls) == 2  # 429 then success


def test_fetch_xml_error_raises_adapter_error():
    stub = _Stub(payloads=(b"<feed xmlns=\"http://www.w3.org/2005/Atom\"><entry>",))
    adapter = ArxivAdapter(
        _arxiv_config(),
        urlopen=stub,
        now_provider=lambda: FIXED_NOW,
        sleep=lambda s: None,
    )
    with pytest.raises(AdapterError):
        adapter.fetch()


def test_fetch_single_entry_isolation():
    feed = _feed_xml(
        [
            _entry_xml("http://arxiv.org/abs/2401.11111v1"),
            "<entry><title>Missing id, must be skipped</title></entry>",
        ]
    )
    stub = _Stub(payloads=(feed, _EMPTY_FEED))
    adapter = ArxivAdapter(
        _arxiv_config(),
        urlopen=stub,
        now_provider=lambda: FIXED_NOW,
        sleep=lambda s: None,
    )
    items = adapter.fetch()
    assert len(items) == 1
    assert items[0].source_item_id == "2401.11111v1"


def test_fetch_drops_suffix_attack_entry():
    feed = _feed_xml(
        [
            _entry_xml("http://arxiv.org/abs/2401.22222v1"),
            _entry_xml("http://arxiv.org.evil.com/abs/999"),  # suffix forgery
        ]
    )
    stub = _Stub(payloads=(feed, _EMPTY_FEED))
    adapter = ArxivAdapter(
        _arxiv_config(allowed_domains=["arxiv.org"]),
        urlopen=stub,
        now_provider=lambda: FIXED_NOW,
        sleep=lambda s: None,
    )
    items = adapter.fetch()
    assert len(items) == 1
    assert items[0].original_url == "https://arxiv.org/abs/2401.22222v1"


# ---------------------------------------------------------------------------
# C. CONFIG CONTRACT TEST (bonus) -- sources.yaml loads + allowed_domains
# ---------------------------------------------------------------------------


def test_sources_yaml_arxiv_has_allowed_domains():
    import yaml

    cfg_path = pathlib.Path(__file__).resolve().parents[2] / "config" / "sources.yaml"
    data = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    arxiv = next((s for s in data["sources"] if s["id"] == "arxiv"), None)
    assert arxiv is not None
    assert arxiv["allowed_domains"] == ["arxiv.org"]
    assert arxiv["category"] == "ai_research"
    # The loaded dict must also construct a valid SourceConfig (anti-drift).
    cfg = SourceConfig(**arxiv)
    assert cfg.allowed_domains == ["arxiv.org"]
    assert cfg.endpoint == "http://export.arxiv.org/api/query"
