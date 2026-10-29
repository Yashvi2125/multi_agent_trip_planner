import logging

from langgraph.checkpoint.memory import MemorySaver

from app.core.config import get_settings

log = logging.getLogger("wayfare.graph")
_memory = MemorySaver()
_postgres = None


def get_checkpointer():
    """thread_id = trip id, so each trip has its own resumable history of graph runs.
    The DB stays the source of truth for trip data; checkpoints give inspectable run history."""
    global _postgres
    s = get_settings()
    if s.checkpointer == "postgres" and s.database_url.startswith("postgresql"):
        if _postgres is None:
            try:  # needs langgraph-checkpoint-postgres; connection must be autocommit + dict rows
                import psycopg
                from langgraph.checkpoint.postgres import PostgresSaver
                from psycopg.rows import dict_row
                conn = psycopg.connect(s.database_url.replace("+psycopg", ""), autocommit=True, row_factory=dict_row)
                _postgres = PostgresSaver(conn)
                _postgres.setup()
            except Exception:
                log.exception("Postgres checkpointer unavailable; falling back to in-memory")
                return _memory
        return _postgres
    return _memory
