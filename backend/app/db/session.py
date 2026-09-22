from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from typing import Generator
from app.core.config import settings

engine = create_engine(
    settings.DATABASE_URL,
    # busy_timeout: the API, the Celery worker and beat all write to the same
    # file. Without it, a concurrent writer fails instantly with
    # "database is locked" instead of waiting for the lock.
    connect_args={"check_same_thread": False, "timeout": 30},  # SQLite specific
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, connection_record):
    """Enable WAL so readers (API) don't block on writers (sync tasks)."""
    if not settings.DATABASE_URL.startswith("sqlite"):
        return
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=30000")
    finally:
        cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator:
    """Dependency for FastAPI endpoints to get a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
