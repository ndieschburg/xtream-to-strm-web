"""
Unified sync history endpoint.

Aggregates execution history from all sync sources:
- Xtream (ScheduleExecution)
- Plex (PlexScheduleExecution)
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime
from app.db.session import get_db
from app.models.schedule import Schedule
from app.models.schedule_execution import ScheduleExecution
from app.models.plex_schedule import PlexSchedule
from app.models.plex_schedule_execution import PlexScheduleExecution
from app.models.subscription import Subscription
from app.models.plex_server import PlexServer

router = APIRouter()


class SyncHistoryItem(BaseModel):
    id: str  # Prefixed ID to avoid collisions (e.g., "xtream_123", "plex_456")
    source_type: str  # "xtream" or "plex"
    source_name: str
    sync_type: str  # "movies" or "series"
    started_at: datetime
    completed_at: Optional[datetime]
    duration_seconds: Optional[int]
    status: str
    items_added: int
    items_deleted: int
    items_total: int
    files_written: int  # STRM files actually written to disk
    item_unit: str  # What items_* counts: "movies", "episodes" or "items"
    has_details: bool  # False for executions recorded before the split counters
    error_message: Optional[str]

    class Config:
        from_attributes = True


def _item_unit(sync_type: Optional[str]) -> str:
    """One STRM file per movie, per episode for a series sync"""
    if sync_type == "movies":
        return "movies"
    if sync_type == "series":
        return "episodes"
    return "items"


def _counters(exec_row) -> dict:
    """
    Read the counters of an execution.

    Executions recorded before the split counters only have items_processed,
    which lumped additions and deletions together.
    """
    added = exec_row.items_added or 0
    deleted = exec_row.items_deleted or 0
    has_details = bool(added or deleted or exec_row.files_written)

    return {
        "items_added": added,
        "items_deleted": deleted,
        "items_total": (added + deleted) if has_details else (exec_row.items_processed or 0),
        "files_written": exec_row.files_written or 0,
        "has_details": has_details,
    }


@router.get("/", response_model=List[SyncHistoryItem])
async def get_sync_history(
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0),
    source_type: Optional[str] = Query(None, description="Filter by source type: xtream, plex"),
    sync_type: Optional[str] = Query(None, description="Filter by sync type: movies, series"),
    db: Session = Depends(get_db)
):
    """Get unified sync execution history from all sources"""

    history_items: List[SyncHistoryItem] = []

    # Xtream executions
    if source_type is None or source_type == "xtream":
        # Query all executions (both scheduled and manual)
        xtream_executions = db.query(ScheduleExecution).order_by(
            ScheduleExecution.started_at.desc()
        ).all()

        for exec_row in xtream_executions:
            # Get subscription name - from schedule or direct subscription_id
            subscription_name = "Unknown"
            exec_sync_type = exec_row.sync_type

            if exec_row.schedule_id:
                # Scheduled sync - get info from schedule
                schedule = db.query(Schedule).filter(Schedule.id == exec_row.schedule_id).first()
                if schedule:
                    subscription = db.query(Subscription).filter(Subscription.id == schedule.subscription_id).first()
                    if subscription:
                        subscription_name = subscription.name
                    exec_sync_type = schedule.type.value if hasattr(schedule.type, 'value') else str(schedule.type)
            elif exec_row.subscription_id:
                # Manual sync - get info from subscription_id
                subscription = db.query(Subscription).filter(Subscription.id == exec_row.subscription_id).first()
                if subscription:
                    subscription_name = subscription.name

            # Filter by sync_type if provided
            if sync_type and exec_sync_type != sync_type:
                continue

            duration = None
            if exec_row.started_at and exec_row.completed_at:
                duration = int((exec_row.completed_at - exec_row.started_at).total_seconds())

            history_items.append(SyncHistoryItem(
                id=f"xtream_{exec_row.id}",
                source_type="xtream",
                source_name=subscription_name,
                sync_type=exec_sync_type or "unknown",
                started_at=exec_row.started_at,
                completed_at=exec_row.completed_at,
                duration_seconds=duration,
                status=exec_row.status.value if hasattr(exec_row.status, 'value') else str(exec_row.status),
                **_counters(exec_row),
                item_unit=_item_unit(exec_sync_type),
                error_message=exec_row.error_message
            ))

    # Plex executions
    if source_type is None or source_type == "plex":
        # Query all executions (both scheduled and manual)
        plex_executions = db.query(PlexScheduleExecution).order_by(
            PlexScheduleExecution.started_at.desc()
        ).all()

        for exec_row in plex_executions:
            # Get server name - from schedule or direct server_id
            server_name = "Unknown"
            exec_sync_type = exec_row.sync_type

            if exec_row.schedule_id:
                # Scheduled sync - get info from schedule
                schedule = db.query(PlexSchedule).filter(PlexSchedule.id == exec_row.schedule_id).first()
                if schedule:
                    server = db.query(PlexServer).filter(PlexServer.id == schedule.server_id).first()
                    if server:
                        server_name = server.name
                    exec_sync_type = schedule.type.value if hasattr(schedule.type, 'value') else str(schedule.type)
            elif exec_row.server_id:
                # Manual sync - get info from server_id
                server = db.query(PlexServer).filter(PlexServer.id == exec_row.server_id).first()
                if server:
                    server_name = server.name

            # Filter by sync_type if provided
            if sync_type and exec_sync_type != sync_type:
                continue

            duration = None
            if exec_row.started_at and exec_row.completed_at:
                duration = int((exec_row.completed_at - exec_row.started_at).total_seconds())

            history_items.append(SyncHistoryItem(
                id=f"plex_{exec_row.id}",
                source_type="plex",
                source_name=server_name,
                sync_type=exec_sync_type or "unknown",
                started_at=exec_row.started_at,
                completed_at=exec_row.completed_at,
                duration_seconds=duration,
                status=exec_row.status.value if hasattr(exec_row.status, 'value') else str(exec_row.status),
                **_counters(exec_row),
                item_unit=_item_unit(exec_sync_type),
                error_message=exec_row.error_message
            ))

    # Sort all by started_at descending
    history_items.sort(key=lambda x: x.started_at, reverse=True)

    # Apply pagination
    return history_items[offset:offset + limit]


@router.get("/stats")
async def get_sync_stats(db: Session = Depends(get_db)):
    """Get sync statistics summary"""

    # Count executions by status
    xtream_success = db.query(ScheduleExecution).filter(
        ScheduleExecution.status == "success"
    ).count()
    xtream_failed = db.query(ScheduleExecution).filter(
        ScheduleExecution.status == "failed"
    ).count()
    xtream_total = db.query(ScheduleExecution).count()

    plex_success = db.query(PlexScheduleExecution).filter(
        PlexScheduleExecution.status == "success"
    ).count()
    plex_failed = db.query(PlexScheduleExecution).filter(
        PlexScheduleExecution.status == "failed"
    ).count()
    plex_total = db.query(PlexScheduleExecution).count()

    total = xtream_total + plex_total
    success = xtream_success + plex_success
    failed = xtream_failed + plex_failed

    return {
        "total_executions": total,
        "successful": success,
        "failed": failed,
        "success_rate": round((success / total * 100) if total > 0 else 100, 1),
        "by_source": {
            "xtream": {"total": xtream_total, "success": xtream_success, "failed": xtream_failed},
            "plex": {"total": plex_total, "success": plex_success, "failed": plex_failed}
        }
    }
