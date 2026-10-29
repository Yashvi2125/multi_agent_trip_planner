"""Bali through the real stack (HTTP → planner graph → database), and the guarantees around it:
the other destinations still work, and unsupported ones get a helpful answer and save nothing."""
import json
from decimal import Decimal

import pytest

from app.core.database import SessionLocal
from app.models import ItineraryVersion, Trip
from app.tools.curated import DATA_DIR
from tests.conftest import GOA, make_user

PLAN_REQUEST = "@planner make the itinerary"


def place_ids_of(dest_id: str) -> set[str]:
    return {p["id"] for p in json.loads((DATA_DIR / f"{dest_id}.json").read_text(encoding="utf-8"))["places"]}


class World:
    def __init__(self, client, destination: str, **trip_overrides):
        self.client = client
        self.h, *_ = make_user(client, "Rahul Mehta", "rahul@example.com")
        self.h2, *_ = make_user(client, "Priya Shah", "priya@example.com")
        body = {**GOA, "name": f"{destination} trip", "destination": destination, "group_budget": "150000", **trip_overrides}
        r = client.post("/api/trips", json=body, headers=self.h)
        assert r.status_code == 201, r.text
        self.trip = r.json()
        client.post("/api/trips/join", json={"code": self.trip["code"]}, headers=self.h2)

    def get(self, path: str):
        return self.client.get(f"/api/trips/{self.trip['id']}/{path}", headers=self.h)

    def ask_for_plan(self):
        r = self.client.post(f"/api/trips/{self.trip['id']}/messages", json={"text": PLAN_REQUEST}, headers=self.h)
        assert r.status_code == 202
        return [m["text"] for m in self.get("messages").json() if m["sender_type"] == "ai"]

    def saved_versions(self) -> int:
        with SessionLocal() as db:
            return db.query(ItineraryVersion).filter_by(trip_id=self.trip["id"]).count()

    def trip_row_version(self) -> int:
        with SessionLocal() as db:
            return db.get(Trip, self.trip["id"]).current_itinerary_version


# ---------- 1 + 2: Bali generates a plan and it is saved ----------

def test_bali_generates_a_plan_that_is_saved_in_the_database(client):
    w = World(client, "Bali")
    ai = w.ask_for_plan()
    assert any("version 1 of the Bali plan" in t for t in ai), ai

    r = w.get("itinerary")
    assert r.status_code == 200
    body = r.json()
    assert body["version"] == 1 and body["itinerary"]["destination"] == "Bali"
    days = body["itinerary"]["days"]
    assert len(days) == 5 and all(d["items"] for d in days)

    placed = [i["place_id"] for d in days for i in d["items"]]
    assert placed and set(placed) <= place_ids_of("bali")          # every stop is a verified Bali place
    assert len(set(placed)) == len(placed)

    assert w.saved_versions() == 1 and w.trip_row_version() == 1   # persisted, and the trip points at it
    assert w.client.get(f"/api/trips/{w.trip['id']}/itinerary/versions", headers=w.h).json()[0]["version"] == 1


def test_bali_plan_respects_real_constraints(client):
    w = World(client, "Bali")
    w.ask_for_plan()
    it = w.get("itinerary").json()["itinerary"]
    assert it["days"][0]["items"][0]["start"] >= "12:00"           # day 1 starts at arrival
    nusa_day = next((d["index"] for d in it["days"] for i in d["items"] if i["place_id"] == "nusa_penida"), None)
    assert nusa_day != 1                                           # an 8-hour island trip can't start after noon
    stay = it["stay"]
    assert stay["nights"] == 4 and stay["nightly_per_room"] > 0 and stay["rooms"] == 1
    assert "stays in" in stay["why"]


def test_bali_peak_season_is_reflected_in_what_the_group_is_told(client):
    ai = World(client, "Bali").ask_for_plan()
    plan = next(t for t in ai if "version 1" in t)
    assert "peak season in Bali" in plan                           # December is peak season in the data


# ---------- 4: budget works ----------

def test_bali_budget_is_estimated_from_bali_data(client):
    w = World(client, "Bali")
    w.ask_for_plan()
    r = w.get("budget")
    assert r.status_code == 200
    b = r.json()
    assert b["travelers"] == 2 and Decimal(b["cap"]) == 150000
    assert Decimal(b["total"]) > 0 and Decimal(b["per_person"]) > 0
    assert abs(Decimal(b["total"]) / 2 - Decimal(b["per_person"])) <= 1
    assert {"accommodation", "food", "transport", "activities"} <= set(b["by_category"])
    assert Decimal(b["by_category"]["accommodation"]) > 0
    assert b["status"] in {"within", "tight", "over"}


def test_bali_budget_is_checked_against_a_tight_limit(client):
    w = World(client, "Bali", group_budget="20000")
    ai = w.ask_for_plan()
    b = w.get("budget").json()
    assert b["status"] == "over" and Decimal(b["over_by"]) > 0
    plan = next(t for t in ai if "version 1" in t)
    assert "over your ₹20,000 budget" in plan                      # said plainly, plan still saved
    assert w.saved_versions() == 1


# ---------- the other destinations still work ----------

@pytest.mark.parametrize("destination,dest_id", [("Goa", "goa"), ("Jaipur", "jaipur"), ("Manali", "manali"), ("Bali", "bali")])
def test_every_supported_destination_still_plans_and_saves(client, destination, dest_id):
    w = World(client, destination)
    w.ask_for_plan()
    body = w.get("itinerary").json()
    placed = [i["place_id"] for d in body["itinerary"]["days"] for i in d["items"]]
    assert placed and set(placed) <= place_ids_of(dest_id)         # never mixes in another destination's places
    assert w.saved_versions() == 1
    assert w.get("budget").status_code == 200


def test_destinations_endpoint_lists_bali_for_the_frontend(client):
    r = client.get("/api/destinations")
    assert r.status_code == 200
    by_name = {d["name"]: d for d in r.json()}
    assert {"Bali", "Goa", "Jaipur", "Manali"} <= set(by_name)
    assert by_name["Bali"]["country"] == "Indonesia" and by_name["Bali"]["places"] == 18
    assert by_name["Bali"]["highlights"] and by_name["Bali"]["dry_months"]


@pytest.mark.parametrize("spelling", ["bali", "BALI", "  Bali  ", "Bali, Indonesia", "Ubud"])
def test_bali_is_recognised_however_it_is_typed(client, spelling):
    w = World(client, spelling)
    ai = w.ask_for_plan()
    assert any("of the Bali plan" in t for t in ai), (spelling, ai)


# ---------- 5: unsupported destinations get a helpful answer and nothing is saved ----------

def test_unsupported_destination_gets_a_helpful_message_and_saves_nothing(client):
    w = World(client, "Lisbon")
    ai = w.ask_for_plan()
    assert len(ai) == 1
    msg = ai[0]
    assert "Bali, Goa, Jaipur, Manali" in msg                      # the supported list is generated from the data
    assert "Lisbon" in msg and "Settings" in msg                   # says what's missing and what to do
    assert "preferences stay saved" in msg
    assert w.get("itinerary").status_code == 404
    assert w.saved_versions() == 0 and w.trip_row_version() == 0


# ---------- the exact path the UI's "Build the first plan" button takes (POST /regenerate) ----------

def test_the_build_first_plan_button_works_for_bali(client):
    w = World(client, "Bali")
    assert w.get("itinerary").status_code == 404                   # nothing yet: the empty state with the button
    r = client.post(f"/api/trips/{w.trip['id']}/regenerate", headers=w.h)
    assert r.status_code == 202
    body = w.get("itinerary").json()
    assert body["version"] == 1 and body["itinerary"]["destination"] == "Bali" and w.saved_versions() == 1
    assert w.get("budget").status_code == 200


def test_the_build_first_plan_button_on_an_unsupported_destination_explains_and_saves_nothing(client):
    w = World(client, "Lisbon")
    assert client.post(f"/api/trips/{w.trip['id']}/regenerate", headers=w.h).status_code == 202
    ai = [m["text"] for m in w.get("messages").json() if m["sender_type"] == "ai"]
    assert len(ai) == 1 and "Bali, Goa, Jaipur, Manali" in ai[0] and "Settings" in ai[0]
    assert w.get("itinerary").status_code == 404 and w.saved_versions() == 0
