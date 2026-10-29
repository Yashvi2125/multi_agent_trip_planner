from tests.conftest import GOA, make_user, open_ws


def _trip(client):
    h, u, tok = make_user(client)
    t = client.post("/api/trips", json=GOA, headers=h).json()
    return h, tok, t


def test_send_and_history(client):
    h, _, t = _trip(client)
    r = client.post(f"/api/trips/{t['id']}/messages", json={"text": "I want beaches"}, headers=h)
    assert r.status_code == 202 and r.json()["source"] == "web" and r.json()["sender"]["name"] == "Rahul Mehta"
    msgs = client.get(f"/api/trips/{t['id']}/messages", headers=h).json()
    assert [m["text"] for m in msgs] == ["I want beaches"]


def test_empty_message_rejected(client):
    h, _, t = _trip(client)
    assert client.post(f"/api/trips/{t['id']}/messages", json={"text": "   "}, headers=h).status_code == 422


def test_ai_silent_unless_addressed_then_replies(client):
    h, _, t = _trip(client)
    client.post(f"/api/trips/{t['id']}/messages", json={"text": "we like nightlife"}, headers=h)
    assert len(client.get(f"/api/trips/{t['id']}/messages", headers=h).json()) == 1
    client.post(f"/api/trips/{t['id']}/messages", json={"text": "@planner you there?"}, headers=h)
    msgs = client.get(f"/api/trips/{t['id']}/messages", headers=h).json()
    assert [m["sender_type"] for m in msgs] == ["user", "user", "ai"]


def test_websocket_rejects_bad_token_and_non_members(client):
    import pytest
    from starlette.websockets import WebSocketDisconnect
    _, _, t = _trip(client)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/ws/trips/{t['id']}?token=bad"):
            pass
    _, _, other_tok = make_user(client, "Outsider", "out@example.com")
    with pytest.raises(WebSocketDisconnect):
        with open_ws(client, t['id'], other_tok):
            pass


def test_realtime_fanout_across_members(client):
    h1, tok1, t = _trip(client)
    h2, _, tok2 = make_user(client, "Aman Verma", "aman@example.com")
    client.post("/api/trips/join", json={"code": t["code"]}, headers=h2)
    with open_ws(client, t['id'], tok2) as ws:
        client.post(f"/api/trips/{t['id']}/messages", json={"text": "Dudhsagar?"}, headers=h1)
        evt = ws.receive_json()
        assert evt["type"] == "message.new" and evt["data"]["text"] == "Dudhsagar?"


def test_join_broadcasts_member_joined(client):
    h1, tok1, t = _trip(client)
    h2, *_ = make_user(client, "Neha Rao", "neha@example.com")
    with open_ws(client, t['id'], tok1) as ws:
        client.post("/api/trips/join", json={"code": t["code"]}, headers=h2)
        assert ws.receive_json()["type"] == "member.joined"
        assert "Neha Rao joined" in ws.receive_json()["data"]["text"]


def test_unhandled_error_hides_stack_trace(client, monkeypatch):
    from app.services import trip_service
    monkeypatch.setattr(trip_service, "list_user_trips", lambda *a: 1 / 0)
    h, *_ = make_user(client)
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app, raise_server_exceptions=False) as quiet:
        r = quiet.get("/api/trips", headers=h)
    assert r.status_code == 500 and "ZeroDivision" not in r.text
    assert r.json()["error"]["code"] == "server_error"
