"""The seam between chat and the AI. Routes call `planner.handle(...)`; tests swap `planner` for a
runner wired to fakes."""
from typing import Protocol

from app.agents.router import addressed_to_planner  # noqa: F401  (re-exported for adapters)
from app.services.planner_runner import PlannerRunner


class Planner(Protocol):
    def handle(self, trip_id: int, message_id: int, command: str | None = None) -> None: ...


planner: Planner = PlannerRunner()
