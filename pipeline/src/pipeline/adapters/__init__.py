"""Adapter sub-package for Daily Trend Radar data sources.

Holds the unified ``SourceAdapter`` contract (``base.py``) plus, in later
stages, one module per data source (arxiv / github / rss_generic / ...).

This package defines the INTERFACE only. Stage 1-2 does NOT implement any
real adapter (no ArXiv, GitHub, RSS, network, API or RSS calls).
"""
