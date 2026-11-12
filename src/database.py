"""Connection management for the retail_db Postgres database."""

import logging
import os

import psycopg
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError

logger = logging.getLogger(__name__)

load_dotenv()


def get_connection_url() -> str:
    """Build the retail_db connection string from environment variables.

    Reads POSTGRES_HOST/PORT/DB/USER/PASSWORD rather than taking a
    connection string directly, so a password typo fails fast with a
    clear env var name instead of a parse error on a hand-built URL.
    """
    required = ["POSTGRES_HOST", "POSTGRES_PORT", "POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD"]
    missing = [var for var in required if not os.environ.get(var)]
    if missing:
        raise RuntimeError(
            f"Missing required environment variable(s): {', '.join(missing)}. "
            "Copy .env.example to .env and fill in real values."
        )

    user = os.environ["POSTGRES_USER"]
    password = os.environ["POSTGRES_PASSWORD"]
    host = os.environ["POSTGRES_HOST"]
    port = os.environ["POSTGRES_PORT"]
    db = os.environ["POSTGRES_DB"]
    return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{db}"


_engine: Engine | None = None


def get_engine() -> Engine:
    """Return a process-wide SQLAlchemy engine, creating it on first use."""
    global _engine
    if _engine is None:
        _engine = create_engine(get_connection_url(), pool_pre_ping=True)
    return _engine


def get_raw_connection() -> psycopg.Connection:
    """A plain psycopg connection, bypassing SQLAlchemy's pooling — used
    only where SQLAlchemy Core can't express the operation directly, e.g.
    the server-side COPY used for bulk-loading the staging table.
    """
    return psycopg.connect(
        host=os.environ["POSTGRES_HOST"],
        port=os.environ["POSTGRES_PORT"],
        dbname=os.environ["POSTGRES_DB"],
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
    )


def check_connection() -> bool:
    """Verify the database is reachable; used by the DAG before real work starts."""
    try:
        with get_engine().connect() as conn:
            conn.exec_driver_sql("SELECT 1")
        return True
    except OperationalError:
        logger.exception("Could not connect to retail_db")
        return False
