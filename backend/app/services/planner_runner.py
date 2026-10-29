"""Executes the LangGraph for one inbound message and fans results out through the hub.
Channel-agnostic: Telegram and web both arrive here via `handle(trip_id, message_id)`."""
import logging
import threading
from collections import defaultdict
from datetime import datetime, timezone

from app.agents.router import addressed_to_planner
from app.core import database
from app.graph.builder import RunContext, build_graph
from app.graph.checkpointer import get_checkpointer
from app.graph.deps import Deps, default_deps
from app.graph.state import initial_state
from app.models import AIAction, Channel, Message, SenderType, Trip
from app.schemas.trip import MessageOut
from app.services.event_hub import hub

log = logging.getLogger("wayfare.planner")

FRIENDLY_FAILURE = "I hit a snag while working on that. Nothing was lost, so please try again in a moment."


class PlannerRunner:
    def __init__(self, deps: Deps | None = None):
        self._deps = deps
        self._locks: dict[int, threading.Lock] = defaultdict(threading.Lock)

    @property
    def deps(self) -> Deps:
        if self._deps is None:
            self._deps = default_deps()
        return self._deps

    def handle(self, trip_id: int, message_id: int, command: str | None = None) -> None:
        # One graph run per trip at a time: four people typing must not interleave writes.
        with self._locks[trip_id]:
            try:
                self._run(trip_id, message_id, command)
            except Exception:
                log.exception("Planner run crashed (trip=%s message=%s)", trip_id, message_id)

    def _run(self, trip_id: int, message_id: int, command: str | None) -> None:
        with database.SessionLocal() as db:
            msg = db.get(Message, message_id)
            trip = db.get(Trip, trip_id)
            if not msg or not trip or msg.sender_type is not SenderType.user:
                return  # never react to the AI's own or system messages
            parent = db.get(Message, msg.reply_to_id) if msg.reply_to_id else None
            addressed = addressed_to_planner(msg.text, bool(parent and parent.sender_type is SenderType.ai)) or bool(command)

            action = AIAction(trip_id=trip_id, trigger_message_id=message_id, status="running")
            db.add(action)
            db.commit()

            sent_status = False

            def status(text: str) -> None:
                nonlocal sent_status
                sent_status = True
                hub.publish_threadsafe(trip_id, {"type": "ai.status", "data": {"text": text}})

            ctx = RunContext(db=db, deps=self.deps, trip=trip, action_id=action.id, status=status)
            sender = msg.sender
            state = initial_state(trip_id, message_id, msg.sender_user_id or 0, sender.name if sender else "",
                                  msg.text, addressed, command)
            try:
                graph = build_graph(ctx, get_checkpointer())
                final = graph.invoke(state, {"configurable": {"thread_id": str(trip_id)}})
            except Exception as e:
                db.rollback()
                log.exception("Graph failed")
                action.status, action.error = "failed", type(e).__name__
                action.finished_at = datetime.now(timezone.utc)
                db.commit()
                if sent_status:
                    hub.publish_threadsafe(trip_id, {"type": "ai.status", "data": {"text": None}})
                if addressed:  # don't spam the group about silent background failures
                    self._say(db, trip_id, message_id, FRIENDLY_FAILURE, {"error": True})
                return

            for out in final["outbox"]:
                self._say(db, trip_id, message_id, out["text"], out.get("meta") or {})
            for ev in final["events"]:
                hub.publish_threadsafe(trip_id, ev)
            if sent_status:
                hub.publish_threadsafe(trip_id, {"type": "ai.status", "data": {"text": None}})

            action.intent = final["intent"]
            action.agents_run = ["router", "explainer"] if final["intent"] == "explain" else [
                "preference", "conflict"] + (["research", "itinerary", "budget", "validator"] if final["plan_request"] else [])
            action.reasoning = {k: final[k] for k in (
                "added_prefs", "added_constraints", "changed_mind", "trimmed", "dropped", "loop_count", "notes",
                "violations", "warnings", "coverage", "used_fallback", "extract_failed", "blocked", "version")}
            action.status = "ok"
            action.finished_at = datetime.now(timezone.utc)
            db.commit()

    @staticmethod
    def _say(db, trip_id: int, reply_to: int, text: str, meta: dict) -> None:
        m = Message(trip_id=trip_id, sender_type=SenderType.ai, source=Channel.system, text=text,
                    reply_to_id=reply_to, meta=meta or None)
        db.add(m)
        db.commit()
        hub.publish_threadsafe(trip_id, {"type": "message.new", "data": MessageOut.model_validate(m).model_dump(mode="json")})
