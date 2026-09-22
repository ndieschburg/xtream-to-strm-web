"""
Plex sync state model for tracking synchronization status.

Similar to SyncState for Xtream subscriptions.
"""
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from datetime import datetime
from app.db.base_class import Base


class PlexSyncState(Base):
    """
    Tracks sync status for Plex servers.

    @description One record per server per type (movies/series).
    Used to display sync progress and history.
    """
    __tablename__ = "plex_sync_state"

    id = Column(Integer, primary_key=True, index=True)
    server_id = Column(Integer, ForeignKey("plex_servers.id", ondelete="CASCADE"), nullable=False, index=True)
    type = Column(String, nullable=False)  # "movies" or "series"
    last_sync = Column(DateTime, nullable=True)
    status = Column(String, nullable=False, default="idle")  # idle, running, success, failed
    # Unit is the STRM file: movies for a "movies" sync, episodes for a "series" sync
    items_added = Column(Integer, nullable=False, default=0)
    items_deleted = Column(Integer, nullable=False, default=0)
    files_written = Column(Integer, nullable=False, default=0)  # STRM files actually written
    error_message = Column(String, nullable=True)
    task_id = Column(String, nullable=True)  # Celery task ID for cancellation
