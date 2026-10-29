from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings

_url = get_settings().database_url
_kwargs: dict = {"pool_pre_ping": True}
if _url.startswith("sqlite"):
    _kwargs = {"connect_args": {"check_same_thread": False}}
    if _url in ("sqlite://", "sqlite:///:memory:"):
        _kwargs["poolclass"] = StaticPool

engine = create_engine(_url, **_kwargs)

if _url.startswith("sqlite") and _url not in ("sqlite://", "sqlite:///:memory:"):
    @event.listens_for(engine, "connect")
    def _sqlite_concurrency(dbapi_conn, _):
        """Request threads, the planner and the Telegram notifier all write. WAL lets readers and a writer
        coexist, and the timeout makes a briefly-locked write wait instead of failing."""
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=15000")
        cur.close()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
