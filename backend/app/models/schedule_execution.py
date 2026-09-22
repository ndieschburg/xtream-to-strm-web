from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Enum as SQLEnum
from sqlalchemy.sql import func
from app.db.base_class import Base
import enum

class ExecutionStatus(str, enum.Enum):
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RUNNING = "running"
    INTERRUPTED = "interrupted"

class ScheduleExecution(Base):
    __tablename__ = "schedule_executions"

    id = Column(Integer, primary_key=True, index=True)
    schedule_id = Column(Integer, ForeignKey("schedules.id"), nullable=True)  # Nullable for manual syncs
    subscription_id = Column(Integer, nullable=True)  # Direct reference for manual syncs
    sync_type = Column(String, nullable=True)  # "movies" or "series" for manual syncs
    started_at = Column(DateTime, server_default=func.now(), nullable=False)
    completed_at = Column(DateTime, nullable=True)
    status = Column(SQLEnum(ExecutionStatus), nullable=False, default=ExecutionStatus.RUNNING)
    items_processed = Column(Integer, default=0)  # Kept for backward compatibility: added + deleted
    # Unit is the STRM file: movies for a "movies" sync, episodes for a "series" sync
    items_added = Column(Integer, default=0)
    items_deleted = Column(Integer, default=0)
    files_written = Column(Integer, default=0)  # STRM files actually written to disk
    error_message = Column(Text, nullable=True)
