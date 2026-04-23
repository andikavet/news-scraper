"""Smoke tests for config.store — covers round-trips and schema validation.

These are intentionally quick; the full behavioural tests land in later iterations
as actual scraping code lands.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml


# Point the config layer at a tmp dir BEFORE importing config.*
@pytest.fixture()
def isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("NEWS_SCRAPER_CONFIG_DIR", str(tmp_path))
    # Re-import so the path fn picks up the env var.
    import importlib

    import config.paths as paths_mod

    importlib.reload(paths_mod)
    import config.store as store_mod

    importlib.reload(store_mod)
    import config as config_pkg

    importlib.reload(config_pkg)
    yield tmp_path


def test_load_sources_empty_returns_empty_list(isolated_config):
    from config import load_sources

    assert load_sources() == []


def test_save_and_load_sources_roundtrip(isolated_config):
    from config import (
        ScraperSelectors,
        ScrapeSource,
        SleepRange,
        load_sources,
        save_sources,
    )

    src = ScrapeSource(
        name="Portal X",
        pagination_type="url_params",
        url_template="https://x.test/indeks?page={page}",
        selectors=ScraperSelectors(container=".item", title="h2 a", link="h2 a", date=".date"),
        avg_page_per_month=40,
        sleep=SleepRange(min=1.0, max=2.5),
        max_retries=2,
        enabled_layers=[1, 3],
    )
    save_sources([src])
    loaded = load_sources()
    assert len(loaded) == 1
    assert loaded[0].name == "Portal X"
    assert loaded[0].enabled_layers == [1, 3]


def test_save_and_load_categorizers_roundtrip(isolated_config):
    from config import (
        CategorizerGrouping,
        CategoryRule,
        load_categorizers,
        save_categorizers,
    )

    g = CategorizerGrouping(
        name="GDP Sector",
        rules=[
            CategoryRule(
                category="Agriculture",
                include_tokens=["padi", "sawah"],
                exclude_tokens=["subsidi"],
            ),
            CategoryRule(category="Mining", include_tokens=["tambang"]),
        ],
    )
    save_categorizers([g])
    loaded = load_categorizers()
    assert len(loaded) == 1
    assert {r.category for r in loaded[0].rules} == {"Agriculture", "Mining"}


def test_app_settings_default_when_missing(isolated_config):
    from config import load_app_settings

    s = load_app_settings()
    assert s.log_level == "INFO"
    assert s.default_min_sleep == 1.5


def test_app_settings_save_then_load(isolated_config, tmp_path: Path):
    from config import AppSettings, load_app_settings, save_app_settings

    save_app_settings(AppSettings(overall_exclude_tokens=["sponsor", "iklan"], log_level="DEBUG"))
    # Sanity: file written as yaml
    raw = (tmp_path / "app_settings.yaml").read_text()
    parsed = yaml.safe_load(raw)
    assert parsed["log_level"] == "DEBUG"

    s = load_app_settings()
    assert s.overall_exclude_tokens == ["sponsor", "iklan"]


def test_source_rejects_bad_sleep_range(isolated_config):
    from pydantic import ValidationError

    from config import ScraperSelectors, ScrapeSource, SleepRange

    with pytest.raises(ValidationError):
        ScrapeSource(
            name="X",
            url_template="https://x.test/?page={page}",
            selectors=ScraperSelectors(container="a", title="a", link="a", date="a"),
            sleep=SleepRange(min=5.0, max=1.0),
        )


def test_source_rejects_empty_enabled_layers(isolated_config):
    from pydantic import ValidationError

    from config import ScraperSelectors, ScrapeSource

    with pytest.raises(ValidationError):
        ScrapeSource(
            name="X",
            url_template="https://x.test/?page={page}",
            selectors=ScraperSelectors(container="a", title="a", link="a", date="a"),
            enabled_layers=[],
        )
