import os
import httpx
import logging
import time
import asyncio
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from app.core.celery_app import celery_app
from app.db.session import SessionLocal
from app.models.downloads import (
    DownloadTask, DownloadStatus, DownloadSettings, 
    MonitoredMedia, DownloadSettingsGlobal, DownloadStatistics
)
from app.models.subscription import Subscription
from app.models.cache import MovieCache, SeriesCache, EpisodeCache
from app.models.settings import SettingsModel
from app.services.xtream import XtreamClient
from app.services.file_manager import FileManager

logger = logging.getLogger(__name__)

# Constants
CHUNK_SIZE = 64 * 1024  # 64KB for better throttling control
DB_REFRESH_INTERVAL = 5.0  # Refresh DB once every 5 seconds during download

# --- Helper Functions ---

def get_global_settings(db: Session):
    settings = db.query(DownloadSettingsGlobal).first()
    if not settings:
        settings = DownloadSettingsGlobal()
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings

def update_daily_stats(db: Session, success=True, bytes_downloaded=0.0):
    # Local calendar day on purpose: this is the date label shown to the user
    today = datetime.now().strftime("%Y-%m-%d")
    stats = db.query(DownloadStatistics).filter(DownloadStatistics.date == today).first()
    if not stats:
        stats = DownloadStatistics(date=today)
        db.add(stats)
    
    stats.total_downloads = (stats.total_downloads or 0) + 1
    if success:
        stats.completed_downloads = (stats.completed_downloads or 0) + 1
        stats.total_bytes_downloaded = (stats.total_bytes_downloaded or 0) + bytes_downloaded
    else:
        stats.failed_downloads = (stats.failed_downloads or 0) + 1
    
    db.commit()

def is_quiet_hours(settings: DownloadSettingsGlobal):
    if not settings.quiet_hours_start or not settings.quiet_hours_end:
        return False
    
    # Local wall-clock on purpose: quiet_hours_start/end are times the user
    # typed ("23:00"), not UTC instants.
    now = datetime.now().time()
    try:
        start = datetime.strptime(settings.quiet_hours_start, "%H:%M").time()
        end = datetime.strptime(settings.quiet_hours_end, "%H:%M").time()
    except Exception:
        return False
    
    if start <= end:
        return start <= now <= end
    else: # Over midnight
        return now >= start or now <= end

def cleanup_old_tasks(db: Session, settings: DownloadSettingsGlobal):
    """Delete old completed/failed tasks based on retention settings"""
    if not settings.auto_cleanup_enabled:
        return
    
    # Completed tasks
    completed_limit = datetime.utcnow() - timedelta(days=settings.keep_completed_days or 7)
    db.query(DownloadTask).filter(
        DownloadTask.status == DownloadStatus.COMPLETED,
        DownloadTask.completed_at < completed_limit
    ).delete()
    
    # Failed tasks
    failed_limit = datetime.utcnow() - timedelta(days=settings.keep_failed_days or 7)
    db.query(DownloadTask).filter(
        DownloadTask.status == DownloadStatus.FAILED,
        DownloadTask.created_at < failed_limit
    ).delete()
    
    db.commit()

def _resolve_target_path(db: Session, download: DownloadTask, subscription: Subscription, app_settings: Dict[str, Any]) -> Path:
    """Determine final save path and create directories."""
    prefix_regex = app_settings.get("PREFIX_REGEX")
    format_date = app_settings.get("FORMAT_DATE_IN_TITLE") == "true"
    clean_name = app_settings.get("CLEAN_NAME") == "true"
    use_season_folders = app_settings.get("SERIES_USE_SEASON_FOLDERS", "true") == "true"
    include_series_name = app_settings.get("SERIES_INCLUDE_NAME_IN_FILENAME", "false") == "true"
    use_category_folders = app_settings.get("SERIES_USE_CATEGORY_FOLDERS", "true") == "true"

    if download.media_type == "movie":
        base_dir = subscription.download_movies_dir or "/output/downloads/movies"
    else:
        base_dir = subscription.download_series_dir or "/output/downloads/series"
        
    fm = FileManager(base_dir)
    cat_name = "Uncategorized"
    xc = XtreamClient(subscription.xtream_url, subscription.username, subscription.password)
    try:

        if download.media_type == "movie":
            movie_cache = db.query(MovieCache).filter(
                MovieCache.subscription_id == download.subscription_id,
                MovieCache.stream_id == int(download.media_id)
            ).first()
        
            category_id = movie_cache.category_id if movie_cache else None
            movie_name = movie_cache.name if movie_cache else download.title
            tmdb_id = movie_cache.tmdb_id if movie_cache else None

            # Fallback to API if cache is missing or incomplete
            if not movie_cache:
                try:
                    logger.info(f"Movie cache missing for ID {download.media_id}. Fetching from API.")
                    movies = xc.get_vod_streams_sync()
                    media = next((m for m in movies if str(m['stream_id']) == str(download.media_id)), None)
                    if media:
                        movie_name = media.get('name', movie_name)
                        category_id = media.get('category_id')
                        tmdb_id = media.get('tmdb')
                except Exception as e:
                    logger.warning(f"Failed to fetch movie info from API: {e}")
        
            movie_name = movie_name.strip().strip('-').strip()

            if category_id:
                try:
                    categories = xc.get_vod_categories_sync()
                    cat_map = {str(c['category_id']): c['category_name'] for c in categories}
                    cat_name = cat_map.get(str(category_id), "Uncategorized")
                except Exception as e: 
                    logger.warning(f"Failed to fetch VOD categories: {e}")
        
            movie_data = {
                "name": movie_name,
                "tmdb": tmdb_id
            }
            target_info = fm.get_movie_target_info(movie_data, cat_name, prefix_regex, format_date, clean_name)
        
            save_dir = Path(target_info["target_dir"])
            save_dir.mkdir(parents=True, exist_ok=True)
            return save_dir / f"{target_info['filename_base']}.mp4"

        else: # episode
            episode_cache = db.query(EpisodeCache).filter(
                EpisodeCache.subscription_id == download.subscription_id,
                EpisodeCache.id == int(download.media_id)
            ).first()
        
            series_cache = None
            series_id = None
            season_num = 1
            ep_num = 1
            ep_title = ""

            if episode_cache:
                series_id = episode_cache.series_id
                season_num = episode_cache.season_num
                ep_num = episode_cache.episode_num
                ep_title = episode_cache.title
            
                series_cache = db.query(SeriesCache).filter(
                    SeriesCache.subscription_id == download.subscription_id,
                    SeriesCache.series_id == series_id
                ).first()
            else:
                # If no episode cache, try to parse from title
                logger.info(f"DEBUG_PATH: Episode cache missing for ID {download.media_id}. Title: '{download.title}'")
                import re
            
                # Robust regex for series titles
                m = re.search(r'^(.*?)(?:\s+-\s*|\s+)S(\d+)E(\d+)(?:\s*[- ]+\s*(.*))?$', download.title, re.IGNORECASE)
                if not m:
                    logger.info("DEBUG_PATH: Main regex failed. Trying fallback.")
                    m = re.search(r'S(\d+)E(\d+)\s+(.*)$', download.title, re.IGNORECASE)
                    if m:
                        season_num = int(m.group(1))
                        ep_num = int(m.group(2))
                        series_name = m.group(3).strip().strip('-').strip()
                        logger.info(f"DEBUG_PATH: Fallback match: s={season_num} e={ep_num} name='{series_name}'")
                else:
                    series_name = m.group(1).strip().strip('-').strip()
                    season_num = int(m.group(2))
                    ep_num = int(m.group(3))
                    ep_title = m.group(4).strip() if m.group(4) else ""
                    logger.info(f"DEBUG_PATH: Main match: name='{series_name}' s={season_num} e={ep_num} title='{ep_title}'")
                
                if 'series_name' in locals() and series_name and series_name != "Unknown Series":
                    # Try to find a series by this name in cache to get category
                    series_cache = db.query(SeriesCache).filter(
                        SeriesCache.subscription_id == download.subscription_id,
                        SeriesCache.name.ilike(series_name)
                    ).first()
                
                    if series_cache:
                        series_name = series_cache.name
                        category_id = series_cache.category_id
                        tmdb_id = series_cache.tmdb_id
                        logger.info(f"DEBUG_PATH: Name lookup SUCCESS: series='{series_name}' cat_id={category_id}")
                    else:
                        logger.info(f"DEBUG_PATH: Name lookup FAILED in cache for '{series_name}'. Trying API.")
                        try:
                            api_series = xc.get_series_sync()
                            # Case-insensitive match in API results
                            s_data = next((s for s in api_series if s.get('name', '').lower() == series_name.lower()), None)
                            if s_data:
                                series_name = s_data.get('name', series_name)
                                category_id = s_data.get('category_id')
                                tmdb_id = s_data.get('tmdb')
                                logger.info(f"DEBUG_PATH: API Name match SUCCESS: series='{series_name}' cat_id={category_id}")
                            else:
                                logger.info(f"DEBUG_PATH: API Name match FAILED for '{series_name}'")
                        except Exception as e:
                            logger.warning(f"DEBUG_PATH: API series fetch failed: {e}")

            # Basic defaults if not resolved
            if 'series_name' not in locals(): series_name = "Unknown Series"
            if 'category_id' not in locals(): category_id = None
            if 'tmdb_id' not in locals(): tmdb_id = None
        
            logger.info(f"DEBUG_PATH: Final resolved: name='{series_name}' cat_id={category_id} tmdb={tmdb_id}")

            if series_cache:
                series_name = series_cache.name
                category_id = series_cache.category_id
                tmdb_id = series_cache.tmdb_id
            elif not category_id:
                # Try to fetch series info from API if we have series_id
                if series_id:
                    try:
                        logger.info(f"Series cache missing for ID {series_id}. Fetching from API.")
                        series_list = xc.get_series_sync()
                        s_data = next((s for s in series_list if str(s['series_id']) == str(series_id)), None)
                        if s_data:
                            series_name = s_data.get('name', series_name)
                            category_id = s_data.get('category_id')
                            tmdb_id = s_data.get('tmdb')
                    except Exception as e:
                        logger.warning(f"Failed to fetch series info from API: {e}")

            if category_id:
                try:
                    categories = xc.get_series_categories_sync()
                    cat_map = {str(c['category_id']): c['category_name'] for c in categories}
                    cat_name = cat_map.get(str(category_id), "Uncategorized")
                except Exception as e:
                    logger.warning(f"Failed to fetch series categories: {e}")
        
            series_data = {
                "name": series_name,
                "tmdb": tmdb_id
            }
            target_info = fm.get_series_target_info(series_data, cat_name, prefix_regex, format_date, clean_name, use_category_folders)
        
            series_dir = Path(target_info["series_dir"])
            series_dir.mkdir(parents=True, exist_ok=True)
        
            # Determine filename
            current_dir = series_dir / f"Season {season_num:02d}" if use_season_folders else series_dir
            current_dir.mkdir(parents=True, exist_ok=True)
        
            formatted_ep = f"S{season_num:02d}E{ep_num:02d}"
            safe_series_name = target_info["safe_series_name"]
        
            if ep_title:
                if ep_title.lower().endswith(".mp4"):
                    ep_title = ep_title[:-4]
                safe_ep_title = fm.sanitize_name(ep_title)
            else:
                safe_ep_title = ""
        
            if include_series_name:
                filename_base = f"{safe_series_name} - {formatted_ep}"
            else:
                filename_base = formatted_ep
        
            filename = f"{filename_base} - {safe_ep_title}.mp4" if safe_ep_title else f"{filename_base}.mp4"
            return current_dir / filename
    finally:
        xc.close()

def _perform_download_stream(db: Session, download: DownloadTask, save_path: Path, settings: DownloadSettingsGlobal):
    """Core download logic with retry support, throttling, and optimized DB refresh."""
    existing_size = save_path.stat().st_size if save_path.exists() else 0
    download.downloaded_bytes = existing_size
    db.commit()

    # Client configuration
    client_timeout = settings.connection_timeout_seconds or 30
    max_redirects = settings.max_redirects or 10
    limits = httpx.Limits(max_connections=10, max_keepalive_connections=5)
    
    with httpx.Client(limits=limits, follow_redirects=True, max_redirects=max_redirects, 
                      timeout=httpx.Timeout(client_timeout, read=None)) as client:
        
        while True:
            headers = {'Range': f'bytes={existing_size}-'} if existing_size > 0 else {}
            try:
                with client.stream("GET", download.url, headers=headers) as response:
                    response.raise_for_status()
                    
                    # Handle 200 vs 206
                    if response.status_code == 200 and existing_size > 0:
                        logger.warning(f"Server ignored Range for {download.id}. Restarting.")
                        existing_size = 0
                        download.downloaded_bytes = 0
                        mode = 'wb'
                    else:
                        mode = 'ab' if existing_size > 0 else 'wb'

                    # Extract file size
                    if 'content-length' in response.headers:
                        if response.status_code == 206:
                            content_range = response.headers.get('content-range', '')
                            if '/' in content_range:
                                total_str = content_range.split('/')[-1]
                                if total_str != '*':
                                    download.file_size = int(total_str)
                        else:
                            download.file_size = int(response.headers['content-length'])
                    db.commit()

                    # Download loop
                    start_time = time.time()
                    last_db_refresh = time.time()
                    bytes_sampled = 0
                    sample_start = time.time()
                    speed_limit = download.speed_limit_kbps or settings.global_speed_limit_kbps

                    with open(save_path, mode) as f:
                        for chunk in response.iter_bytes(chunk_size=CHUNK_SIZE):
                            # Optimized DB Refresh (Check pause/cancel every 5s)
                            now = time.time()
                            if now - last_db_refresh >= DB_REFRESH_INTERVAL:
                                db.refresh(download)
                                if download.status in [DownloadStatus.PAUSED, DownloadStatus.CANCELLED]:
                                    logger.info(f"Download {download.id} {download.status}")
                                    return False # Interrupted
                                last_db_refresh = now
                            
                            f.write(chunk)
                            download.downloaded_bytes += len(chunk)
                            bytes_sampled += len(chunk)

                            # Throttling
                            if speed_limit > 0:
                                expected = (download.downloaded_bytes - existing_size) / (speed_limit * 1024)
                                elapsed = time.time() - start_time
                                if elapsed < expected:
                                    time.sleep(expected - elapsed)

                            # Statistics Update (Non-blocking)
                            sample_elapsed = now - sample_start
                            if sample_elapsed >= 1.0:
                                download.current_speed_kbps = (bytes_sampled / 1024) / sample_elapsed
                                if download.file_size:
                                    download.progress = min((download.downloaded_bytes / download.file_size) * 100, 99.9)
                                    if download.current_speed_kbps > 0:
                                        rem = (download.file_size - download.downloaded_bytes) / 1024
                                        download.estimated_time_remaining = int(rem / download.current_speed_kbps)
                                bytes_sampled = 0
                                sample_start = now
                                db.commit()

                    return True # Success

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 416:
                    # Verify if already done
                    try:
                        head = client.head(download.url)
                        srv_size = int(head.headers.get('content-length', 0))
                        if srv_size > 0 and existing_size >= srv_size:
                            download.file_size = srv_size
                            download.downloaded_bytes = existing_size
                            return True
                    except Exception: pass
                    # Else reset
                    existing_size = 0
                    download.downloaded_bytes = 0
                    continue
                raise e
            except (httpx.NetworkError, httpx.TimeoutException) as e:
                logger.error(f"Network error for {download.id}: {e}")
                raise e

def _process_auto_downloads_sync(db: Session):
    """Synchronous logic for auto-downloads"""
    monitored_items = db.query(MonitoredMedia).filter(MonitoredMedia.is_active == True).all()
    for item in monitored_items:
        subscription = db.query(Subscription).filter(Subscription.id == item.subscription_id).first()
        if not subscription: continue
        
        xc = XtreamClient(subscription.xtream_url, subscription.username, subscription.password)
        existing_ids = {t.media_id for t in db.query(DownloadTask.media_id)
                       .filter(DownloadTask.subscription_id == item.subscription_id).all()}
        
        # Get naming rules for title cleaning
        settings_dict = {s.key: s.value for s in db.query(SettingsModel).all()}
        prefix_regex = settings_dict.get("PREFIX_REGEX")
        format_date = settings_dict.get("FORMAT_DATE_IN_TITLE") == "true"
        clean_name = settings_dict.get("CLEAN_NAME") == "true"
        fm = FileManager("")

        new_tasks = 0
        if item.media_type == "category_movie":
            try:
                movies = xc.get_vod_streams_sync(category_id=item.media_id)
                for movie in movies:
                    sid = str(movie['stream_id'])
                    if sid not in existing_ids:
                        raw_title = movie.get('name', f'Movie_{sid}')
                        title = fm.clean_title(raw_title, prefix_regex, format_date, clean_name)
                        db.add(DownloadTask(
                            subscription_id=item.subscription_id, media_type="movie", media_id=sid,
                            title=title,
                            url=xc.get_stream_url("movie", sid, movie.get('container_extension', 'mp4')),
                            status=DownloadStatus.PENDING
                        ))
                        new_tasks += 1
                        existing_ids.add(sid)
            except Exception: pass
        
        elif item.media_type == "series":
            try:
                series_info = xc.get_series_info_sync(series_id=item.media_id)
                episodes = series_info.get('episodes', {})
                series_name = fm.clean_title(item.title, prefix_regex, format_date, clean_name)
                
                for season, eps in episodes.items():
                    for ep in eps:
                        sid = str(ep['id'])
                        if sid not in existing_ids:
                            ep_info = f"S{int(season):02d}E{int(ep.get('episode_num', 0)):02d}"
                            ep_title = ep.get('title', '')
                            if ep_title:
                                # Remove extension if present
                                if ep_title.lower().endswith(".mp4"):
                                    ep_title = ep_title[:-4]
                                ep_title = f" - {ep_title}"
                            
                            title = f"{series_name} - {ep_info}{ep_title}"
                            db.add(DownloadTask(
                                subscription_id=item.subscription_id, media_type="episode", media_id=sid,
                                title=title,
                                url=xc.get_stream_url("series", sid, ep.get('container_extension', 'mp4')),
                                status=DownloadStatus.PENDING
                            ))
                            new_tasks += 1
                            existing_ids.add(sid)
            except Exception: pass

        elif item.media_type == "category_series":
            try:
                series_list = xc.get_series_sync(category_id=item.media_id)
                for s in series_list:
                    series_id = str(s['series_id'])
                    s_name_raw = s.get('name', s.get('title', f"Series_{series_id}"))
                    series_name = fm.clean_title(s_name_raw, prefix_regex, format_date, clean_name)
                    
                    try:
                        series_info = xc.get_series_info_sync(series_id=series_id)
                        episodes = series_info.get('episodes', {})
                        
                        for season, eps in episodes.items():
                            for ep in eps:
                                ep_sid = str(ep['id'])
                                if ep_sid not in existing_ids:
                                    ep_info = f"S{int(season):02d}E{int(ep.get('episode_num', 0)):02d}"
                                    ep_title = ep.get('title', '')
                                    if ep_title:
                                        if ep_title.lower().endswith(".mp4"):
                                            ep_title = ep_title[:-4]
                                        ep_title = f" - {ep_title}"
                                    
                                    title = f"{series_name} - {ep_info}{ep_title}"
                                    db.add(DownloadTask(
                                        subscription_id=item.subscription_id, media_type="episode", media_id=ep_sid,
                                        title=title,
                                        url=xc.get_stream_url("series", ep_sid, ep.get('container_extension', 'mp4')),
                                        status=DownloadStatus.PENDING
                                    ))
                                    new_tasks += 1
                                    existing_ids.add(ep_sid)
                    except Exception:
                        continue
            except Exception: pass
        
        xc.close()

        item.last_check = datetime.utcnow()
        db.commit()
        if new_tasks > 0:
            logger.info(f"Auto-download: Queued {new_tasks} items for {item.title}")

    if db.query(DownloadTask).filter(DownloadTask.status == DownloadStatus.PENDING).count() > 0:
        process_download_queue.delay()

# --- Celery Tasks ---

@celery_app.task(bind=True)
def download_media_task(self, download_id: int):
    """Modularized download task."""
    db = SessionLocal()
    try:
        download = db.query(DownloadTask).filter(DownloadTask.id == download_id).first()
        if not download or download.status in [DownloadStatus.COMPLETED, DownloadStatus.CANCELLED]:
            return
        
        settings = get_global_settings(db)
        subscription = db.query(Subscription).filter(Subscription.id == download.subscription_id).first()
        if not subscription: return

        # App settings for naming
        settings_dict = {s.key: s.value for s in db.query(SettingsModel).all()}
        
        # 1. Resolve Path
        save_path = _resolve_target_path(db, download, subscription, settings_dict)
        
        # 2. Start Download
        download.status = DownloadStatus.DOWNLOADING
        download.started_at = datetime.utcnow()
        download.task_id = self.request.id
        db.commit()

        success = _perform_download_stream(db, download, save_path, settings)

        if success:
            download.status = DownloadStatus.COMPLETED
            download.completed_at = datetime.utcnow()
            download.progress = 100.0
            download.save_path = str(save_path)
            db.commit()
            update_daily_stats(db, success=True, bytes_downloaded=float(download.downloaded_bytes))
            logger.info(f"Download {download_id} finished: {download.title}")

    except Exception as e:
        logger.error(f"Task {download_id} failed: {e}")
        try:
            db.refresh(download)
            download.retry_count = (download.retry_count or 0) + 1
            max_r = settings.default_max_retries or 3
            
            if download.retry_count < max_r:
                delay = 60 * (2 ** (download.retry_count - 1))
                download.status = DownloadStatus.PENDING
                download.next_retry_at = datetime.utcnow() + timedelta(seconds=delay)
                download.error_message = f"Retry {download.retry_count}/{max_r}: {e}"
                db.commit()
                download_media_task.apply_async(args=[download_id], countdown=delay)
            else:
                download.status = DownloadStatus.FAILED
                download.error_message = str(e)
                db.commit()
                update_daily_stats(db, success=False)
        except Exception as retry_err:
            logger.error(f"Error handling retry: {retry_err}")
    finally:
        db.close()

@celery_app.task
def process_download_queue():
    """Background task that processes the download queue."""
    db = SessionLocal()
    try:
        settings = get_global_settings(db)
        
        if settings.download_mode == "sequential":
            total_active = db.query(DownloadTask).filter(DownloadTask.status == DownloadStatus.DOWNLOADING).count()
            if total_active >= 1: return
            
            subscriptions = db.query(Subscription).filter(Subscription.is_active == True).all()
            all_pending = []
            for sub in subscriptions:
                pending = db.query(DownloadTask).filter(
                    DownloadTask.subscription_id == sub.id,
                    DownloadTask.status == DownloadStatus.PENDING
                ).all()
                all_pending.extend(pending)
            
            if all_pending:
                all_pending.sort(key=lambda x: (x.priority or 0, x.created_at), reverse=True)
                download = all_pending[0]
                if not download.scheduled_start_at or download.scheduled_start_at <= datetime.utcnow():
                    # Mark as downloading immediately to reserve the slot
                    download.status = DownloadStatus.DOWNLOADING
                    download.started_at = datetime.utcnow()
                    db.commit()
                    
                    download_media_task.delay(download.id)
            return

        subscriptions = db.query(Subscription).filter(Subscription.is_active == True).all()
        for sub in subscriptions:
            active_count = db.query(DownloadTask).filter(
                DownloadTask.subscription_id == sub.id,
                DownloadTask.status == DownloadStatus.DOWNLOADING
            ).count()
            
            max_parallel = sub.max_parallel_downloads or 2
            available_slots = max_parallel - active_count
            if available_slots > 0:
                pending_downloads = db.query(DownloadTask).filter(
                    DownloadTask.subscription_id == sub.id,
                    DownloadTask.status == DownloadStatus.PENDING
                ).order_by(DownloadTask.priority.desc(), DownloadTask.created_at.asc()).limit(available_slots).all()
                
                for download in pending_downloads:
                    if download.scheduled_start_at and download.scheduled_start_at > datetime.utcnow():
                        continue
                    
                    # Mark as downloading immediately to reserve the slot
                    download.status = DownloadStatus.DOWNLOADING
                    download.started_at = datetime.utcnow()
                    db.commit() # Commit each one to be safe for other concurrent processors
                    
                    download_media_task.delay(download.id)
    finally:
        db.close()

@celery_app.task
def check_auto_downloads():
    """Periodic task for auto-downloads, cleanup and recovery."""
    db = SessionLocal()
    try:
        settings = get_global_settings(db)
        # 1. Recovery
        interrupted = db.query(DownloadTask).filter(DownloadTask.status == DownloadStatus.DOWNLOADING).all()
        for t in interrupted:
            t.status = DownloadStatus.PENDING
            t.error_message = "Recovery: interrupted by restart"
        db.commit()

        # 2. Cleanup
        cleanup_old_tasks(db, settings)
        
        # 3. Process auto-downloads
        _process_auto_downloads_sync(db)
    except Exception as e:
        logger.error(f"Error in check_auto_downloads: {e}")
    finally:
        db.close()
