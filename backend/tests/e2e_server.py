"""Live server for the frontend end-to-end tests (not collected by pytest).

REAL: FastAPI, the database, WebSockets, the LangGraph planner, and the Telegram client making real HTTP calls.
FAKED: the LLM and the weather service (same fakes as the backend suite), and Telegram's own servers,
which are a tiny local recorder so the tests can see exactly what the bot sent."""
import argparse
import json
import os
import sys
import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]

TABLE = {   # what the fake LLM "extracts" from each known message
    "I'd love nightlife and beaches!": {"preferences": [
        {"category": "interest", "topic": "nightlife", "weight": 5}, {"category": "interest", "topic": "beaches", "weight": 4}]},
    "I'm not into nightlife, I'd rather relax": {"preferences": [
        {"category": "dislike", "topic": "nightlife", "weight": 4}, {"category": "interest", "topic": "relaxation", "weight": 4}]},
    "Can we add Dudhsagar?": {"preferences": [
        {"category": "interest", "topic": "Dudhsagar Falls", "weight": 5}, {"category": "interest", "topic": "adventure", "weight": 4}]},
    "I can't spend more than ₹12,000": {"constraints": [{"type": "max_budget", "amount": "12000"}]},
}


class FakeTelegram(BaseHTTPRequestHandler):
    calls: list[dict] = []
    lock = threading.Lock()

    def log_message(self, *a):  # keep test output quiet
        pass

    def _send(self, obj):
        data = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        with self.lock:
            self._send(list(self.calls)) if self.path == "/__calls" else self._send({"ok": False})

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}"
        if self.path == "/__reset":
            with self.lock:
                self.calls.clear()
            return self._send({"ok": True})
        method = self.path.rsplit("/", 1)[-1]
        with self.lock:
            self.calls.append({"method": method, "body": json.loads(body)})
            n = len(self.calls)
        self._send({"ok": True, "result": {"message_id": n} if method == "sendMessage" else True})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--tg-port", type=int, required=True)
    ap.add_argument("--db", required=True)
    a = ap.parse_args()
    os.environ.update(
        DATABASE_URL=f"sqlite:///{a.db}", RATE_LIMIT_ENABLED="false", JWT_SECRET="e2e-only-secret-not-for-production",
        BCRYPT_ROUNDS="4", CORS_ORIGINS="*", TELEGRAM_BOT_TOKEN="424242:E2E", TELEGRAM_MODE="webhook",
        TELEGRAM_BOT_USERNAME="WayfareE2EBot", TELEGRAM_WEBHOOK_SECRET="e2e-webhook-secret",
        TELEGRAM_API_BASE=f"http://127.0.0.1:{a.tg_port}", PUBLIC_WEB_URL="http://localhost:5173")
    sys.path.insert(0, str(BACKEND))

    tg = ThreadingHTTPServer(("127.0.0.1", a.tg_port), FakeTelegram)
    threading.Thread(target=tg.serve_forever, daemon=True).start()

    from app.core.database import Base, engine
    import app.models  # noqa: F401
    Base.metadata.create_all(engine)

    from app.graph.deps import Deps
    from app.services import planner_gateway
    from app.services.planner_runner import PlannerRunner
    from tests.dynamic_fakes import FakeGeo, LocationAwarePlaces, ResearchLLM, make_researcher
    from tests.fakes import FakeWeather
    llm = ResearchLLM(TABLE)
    researcher, geo, *_ = make_researcher(FakeGeo(), LocationAwarePlaces(), llm=llm)   # fake providers: no network
    planner_gateway.planner = PlannerRunner(Deps(llm=llm, weather=FakeWeather(), geocoder=geo,
                                                 today=lambda: date(2026, 10, 1), dynamic=researcher))

    import uvicorn
    from app.main import app
    uvicorn.run(app, host="127.0.0.1", port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
