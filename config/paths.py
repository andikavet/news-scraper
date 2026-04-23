"""Centralised filesystem paths for the config layer.

Having one place that computes paths keeps tests easy (override via env var) and
prevents any other module from hard-coding on-disk locations.
"""

from __future__ import annotations

import os
from pathlib import Path

_ENV_VAR = "NEWS_SCRAPER_CONFIG_DIR"


def config_dir() -> Path:
    """Return the active config directory.

    Resolution order:
    1. ``NEWS_SCRAPER_CONFIG_DIR`` env var (useful for tests and docker volumes)
    2. ``<repo_root>/config`` (the default for local dev)
    """
    override = os.environ.get(_ENV_VAR)
    if override:
        return Path(override).expanduser().resolve()
    # This file lives in <repo_root>/config/paths.py
    return Path(__file__).resolve().parent


def sources_path() -> Path:
    return config_dir() / "sources.json"


def categorizers_path() -> Path:
    return config_dir() / "categorizers.json"


def app_settings_path() -> Path:
    return config_dir() / "app_settings.yaml"


__all__ = [
    "app_settings_path",
    "categorizers_path",
    "config_dir",
    "sources_path",
]
