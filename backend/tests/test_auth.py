from tests.conftest import make_user


def test_register_login_me(client):
    headers, user, _ = make_user(client)
    assert client.get("/api/auth/me", headers=headers).json()["email"] == "rahul@example.com"
    r = client.post("/api/auth/login", json={"email": "RAHUL@example.com", "password": "goa-trip-2026"})
    assert r.status_code == 200 and r.json()["user"]["id"] == user["id"]


def test_duplicate_email_rejected(client):
    make_user(client)
    r = client.post("/api/auth/register", json={"name": "X", "email": "rahul@example.com", "password": "password123"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "email_taken"


def test_wrong_password_is_generic(client):
    make_user(client)
    r = client.post("/api/auth/login", json={"email": "rahul@example.com", "password": "nope-nope"})
    assert r.status_code == 401
    r2 = client.post("/api/auth/login", json={"email": "ghost@example.com", "password": "nope-nope"})
    assert r.json()["error"]["message"] == r2.json()["error"]["message"]


def test_short_password_validation_envelope(client):
    r = client.post("/api/auth/register", json={"name": "A", "email": "a@b.co", "password": "short"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_input"


def test_password_is_hashed(client):
    from app.core.database import SessionLocal
    from app.models import User
    make_user(client)
    with SessionLocal() as db:
        assert db.query(User).one().password_hash.startswith("$2")


def test_protected_routes_need_token(client):
    assert client.get("/api/trips").status_code == 401
    assert client.get("/api/trips", headers={"Authorization": "Bearer garbage"}).status_code == 401
