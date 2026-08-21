"""Thin wrapper around the official `neo4j` driver.

Injects the target database and owns the driver lifecycle so the rest of the
app never manages sessions/transactions manually (spec/03-architecture-spec.md).
"""

from __future__ import annotations

from neo4j import AsyncDriver, AsyncGraphDatabase, RoutingControl

from app.config import Settings


class Neo4jConnection:
    def __init__(self, settings: Settings) -> None:
        self._database = settings.neo4j_database
        self._driver: AsyncDriver = AsyncGraphDatabase.driver(
            settings.neo4j_uri, auth=(settings.neo4j_username, settings.neo4j_password)
        )

    async def verify_connectivity(self) -> None:
        await self._driver.verify_connectivity()

    async def close(self) -> None:
        await self._driver.close()

    async def write(self, query: str, **parameters: object) -> list:
        result = await self._driver.execute_query(
            query, parameters, database_=self._database, routing_=RoutingControl.WRITE
        )
        return result.records

    async def read(self, query: str, **parameters: object) -> list:
        result = await self._driver.execute_query(
            query, parameters, database_=self._database, routing_=RoutingControl.READ
        )
        return result.records
