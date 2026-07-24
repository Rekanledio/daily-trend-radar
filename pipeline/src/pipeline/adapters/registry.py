"""Source adapter registry (Stage 1-4A).

Maps a ``source_id`` to its concrete ``SourceAdapter`` implementation. This
is the ONLY place that wires adapter classes to source ids -- the pipeline
orchestrator never does ``if source_id == "arxiv"``. To add a future
source (github / rss / ...) just register its adapter class in
``_ADAPTER_REGISTRY`` below; nothing else needs to change.
"""

from __future__ import annotations

from typing import Dict, Type

from ..models import SourceConfig
from .arxiv import ArxivAdapter
from .base import SourceAdapter

# source_id -> adapter class. Only arXiv is a real, evaluated source today
# (Stage 1-3A). Future sources are added here, NOT via branching in the
# orchestrator.
_ADAPTER_REGISTRY: Dict[str, Type[SourceAdapter]] = {
    "arxiv": ArxivAdapter,
}


def build_adapter(config: SourceConfig) -> SourceAdapter:
    """Instantiate the adapter registered for ``config.id``."""
    cls = _ADAPTER_REGISTRY.get(config.id)
    if cls is None:
        raise ValueError(
            f"No adapter registered for source id '{config.id}'. "
            f"Known adapters: {sorted(_ADAPTER_REGISTRY)}"
        )
    return cls(config=config)


def build_registry(configs: list[SourceConfig]) -> Dict[str, SourceAdapter]:
    """Instantiate adapters for every ENABLED source (disabled are skipped)."""
    registry: Dict[str, SourceAdapter] = {}
    for cfg in configs:
        if not cfg.enabled:
            continue
        registry[cfg.id] = build_adapter(cfg)
    return registry
