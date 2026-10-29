"""Long-polling for local development (no public URL needed). Runs inside the API process so it shares
the in-memory event hub with the WebSocket clients. Use webhooks in production."""
import asyncio
import logging
import threading

from app.telegram import handlers, service

log = logging.getLogger("wayfare.telegram")


def run_planner_in_thread(trip_id: int, message_id: int, command: str | None) -> None:
    from app.services import planner_gateway
    threading.Thread(target=planner_gateway.planner.handle, args=(trip_id, message_id, command), daemon=True).start()


async def poll_forever() -> None:
    c = service.get_client()
    if c is None:
        return
    offset = None
    while True:
        try:
            updates = await asyncio.to_thread(c.get_updates, offset, 25)
            for u in updates:
                offset = u["update_id"] + 1
                try:
                    await asyncio.to_thread(handlers.process_update, u, run_planner_in_thread)
                except Exception:
                    log.exception("Telegram update failed")
        except asyncio.CancelledError:
            raise
        except Exception:
            log.warning("Telegram polling error; retrying shortly")
            await asyncio.sleep(3)
