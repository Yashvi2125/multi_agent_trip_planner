import atexit
import os
import shutil
import tempfile

# A file-backed SQLite database, so every thread gets its own connection (as with Postgres). One shared in-memory
# connection made the request, planner and notifier threads trample each other's transactions: a flaky suite.
_DB_DIR = tempfile.mkdtemp(prefix="wayfare-test-")
atexit.register(shutil.rmtree, _DB_DIR, ignore_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_DIR}/test.db"
os.environ["RATE_LIMIT_ENABLED"] = "false"
os.environ["JWT_SECRET"] = "test-secret"
os.environ["BCRYPT_ROUNDS"] = "4"
os.environ["PLANNER_MODE"] = "stub"

from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from app.core.database import Base, engine
from app.main import app


@pytest.fixture(autouse=True)
def fake_planner(monkeypatch):
    """Every test gets a planner wired to fakes: no LLM key, no weather network."""
    from app.graph.deps import Deps
    from app.services import planner_gateway
    from app.services.planner_runner import PlannerRunner
    from tests.fakes import FakeLLM, FakeWeather
    from datetime import date
    runner = PlannerRunner(Deps(llm=FakeLLM({}), weather=FakeWeather(), today=lambda: date(2026, 10, 1)))
    monkeypatch.setattr(planner_gateway, "planner", runner)
    return runner


@pytest.fixture()
def client():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with TestClient(app) as c:  # context manager runs lifespan → binds hub loop
        yield c


def make_user(client, name="Rahul Mehta", email="rahul@example.com", password="goa-trip-2026"):
    r = client.post("/api/auth/register", json={"name": name, "email": email, "password": password})
    assert r.status_code == 201, r.text
    body = r.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, body["user"], body["access_token"]


GOA = {"name": "Goa with the gang", "destination": "Goa", "start_date": "2026-12-10",
       "end_date": "2026-12-14", "group_budget": "60000"}


@contextmanager
def open_ws(client, trip_id, token):
    """Connect and wait for the server's "ready", the point after which no event can be missed."""
    with client.websocket_connect(f"/ws/trips/{trip_id}?token={token}") as ws:
        assert ws.receive_json()["type"] == "ready"
        yield ws
