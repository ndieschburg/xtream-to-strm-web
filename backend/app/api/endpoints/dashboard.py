from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func, or_
from typing import Dict, List, Any
from app.db.session import get_db
from app.models.subscription import Subscription
from app.models.m3u_source import M3USource
from app.models.m3u_entry import M3UEntry, EntryType
from app.models.sync_state import SyncState
from app.models.schedule import Schedule
from app.models.schedule_execution import ScheduleExecution, ExecutionStatus
from app.models.plex_schedule_execution import PlexScheduleExecution, PlexExecutionStatus
from app.models.cache import MovieCache, SeriesCache
from app.models.plex_account import PlexAccount
from app.models.plex_server import PlexServer
from app.models.plex_cache import PlexMovieCache, PlexSeriesCache
from app.models.plex_sync_state import PlexSyncState
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/stats")
def get_dashboard_stats(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Get overall dashboard statistics"""
    
    # Source statistics
    xtream_subs_total = db.query(Subscription).count()
    xtream_active = db.query(Subscription).filter(Subscription.is_active == True).count()

    m3u_total = db.query(M3USource).count()
    m3u_active = db.query(M3USource).filter(M3USource.is_active == True).count()

    # Plex source statistics
    plex_servers_total = db.query(PlexServer).count()
    plex_servers_active = db.query(PlexServer).filter(PlexServer.is_selected == True).count()

    # Content statistics from M3U entries
    m3u_movies = db.query(M3UEntry).filter(M3UEntry.entry_type == EntryType.MOVIE).count()
    m3u_series = db.query(M3UEntry).filter(M3UEntry.entry_type == EntryType.SERIES).count()

    # Content statistics from Xtream Cache
    xtream_movies = db.query(MovieCache).count()
    xtream_series = db.query(SeriesCache).count()

    # Content statistics from Plex Cache
    plex_movies = db.query(PlexMovieCache).count()
    plex_series = db.query(PlexSeriesCache).count()

    movies_count = m3u_movies + xtream_movies + plex_movies
    series_count = m3u_series + xtream_series + plex_series
    
    # Sync status from execution tables
    yesterday = datetime.utcnow() - timedelta(days=1)

    # In-progress syncs from execution tables
    xtream_running = db.query(ScheduleExecution).filter(
        ScheduleExecution.status == ExecutionStatus.RUNNING
    ).count()
    plex_running = db.query(PlexScheduleExecution).filter(
        PlexScheduleExecution.status == PlexExecutionStatus.RUNNING
    ).count()
    syncing = xtream_running + plex_running

    # Error count (last 24h) from execution tables
    xtream_errors = db.query(ScheduleExecution).filter(
        ScheduleExecution.status == ExecutionStatus.FAILED,
        ScheduleExecution.started_at >= yesterday
    ).count()
    plex_errors = db.query(PlexScheduleExecution).filter(
        PlexScheduleExecution.status == PlexExecutionStatus.FAILED,
        PlexScheduleExecution.started_at >= yesterday
    ).count()
    errors_24h = xtream_errors + plex_errors

    # Success rate (last 24h) from execution tables
    xtream_completed = db.query(ScheduleExecution).filter(
        ScheduleExecution.started_at >= yesterday,
        ScheduleExecution.status != ExecutionStatus.RUNNING
    ).count()
    xtream_success = db.query(ScheduleExecution).filter(
        ScheduleExecution.status == ExecutionStatus.SUCCESS,
        ScheduleExecution.started_at >= yesterday
    ).count()
    plex_total = db.query(PlexScheduleExecution).filter(
        PlexScheduleExecution.started_at >= yesterday,
        PlexScheduleExecution.status != PlexExecutionStatus.RUNNING
    ).count()
    plex_success = db.query(PlexScheduleExecution).filter(
        PlexScheduleExecution.status == PlexExecutionStatus.SUCCESS,
        PlexScheduleExecution.started_at >= yesterday
    ).count()

    total_completed = xtream_completed + plex_total
    total_success = xtream_success + plex_success
    success_rate = (total_success / total_completed * 100) if total_completed > 0 else 100

    # Get running tasks details
    running_tasks = []

    xtream_running_tasks = db.query(ScheduleExecution).filter(
        ScheduleExecution.status == ExecutionStatus.RUNNING
    ).all()
    for task in xtream_running_tasks:
        source_name = "Unknown"
        if task.subscription_id:
            sub = db.query(Subscription).filter(Subscription.id == task.subscription_id).first()
            if sub:
                source_name = sub.name
        elif task.schedule_id:
            from app.models.schedule import Schedule
            schedule = db.query(Schedule).filter(Schedule.id == task.schedule_id).first()
            if schedule:
                sub = db.query(Subscription).filter(Subscription.id == schedule.subscription_id).first()
                if sub:
                    source_name = sub.name
        running_tasks.append({
            "source": source_name,
            "type": "xtream",
            "sync_type": task.sync_type or "unknown",
            "started_at": task.started_at.isoformat() if task.started_at else None
        })

    plex_running_tasks = db.query(PlexScheduleExecution).filter(
        PlexScheduleExecution.status == PlexExecutionStatus.RUNNING
    ).all()
    for task in plex_running_tasks:
        source_name = "Unknown"
        if task.server_id:
            server = db.query(PlexServer).filter(PlexServer.id == task.server_id).first()
            if server:
                source_name = server.name
        elif task.schedule_id:
            from app.models.plex_schedule import PlexSchedule
            schedule = db.query(PlexSchedule).filter(PlexSchedule.id == task.schedule_id).first()
            if schedule:
                server = db.query(PlexServer).filter(PlexServer.id == schedule.server_id).first()
                if server:
                    source_name = server.name
        running_tasks.append({
            "source": source_name,
            "type": "plex",
            "sync_type": task.sync_type or "unknown",
            "started_at": task.started_at.isoformat() if task.started_at else None
        })

    return {
        "sources": {
            "total": xtream_subs_total + m3u_total + plex_servers_total,
            "xtream": xtream_subs_total,
            "m3u": m3u_total,
            "plex": plex_servers_total,
            "active": xtream_active + m3u_active + plex_servers_active,
            "inactive": (xtream_subs_total - xtream_active) + (m3u_total - m3u_active) + (plex_servers_total - plex_servers_active)
        },
        "total_content": {
            "movies": movies_count,
            "series": series_count,
            "total": movies_count + series_count
        },
        "sync_status": {
            "in_progress": syncing,
            "errors_24h": errors_24h,
            "success_rate": round(success_rate, 1),
            "running_tasks": running_tasks
        }
    }


@router.get("/recent-activity")
def get_recent_activity(
    limit: int = 10,
    db: Session = Depends(get_db)
) -> List[Dict[str, Any]]:
    """Get recent sync activity"""
    
    recent_syncs = db.query(SyncState).order_by(
        SyncState.last_sync.desc()
    ).limit(limit).all()
    
    activity = []
    for sync in recent_syncs:
        # Determine source name and type
        source_name = "Unknown"
        source_type = "unknown"
        
        if sync.type == "movies" or sync.type == "series":
            # XtreamTV sync
            sub = db.query(Subscription).filter(
                Subscription.id == sync.subscription_id
            ).first()
            if sub:
                source_name = sub.name
                source_type = "xtream"
        
        # Calculate duration if we have both start and update times
        duration = None
        if sync.last_sync and sync.last_sync:
            # Estimate duration (this is approximate)
            duration = 0  # We don't track start time currently
        
        activity.append({
            "id": sync.id,
            "source_name": source_name,
            "source_type": source_type,
            "sync_type": sync.type,
            "status": sync.status,
            "items_processed": (sync.items_added or 0) + (sync.items_deleted or 0),
            "timestamp": sync.last_sync.isoformat() if sync.last_sync else None,
            "duration": duration,
            "error_message": sync.error_message if sync.status == "error" else None
        })
    
    return activity


@router.get("/scheduled-syncs")
def get_scheduled_syncs(db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    """Get upcoming scheduled syncs"""
    
    # The column is `enabled`, not `is_active`
    schedules = db.query(Schedule).filter(
        Schedule.enabled == True
    ).all()
    
    scheduled = []
    for schedule in schedules:
        # Get source name
        source_name = "Unknown"
        source_type = "unknown"
        
        if schedule.subscription_id:
            sub = db.query(Subscription).filter(
                Subscription.id == schedule.subscription_id
            ).first()
            if sub:
                source_name = sub.name
                source_type = "xtream"
        
        # Calculate next run time
        next_run = None
        if schedule.last_run:
            if schedule.frequency == "hourly":
                next_run = schedule.last_run + timedelta(hours=1)
            elif schedule.frequency == "daily":
                next_run = schedule.last_run + timedelta(days=1)
            elif schedule.frequency == "weekly":
                next_run = schedule.last_run + timedelta(weeks=1)
        
        scheduled.append({
            "id": schedule.id,
            "source_name": source_name,
            "source_type": source_type,
            "sync_type": schedule.type.value if hasattr(schedule.type, "value") else str(schedule.type),
            "frequency": schedule.frequency,
            "next_run": next_run.isoformat() if next_run else None,
            "last_run": schedule.last_run.isoformat() if schedule.last_run else None
        })
    
    return scheduled


@router.get("/content-by-source")
def get_content_by_source(db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    """Get content breakdown by source"""
    
    result = []
    
    # XtreamTV sources
    subscriptions = db.query(Subscription).all()
    for sub in subscriptions:
        # Count from Cache
        movies_count = db.query(MovieCache).filter(
            MovieCache.subscription_id == sub.id
        ).count()
        
        series_count = db.query(SeriesCache).filter(
            SeriesCache.subscription_id == sub.id
        ).count()
        
        result.append({
            "source_name": sub.name,
            "source_type": "xtream",
            "movies": movies_count,
            "series": series_count,
            "total": movies_count + series_count
        })
    
    # M3U sources
    m3u_sources = db.query(M3USource).all()
    for source in m3u_sources:
        movies = db.query(M3UEntry).filter(
            M3UEntry.m3u_source_id == source.id,
            M3UEntry.entry_type == EntryType.MOVIE
        ).count()
        
        series = db.query(M3UEntry).filter(
            M3UEntry.m3u_source_id == source.id,
            M3UEntry.entry_type == EntryType.SERIES
        ).count()
        
        result.append({
            "source_name": source.name,
            "source_type": "m3u",
            "movies": movies,
            "series": series,
            "total": movies + series
        })

    # Plex servers
    plex_servers = db.query(PlexServer).all()
    for server in plex_servers:
        movies = db.query(PlexMovieCache).filter(
            PlexMovieCache.server_id == server.id
        ).count()

        series = db.query(PlexSeriesCache).filter(
            PlexSeriesCache.server_id == server.id
        ).count()

        result.append({
            "source_name": server.name,
            "source_type": "plex",
            "movies": movies,
            "series": series,
            "total": movies + series
        })

    return result
