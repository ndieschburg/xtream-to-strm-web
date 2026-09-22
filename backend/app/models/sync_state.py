from sqlalchemy import Column, String, Integer, DateTime, Enum
import enum
from datetime import datetime
from app.db.base_class import Base

class SyncStatus(str, enum.Enum):
    IDLE = "idle"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"

class SyncType(str, enum.Enum):
    MOVIES = "movies"
    SERIES = "series"

class SyncState(Base):
    __tablename__ = "sync_state"

    id = Column(Integer, primary_key=True, index=True)
    subscription_id = Column(Integer, nullable=False, index=True)
    type = Column(String, nullable=False)  # movies or series
    last_sync = Column(DateTime, nullable=True)
    status = Column(String, nullable=False, default=SyncStatus.IDLE)
    # Unit is the STRM file: movies for a "movies" sync, episodes for a "series" sync
    items_added = Column(Integer, nullable=False, default=0)
    items_deleted = Column(Integer, nullable=False, default=0)
    files_written = Column(Integer, nullable=False, default=0)  # STRM files actually written
    error_message = Column(String, nullable=True)
    task_id = Column(String, nullable=True)  # Celery task ID for cancellation
