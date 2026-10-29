import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, chat, destinations, planning, telegram as telegram_api, trip_extras, trips, ws
from app.core.config import get_settings
from app.core.errors import install_error_handlers
from app.services.event_hub import hub


@asynccontextmanager
async def lifespan(_: FastAPI):
    hub.bind_loop(asyncio.get_running_loop())
    poller = None
    s = get_settings()
    if s.telegram_bot_token and s.telegram_mode != "off":
        from app.telegram import notifier, polling
        hub.subscribe(notifier.on_event)
        if s.telegram_mode == "polling":
            poller = asyncio.create_task(polling.poll_forever())
    yield
    if poller:
        poller.cancel()


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title=s.app_name, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware, allow_origins=s.cors_origin_list, allow_credentials=True,
        allow_methods=["*"], allow_headers=["*"],
    )
    install_error_handlers(app)
    for r in (auth.router, destinations.router, trips.router, chat.router, planning.router, trip_extras.router, telegram_api.router, ws.router):
        app.include_router(r)

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    return app


app = create_app()
