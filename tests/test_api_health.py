from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.mark.parametrize("database_ok,qdrant_ok", [(True, True), (False, True), (True, False), (False, False)])
def test_health_checks_both_dependencies(database_ok, qdrant_ok):
    from app.main import app
    database = AsyncMock(side_effect=None if database_ok else RuntimeError("db password hidden"))
    qdrant = AsyncMock(side_effect=None if qdrant_ok else RuntimeError("qdrant secret hidden"))
    with patch("app.api.health._database_probe", database), patch("app.api.health._qdrant_probe", qdrant):
        response = TestClient(app).get("/api/v1/health")
    assert response.status_code == (200 if database_ok and qdrant_ok else 503)
    assert response.json()["dependencies"] == {
        "database": "ok" if database_ok else "error",
        "qdrant": "ok" if qdrant_ok else "error",
    }
    assert "hidden" not in response.text
    database.assert_awaited_once()
    qdrant.assert_awaited_once()
