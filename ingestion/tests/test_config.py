from __future__ import annotations

from app.config import Settings


def test_blank_embedding_dimensions_env_var_means_auto_detect(monkeypatch):
    """A committed `.env` with `EMBEDDING_DIMENSIONS=` (blank, meaning "auto
    detect") arrives to pydantic-settings as an empty string, which int-parsing
    would otherwise reject outright — regression test for that bug."""
    monkeypatch.setenv("EMBEDDING_DIMENSIONS", "")
    settings = Settings(_env_file=None)
    assert settings.embedding_dimensions is None


def test_explicit_embedding_dimensions_env_var_is_parsed(monkeypatch):
    monkeypatch.setenv("EMBEDDING_DIMENSIONS", "768")
    settings = Settings(_env_file=None)
    assert settings.embedding_dimensions == 768
