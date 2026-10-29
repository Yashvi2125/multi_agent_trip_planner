"""Drives the real graph against a real (SQLite) database, bypassing the HTTP stub planner."""
from datetime import date

from app.core.database import SessionLocal
from app.graph.builder import GraphDeps
from app.models import AIAction, Message, SenderType, Trip
from app.services.planner_gateway import GraphPlanner
from tests.conftest import GOA, make_user
from tests.test_tools import FakeWeather


class Harness:
    def __init__(self, client, llm, members=("Rahul Mehta", "Priya Shah"), trip=None, weather=None):
        self.client, self.llm = client, llm
        self.users, self.headers = [], []
        for i, name in enumerate(members):
            h, u, _ = make_user(client, name, f"user{i}@example.com")
            self.users.append(u), self.headers.append(h)
        t = client.post("/api/trips", json=trip or GOA, headers=self.headers[0]).json()
        self.trip_id, self.code = t["id"], t["code"]
        for h in self.headers[1:]:
            client.post("/api/trips/join", json={"code": self.code}, headers=h)
        deps = GraphDeps(llm=llm, weather=weather or FakeWeather(), session_factory=lambda: SessionLocal(),
                         today=lambda: date(2026, 10, 1))
        self.planner = GraphPlanner(deps)

    def say(self, who: int, text: str) -> list[str]:
        """Post as member `who`, run the planner, return only the NEW AI messages."""
        with SessionLocal() as db:
            before = db.query(Message).filter_by(trip_id=self.trip_id, sender_type=SenderType.ai).count()
            m = Message(trip_id=self.trip_id, sender_user_id=self.users[who]["id"], text=text)
            db.add(m)
            db.commit()
            mid = m.id
        self.planner.handle(self.trip_id, mid)
        with SessionLocal() as db:
            rows = db.query(Message).filter_by(trip_id=self.trip_id, sender_type=SenderType.ai).order_by(Message.id).all()
            return [r.text for r in rows[before:]]

    def trip(self) -> Trip:
        with SessionLocal() as db:
            return db.get(Trip, self.trip_id)

    def versions(self):
        from app.models import ItineraryVersion
        with SessionLocal() as db:
            return db.query(ItineraryVersion).filter_by(trip_id=self.trip_id).order_by(ItineraryVersion.version).all()

    def actions(self):
        with SessionLocal() as db:
            return db.query(AIAction).filter_by(trip_id=self.trip_id).all()
