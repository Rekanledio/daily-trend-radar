"""Adapter sub-package for Daily Trend Radar data sources.

Holds the unified ``SourceAdapter`` contract (``base.py``) plus, in later
stages, one module per data source (arxiv / github / rss_generic / ...).

This package defines the INTERFACE only. Stage 1-2 does NOT implement any
real adapter (no ArXiv, GitHub, RSS, network, API or RSS calls).

Stage 1-3A adds the first real adapter: ``arxiv`` (official ArXiv Atom
API). It is importable here so a future orchestrator can discover it, but
it performs NO network IO unless its ``fetch()`` is actually called.
"""

from .arxiv import ArxivAdapter, parse_arxiv_feed

__all__ = ["ArxivAdapter", "parse_arxiv_feed"]
