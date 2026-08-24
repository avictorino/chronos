"""Thin wrapper around a `google.cloud.firestore.AsyncClient` — Firestore is
the *only* datastore for the ingestion pipeline. Loads a service-account key
file explicitly (pydantic-settings reads `.env` into this process without
exporting it to `os.environ`, so `google.auth.default()` would never see
`GOOGLE_APPLICATION_CREDENTIALS` otherwise), falling back to ambient
Application Default Credentials when no key path is configured.
"""

from __future__ import annotations

from google.cloud import firestore
from google.oauth2 import service_account

from app.config import Settings


class FirestoreConnection:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: firestore.AsyncClient | None = None

    async def connect(self) -> None:
        if self._client is not None:
            return
        if not self._settings.firebase_project_id:
            raise RuntimeError("FIREBASE_PROJECT_ID is not set — required to connect to Firestore.")
        credentials = None
        if self._settings.google_application_credentials:
            credentials = service_account.Credentials.from_service_account_file(
                self._settings.google_application_credentials
            )
        self._client = firestore.AsyncClient(project=self._settings.firebase_project_id, credentials=credentials)

    async def verify_connectivity(self) -> None:
        await self.connect()
        assert self._client is not None
        # A cheap read that doesn't require any collection/document to exist —
        # just proves the credentials/project are valid and reachable.
        await self._client.collection("_connectivity_check").limit(1).get()

    async def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    @property
    def db(self) -> firestore.AsyncClient:
        assert self._client is not None, "call connect()/verify_connectivity() first"
        return self._client
