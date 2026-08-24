from __future__ import annotations

from app.config import Settings


def test_settings_defaults_load_without_firebase_credentials(monkeypatch):
    """Settings() must construct fine with no Firebase env vars set — only
    `ingest` (without --dry-run) actually requires them at connect time (see
    app/services/ingestion_service.py::_build_deps)."""
    monkeypatch.delenv("FIREBASE_PROJECT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    settings = Settings(_env_file=None)
    assert settings.firebase_project_id is None
    assert settings.google_application_credentials is None
