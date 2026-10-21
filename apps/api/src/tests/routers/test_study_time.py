from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.core.events.database import get_db_session
from src.routers.courses.activities.activities import router
from src.security.auth import get_current_user


@pytest.fixture
async def client(db, regular_user):
    app = FastAPI()
    app.include_router(router, prefix="/activities")
    app.dependency_overrides[get_db_session] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: regular_user
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest.mark.parametrize("counter", [-1, 1.5, "15", True, 2**53])
async def test_invalid_counters_are_rejected(client, activity, counter):
    response = await client.post(f"/activities/{activity.activity_uuid}/study-time", json={"session_id": str(uuid4()), "total_ms": counter})
    assert response.status_code == 422


async def test_valid_own_heartbeat_and_invalid_session(client, activity):
    response = await client.post(f"/activities/{activity.activity_uuid}/study-time", json={"session_id": str(uuid4()), "total_ms": 0})
    assert response.status_code == 200
    assert response.json()["active_seconds"] == 0
    response = await client.post(f"/activities/{activity.activity_uuid}/study-time", json={"session_id": "invalid", "total_ms": 0})
    assert response.status_code == 422
