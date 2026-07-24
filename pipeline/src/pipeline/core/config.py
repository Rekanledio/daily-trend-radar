"""Static configuration loader for Daily Trend Radar.

Loads ``config/sources.yaml`` (human-authored, version-controlled) into the
Pydantic ``SourcesConfig`` model. This is the SINGLE place that knows the
YAML layout; the rest of the pipeline consumes typed ``SourceConfig``
objects. Pure-ish: it only reads a file and validates it -- no network,
no API, no AI, no pipeline logic.

The config/sources.yaml <-> Pipeline boundary is the documented "two
separations" rule (PROJECT_RULES section five / v2 section 5): this file
is the static, human-owned description of *what/how* to collect; runtime
state (health/sources_state) is written elsewhere and must stay separate.
"""

from __future__ import annotations

import pathlib
from typing import Union

import yaml

from ..models import SourcesConfig


def _find_project_root() -> pathlib.Path:
    """Walk up from this file to the repo root (holds ``schemas/`` + ``config/``).

    Robust to import-path depth differences (``python -m pipeline`` vs a
    ``sys.path`` insert): we locate the directory that actually contains the
    project's ``schemas`` and ``config`` directories, rather than guessing
    a fixed parent index.
    """
    here = pathlib.Path(__file__).resolve()
    for cand in [here, *here.parents]:
        if (cand / "schemas").is_dir() and (cand / "config").is_dir():
            return cand
    # Fallback for unusual layouts.
    return here.parents[4]


_PROJECT_ROOT = _find_project_root()


def load_sources_config(path: Union[str, pathlib.Path]) -> SourcesConfig:
    """Parse a ``sources.yaml`` file into a validated ``SourcesConfig``."""
    raw = pathlib.Path(path).read_text(encoding="utf-8")
    data = yaml.safe_load(raw) or {}
    return SourcesConfig.model_validate(data)


def load_categories(config: SourcesConfig) -> set[str]:
    """Distinct configured categories (consumed by the Validation red line)."""
    return {s.category for s in config.sources}


def default_config_path(project_root: Union[str, pathlib.Path, None] = None) -> pathlib.Path:
    """Locate ``config/sources.yaml``.

    Resolution order: explicit ``project_root`` -> this package's project
    root -> current working directory. The CLI passes an explicit root.
    """
    if project_root is not None:
        return pathlib.Path(project_root) / "config" / "sources.yaml"
    candidate = _PROJECT_ROOT / "config" / "sources.yaml"
    if candidate.exists():
        return candidate
    return pathlib.Path.cwd() / "config" / "sources.yaml"


def project_root() -> pathlib.Path:
    """The repository root (parent of ``config/``, ``data/``, ``schemas/``)."""
    return _PROJECT_ROOT
