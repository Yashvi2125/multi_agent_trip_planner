import hmac
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, Request

from app.api.deps import current_user
from app.core.config import get_settings
from app.core.errors import AppError
from app.models import User
from app.services import planner_gateway, telegram_link
from app.telegram import handlers, service

router = APIRouter(prefix="/api/telegram", tags=["telegram"])
log = logging.getLogger("wayfare.telegram")


@router.get("/status")
def status():
    s = get_settings()
    return {"configured": service.get_client() is not None, "bot_username": s.telegram_bot_username or None,
            "mode": s.telegram_mode}


@router.post("/link-code")
def link_code(user: User = Depends(current_user)):
    if service.get_client() is None:
        raise AppError("telegram_off", "The Telegram bot isn't switched on for this server yet.", 503)
    return {"code": telegram_link.create_code(user.id), "expires_in_seconds": telegram_link.TTL_SECONDS,
            "bot_username": get_settings().telegram_bot_username or None}


@router.post("/webhook")
async def webhook(request: Request, bg: BackgroundTasks):
    s = get_settings()
    if service.get_client() is None:
        raise AppError("telegram_off", "The Telegram bot isn't switched on for this server.", 503)
    if s.telegram_webhook_secret:
        if not hmac.compare_digest(request.headers.get("x-telegram-bot-api-secret-token", ""),
                                   s.telegram_webhook_secret):
            raise AppError("forbidden", "Bad webhook secret.", 403)
    elif s.environment != "development":
        # Without a secret anyone who finds the URL could forge updates and post as any Telegram user.
        raise AppError("forbidden", "The webhook secret isn't configured on this server.", 403)
    try:
        update = await request.json()
    except ValueError:
        return {"ok": True}
    try:
        from starlette.concurrency import run_in_threadpool
        await run_in_threadpool(handlers.process_update, update,
                                lambda t, m, c: bg.add_task(planner_gateway.planner.handle, t, m, c))
    except Exception:
        log.exception("Telegram update failed")      # always 200, or Telegram retries the same update forever
    return {"ok": True}
