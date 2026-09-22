import asyncio
import os
import shutil
from collections import defaultdict
from app.core.celery_app import celery_app
from sqlalchemy.orm import Session
from app.db.session import SessionLocal
from app.models.subscription import Subscription
from app.models.sync_state import SyncState, SyncStatus, SyncType
from app.models.selection import SelectedCategory
from app.models.cache import MovieCache, SeriesCache, EpisodeCache
from app.models.schedule import Schedule, SyncType as ScheduleSyncType
from app.models.schedule_execution import ScheduleExecution, ExecutionStatus
from app.services.xtream import XtreamClient
from app.core.config import settings as config_settings
from app.services.file_manager import FileManager
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


DEFAULT_PARALLELISM = {"SYNC_PARALLELISM_MOVIES": 5, "SYNC_PARALLELISM_SERIES": 5}


def _int_setting(settings: dict, key: str, default: int) -> int:
    try:
        return max(1, int(settings.get(key, default)))
    except (TypeError, ValueError):
        return default


def build_xtream_client(db: Session, sub: Subscription, parallelism_key: str) -> XtreamClient:
    """Build a client throttled with the rate limit configured in Administration.

    The connection pool is sized to the parallelism so a sync reuses keep-alive
    connections instead of opening a new one per request.
    """
    from app.models.settings import SettingsModel
    settings_map = {s.key: s.value for s in db.query(SettingsModel).all()}

    parallelism = _int_setting(settings_map, parallelism_key, DEFAULT_PARALLELISM[parallelism_key])
    try:
        rate_limit = float(settings_map.get("SYNC_RATE_LIMIT_RPS", config_settings.XTREAM_RATE_LIMIT_RPS))
    except (TypeError, ValueError):
        rate_limit = config_settings.XTREAM_RATE_LIMIT_RPS

    logger.info(f"Xtream client: {parallelism} parallel requests, max {rate_limit:.2f} req/s")
    return XtreamClient(
        sub.xtream_url, sub.username, sub.password,
        rate_limit=rate_limit, max_connections=parallelism
    )


async def _run_and_close(coro, xc: XtreamClient):
    """Await a sync coroutine, then release the client's connection pool."""
    try:
        return await coro
    finally:
        await xc.aclose()


def trigger_jellyfin_refresh(db: Session, library_type: str):
    """
    Trigger Jellyfin library refresh if configured.
    library_type: "movies" or "series"

    This function never raises exceptions - Jellyfin errors should not fail syncs.
    """
    from app.models.settings import SettingsModel
    try:
        settings = {s.key: s.value for s in db.query(SettingsModel).all()}

        # Check if Jellyfin integration is enabled
        if settings.get("JELLYFIN_REFRESH_ENABLED") != "true":
            return

        url = settings.get("JELLYFIN_URL")
        token = settings.get("JELLYFIN_API_TOKEN")

        if not url or not token:
            logger.debug("Jellyfin not configured, skipping refresh")
            return

        # Get appropriate library ID
        if library_type == "movies":
            library_id = settings.get("JELLYFIN_MOVIES_LIBRARY_ID")
        else:
            library_id = settings.get("JELLYFIN_SERIES_LIBRARY_ID")

        if not library_id:
            logger.debug(f"No Jellyfin library configured for {library_type}")
            return

        from app.services.jellyfin import JellyfinClient
        client = JellyfinClient(url, token)
        success = client.refresh_library_sync(library_id)

        if success:
            logger.info(f"Jellyfin {library_type} library refresh triggered successfully")
        else:
            logger.warning(f"Jellyfin {library_type} library refresh failed")

    except Exception as e:
        # Never fail the sync due to Jellyfin issues
        logger.error(f"Error triggering Jellyfin refresh for {library_type}: {e}")


async def process_movies(db: Session, xc: XtreamClient, fm: FileManager, subscription_id: int):
    # Get settings
    from app.models.settings import SettingsModel
    settings = {s.key: s.value for s in db.query(SettingsModel).all()}
    prefix_regex = settings.get("PREFIX_REGEX")
    format_date = settings.get("FORMAT_DATE_IN_TITLE") == "true"
    clean_name = settings.get("CLEAN_NAME") == "true"
    use_category_folders = settings.get("MOVIE_USE_CATEGORY_FOLDERS", "true") == "true"

    # Update status
    sync_state = db.query(SyncState).filter(
        SyncState.subscription_id == subscription_id,
        SyncState.type == SyncType.MOVIES
    ).first()
    
    if not sync_state:
        sync_state = SyncState(subscription_id=subscription_id, type=SyncType.MOVIES)
        db.add(sync_state)
    
    sync_state.status = SyncStatus.RUNNING
    sync_state.last_sync = datetime.utcnow()
    db.commit()

    try:
        # Fetch Categories
        categories = await xc.get_vod_categories()
        cat_map = {c['category_id']: c['category_name'] for c in categories}

        # Fetch All Movies
        all_movies = await xc.get_vod_streams()

        # Filter by selected categories if any
        selected_cats = db.query(SelectedCategory).filter(
            SelectedCategory.subscription_id == subscription_id,
            SelectedCategory.type == "movie"
        ).all()
        
        if selected_cats:
            selected_ids = {s.category_id for s in selected_cats}
            all_movies = [m for m in all_movies if m['category_id'] in selected_ids]
        
        # Current Cache
        cached_movies = {m.stream_id: m for m in db.query(MovieCache).filter(MovieCache.subscription_id == subscription_id).all()}
        
        to_add_update = []
        to_delete = []
        
        current_ids = set()

        for movie in all_movies:
            stream_id = int(movie['stream_id'])
            current_ids.add(stream_id)
            
            # Check if changed
            cached = cached_movies.get(stream_id)
            if not cached:
                to_add_update.append(movie)
            else:
                if cached.name != movie['name'] or cached.container_extension != movie['container_extension']:
                    to_add_update.append(movie)

        # Detect deletions
        for stream_id, cached in cached_movies.items():
            if stream_id not in current_ids:
                to_delete.append(cached)

        # Process Deletions
        for movie in to_delete:
            cat_name = cat_map.get(movie.category_id, "Uncategorized")
            target_info = fm.get_movie_target_info(
                {"name": movie.name, "tmdb": movie.tmdb_id}, 
                cat_name, prefix_regex, format_date, clean_name, use_category_folders
            )
            
            # 1. New Structure removal
            # Without a TMDB id the movie has no dedicated folder: target_dir is
            # the category (or output) directory, which must not be wiped
            has_own_folder = target_info["target_dir"] not in (target_info["cat_dir"], fm.output_dir)

            if has_own_folder:
                if os.path.exists(target_info["target_dir"]):
                    shutil.rmtree(target_info["target_dir"])
            else:
                base = target_info["target_dir"]
                await fm.delete_file(os.path.join(base, f"{target_info['filename_base']}.strm"))
                await fm.delete_file(os.path.join(base, f"{target_info['filename_base']}.nfo"))

            # 2. Old Structure removal (fallback)
            safe_name = fm.sanitize_name(movie.name)
            old_path = f"{target_info['cat_dir']}/{safe_name}.strm"
            old_nfo = f"{target_info['cat_dir']}/{safe_name}.nfo"
            await fm.delete_file(old_path)
            await fm.delete_file(old_nfo)

            await fm.delete_directory_if_empty(target_info['cat_dir'])
            
            db.delete(movie)
        
        # Process Additions/Updates with Parallel Fetching
        parallelism = _int_setting(settings, "SYNC_PARALLELISM_MOVIES", DEFAULT_PARALLELISM["SYNC_PARALLELISM_MOVIES"])
        batch_size = parallelism
        semaphore = asyncio.Semaphore(batch_size)

        # STRM files actually written: an unchanged file is left untouched
        strm_written = 0

        async def process_single_movie(movie):
            nonlocal strm_written
            async with semaphore:
                try:
                    stream_id = int(movie['stream_id'])
                    name = movie['name']
                    ext = movie['container_extension']
                    cat_id = movie['category_id']
                    tmdb_id = movie.get('tmdb')

                    # Fetch detailed info for Metadata
                    metadata_ok = True
                    try:
                        detailed_info = await xc.get_vod_info(str(stream_id))
                        if detailed_info and 'info' in detailed_info:
                            movie['info'] = detailed_info['info'] # Inject info for NFO generator
                            # Update TMDB if found
                            if detailed_info['info'].get('tmdb_id'):
                                tmdb_id = detailed_info['info'].get('tmdb_id')
                                movie['tmdb'] = tmdb_id # Update for object
                    except Exception as e:
                        # Only a failed request is worth retrying: a valid answer
                        # without 'info' means the panel simply has no metadata
                        metadata_ok = False
                        logger.warning(f"Failed to fetch info for movie {stream_id}: {e}")

                    cat_name = cat_map.get(cat_id, "Uncategorized")
                    target_info = fm.get_movie_target_info(movie, cat_name, prefix_regex, format_date, clean_name, use_category_folders)
                    
                    fm.ensure_directory(target_info["cat_dir"])
                    if target_info["target_dir"] != target_info["cat_dir"]:
                        fm.ensure_directory(target_info["target_dir"])
                    
                    strm_path = os.path.join(target_info["target_dir"], f"{target_info['filename_base']}.strm")
                    nfo_path = os.path.join(target_info["target_dir"], f"{target_info['filename_base']}.nfo")
                    
                    url = xc.get_stream_url("movie", str(stream_id), ext)
                    
                    if await fm.write_strm(strm_path, url):
                        strm_written += 1

                    nfo_content = fm.generate_movie_nfo(movie, prefix_regex, format_date, clean_name)
                    # Metadata fetch failed: never downgrade an existing NFO,
                    # it would only touch its mtime and make Jellyfin rescan
                    await fm.write_nfo(nfo_path, nfo_content, skip_if_exists=not metadata_ok)

                    # Update Cache
                    # We need to lock DB access or handle it after gather?
                    # Ideally accumulate results and bulk update, but for safety lets return data
                    return {
                        'action': 'update_cache',
                        'metadata_ok': metadata_ok,
                        'data': {
                            'stream_id': stream_id,
                            'name': name,
                            'category_id': cat_id,
                            'container_extension': ext,
                            'tmdb_id': str(tmdb_id) if tmdb_id else None
                        }
                    }

                except Exception as e:
                    logger.error(f"Error processing movie {movie.get('name')}: {e}")
                    return None

        # Execute in chunks to avoid memory explosion if list is huge
        # But for 10 concurrent, direct gather is fine usually.
        # Let's process in batches of 50 to update DB incrementally
        total_processed = 0
        metadata_failures = 0
        chunk_size = 50
        
        for i in range(0, len(to_add_update), chunk_size):
            chunk = to_add_update[i:i + chunk_size]
            results = await asyncio.gather(*[process_single_movie(m) for m in chunk])
            
            for res in results:
                if res and res['action'] == 'update_cache':
                    d = res['data']
                    if not res.get('metadata_ok', True):
                        # Keep it out of the cache: otherwise the next sync sees
                        # it as up to date and the NFO stays metadata-less forever
                        metadata_failures += 1
                        continue

                    cached = cached_movies.get(d['stream_id'])
                    if not cached:
                        cached = MovieCache(subscription_id=subscription_id, stream_id=d['stream_id'])
                        db.add(cached)
                    
                    cached.name = d['name']
                    cached.category_id = d['category_id']
                    cached.container_extension = d['container_extension']
                    cached.tmdb_id = d['tmdb_id']
            
            db.commit() # Commit every chunk

        if metadata_failures:
            logger.warning(
                f"{metadata_failures} movies written without metadata, "
                f"not cached so the next sync retries them"
            )

        logger.info(
            f"Movies sync: {len(to_add_update)} movies added/updated, "
            f"{len(to_delete)} deleted, {strm_written} STRM files written"
        )

        sync_state.items_added = len(to_add_update)
        sync_state.items_deleted = len(to_delete)
        sync_state.status = SyncStatus.SUCCESS
        db.commit()

        # Trigger Jellyfin library refresh
        trigger_jellyfin_refresh(db, "movies")

        # Counters are movie-based here, one STRM file per movie
        return {
            "items_added": len(to_add_update),
            "items_deleted": len(to_delete),
            "files_written": strm_written,
        }

    except Exception as e:
        logger.exception("Error syncing movies")
        sync_state.status = SyncStatus.FAILED
        sync_state.error_message = str(e)
        db.commit()
        raise

async def process_series(db: Session, xc: XtreamClient, fm: FileManager, subscription_id: int):
    # Get settings
    from app.models.settings import SettingsModel
    settings_rows = db.query(SettingsModel).all()
    settings = {s.key: s.value for s in settings_rows}

    prefix_regex = settings.get("PREFIX_REGEX")
    format_date = settings.get("FORMAT_DATE_IN_TITLE") == "true"
    clean_name = settings.get("CLEAN_NAME") == "true"

    use_season_folders = settings.get("SERIES_USE_SEASON_FOLDERS", "true") == "true"
    include_series_name = settings.get("SERIES_INCLUDE_NAME_IN_FILENAME", "false") == "true"
    use_category_folders = settings.get("SERIES_USE_CATEGORY_FOLDERS", "true") == "true"

    # Update status
    sync_state = db.query(SyncState).filter(
        SyncState.subscription_id == subscription_id,
        SyncState.type == SyncType.SERIES
    ).first()

    if not sync_state:
        sync_state = SyncState(subscription_id=subscription_id, type=SyncType.SERIES)
        db.add(sync_state)

    sync_state.status = SyncStatus.RUNNING
    sync_state.last_sync = datetime.utcnow()
    db.commit()

    try:
        categories = await xc.get_series_categories()
        cat_map = {c['category_id']: c['category_name'] for c in categories}

        all_series = await xc.get_series()

        # Filter by selected categories if any
        selected_cats = db.query(SelectedCategory).filter(
            SelectedCategory.subscription_id == subscription_id,
            SelectedCategory.type == "series"
        ).all()

        if selected_cats:
            selected_ids = {s.category_id for s in selected_cats}
            all_series = [s for s in all_series if s['category_id'] in selected_ids]

        cached_series = {s.series_id: s for s in db.query(SeriesCache).filter(SeriesCache.subscription_id == subscription_id).all()}

        # Load episode cache for this subscription
        # Key: (series_id, episode_id) -> EpisodeCache
        all_cached_episodes = db.query(EpisodeCache).filter(
            EpisodeCache.subscription_id == subscription_id
        ).all()
        cached_episodes = {(e.series_id, e.episode_id): e for e in all_cached_episodes}

        # Same rows indexed per series, to spot the episodes that vanished
        cached_eps_by_series = defaultdict(dict)
        for cached_ep in all_cached_episodes:
            cached_eps_by_series[cached_ep.series_id][cached_ep.episode_id] = cached_ep

        to_delete = []
        current_ids = set()
        # Counters are episode-based here, one STRM file per episode
        episodes_deleted = 0
        strm_written = 0

        for series in all_series:
            series_id = int(series['series_id'])
            current_ids.add(series_id)

        for series_id, cached in cached_series.items():
            if series_id not in current_ids:
                to_delete.append(cached)

        # Deletions
        for series in to_delete:
            cat_name = cat_map.get(series.category_id, "Uncategorized")
            target_info = fm.get_series_target_info(
                {"name": series.name, "tmdb": series.tmdb_id},
                cat_name, prefix_regex, format_date, clean_name, use_category_folders
            )

            if os.path.exists(target_info["series_dir"]):
                shutil.rmtree(target_info["series_dir"])

            await fm.delete_directory_if_empty(target_info["cat_dir"])

            # Delete episode cache for this series
            episodes_deleted += db.query(EpisodeCache).filter(
                EpisodeCache.subscription_id == subscription_id,
                EpisodeCache.series_id == series.series_id
            ).delete()

            db.delete(series)

        db.commit()

        # Process ALL selected series (not just new/changed)
        # Episode cache will prevent unnecessary file writes
        parallelism = _int_setting(settings, "SYNC_PARALLELISM_SERIES", DEFAULT_PARALLELISM["SYNC_PARALLELISM_SERIES"])
        batch_size = parallelism
        semaphore = asyncio.Semaphore(batch_size)

        # Track statistics
        total_episodes_added = 0
        total_episodes_skipped = 0

        async def process_single_series(series):
            nonlocal total_episodes_added, total_episodes_skipped, strm_written, episodes_deleted
            async with semaphore:
                try:
                    series_id = int(series['series_id'])
                    name = series['name']
                    cat_id = series['category_id']
                    tmdb_id = series.get('tmdb')

                    # Fetch Episodes and Info
                    info_response = await xc.get_series_info(str(series_id))
                    series_info = info_response.get('info', {})
                    episodes_data = info_response.get('episodes', {})

                    if isinstance(episodes_data, list):
                        episodes_data = {}

                    if series_info.get('tmdb_id'):
                         tmdb_id = series_info.get('tmdb_id')
                         series['tmdb'] = tmdb_id # For NFO

                    cat_name = cat_map.get(cat_id, "Uncategorized")
                    target_info = fm.get_series_target_info(series, cat_name, prefix_regex, format_date, clean_name, use_category_folders)

                    if use_category_folders:
                        fm.ensure_directory(target_info["cat_dir"])

                    series_dir = target_info["series_dir"]
                    fm.ensure_directory(series_dir)

                    # Create tvshow.nfo (will be skipped if unchanged)
                    nfo_path = f"{series_dir}/tvshow.nfo"
                    await fm.write_nfo(nfo_path, fm.generate_show_nfo(series, prefix_regex, format_date, clean_name))

                    episodes_to_cache = []
                    current_ep_ids = set()

                    for season_key, episodes in episodes_data.items():
                        season_num = int(season_key)

                        # SEASON FOLDERS LOGIC
                        if use_season_folders:
                            season_dir_name = f"Season {season_num:02d}"
                            current_dir = f"{series_dir}/{season_dir_name}"
                        else:
                            current_dir = series_dir

                        fm.ensure_directory(current_dir)

                        for ep in episodes:
                            ep_num = int(ep['episode_num'])
                            ep_id = int(ep['id'])
                            container = ep['container_extension']
                            title = ep.get('title', '')
                            current_ep_ids.add(ep_id)

                            # Check episode cache - skip if unchanged
                            cache_key = (series_id, ep_id)
                            cached_ep = cached_episodes.get(cache_key)

                            if cached_ep:
                                # Episode exists in cache - check if changed
                                if (cached_ep.title == title and
                                    cached_ep.container_extension == container and
                                    cached_ep.season_num == season_num and
                                    cached_ep.episode_num == ep_num):
                                    # Episode unchanged, skip
                                    total_episodes_skipped += 1
                                    continue

                            # New or changed episode - process it
                            total_episodes_added += 1

                            filename = fm.build_episode_filename(
                                target_info['safe_series_name'], season_num, ep_num,
                                title, container, include_series_name
                            )

                            strm_path = f"{current_dir}/{filename}.strm"
                            url = xc.get_stream_url("series", str(ep_id), container)
                            if await fm.write_strm(strm_path, url):
                                strm_written += 1

                            # Episode NFO
                            ep_nfo_path = f"{current_dir}/{filename}.nfo"
                            ep_nfo_content = fm.generate_episode_nfo(ep, name, season_num, ep_num)
                            await fm.write_nfo(ep_nfo_path, ep_nfo_content)

                            # Queue episode for cache update
                            episodes_to_cache.append({
                                'episode_id': ep_id,
                                'season_num': season_num,
                                'episode_num': ep_num,
                                'title': ep.get('title', ''),
                                'container_extension': container
                            })

                    # Episodes that vanished from the panel: drop their files
                    deleted_ep_ids = []

                    for stale_id, stale_ep in cached_eps_by_series.get(series_id, {}).items():
                        if stale_id in current_ep_ids:
                            continue

                        stale_season = stale_ep.season_num or 0
                        if use_season_folders:
                            stale_dir = f"{series_dir}/Season {stale_season:02d}"
                        else:
                            stale_dir = series_dir

                        stale_filename = fm.build_episode_filename(
                            target_info['safe_series_name'], stale_season, stale_ep.episode_num or 0,
                            stale_ep.title, stale_ep.container_extension, include_series_name
                        )

                        await fm.delete_file(f"{stale_dir}/{stale_filename}.strm")
                        await fm.delete_file(f"{stale_dir}/{stale_filename}.nfo")
                        await fm.delete_directory_if_empty(stale_dir)

                        deleted_ep_ids.append(stale_id)
                        episodes_deleted += 1

                    return {
                        'action': 'update_cache',
                        'data': {
                            'series_id': series_id,
                            'name': name,
                            'category_id': cat_id,
                            'tmdb_id': str(tmdb_id) if tmdb_id else None,
                            'episodes': episodes_to_cache,
                            'deleted_episode_ids': deleted_ep_ids
                        }
                    }
                except Exception as e:
                     logger.error(f"Error processing series {series.get('name')}: {e}")
                     return None

        chunk_size = 20
        for i in range(0, len(all_series), chunk_size):
            chunk = all_series[i:i + chunk_size]
            results = await asyncio.gather(*[process_single_series(s) for s in chunk])

            for res in results:
                if res and res['action'] == 'update_cache':
                    d = res['data']
                    series_id = d['series_id']

                    # Update series cache
                    cached = cached_series.get(series_id)
                    if not cached:
                        cached = SeriesCache(subscription_id=subscription_id, series_id=series_id)
                        db.add(cached)
                        cached_series[series_id] = cached

                    cached.name = d['name']
                    cached.category_id = d['category_id']
                    cached.tmdb_id = d['tmdb_id']

                    # Update episode cache for new/changed episodes
                    for ep_data in d.get('episodes', []):
                        cache_key = (series_id, ep_data['episode_id'])
                        cached_ep = cached_episodes.get(cache_key)

                        if not cached_ep:
                            cached_ep = EpisodeCache(
                                subscription_id=subscription_id,
                                series_id=series_id,
                                episode_id=ep_data['episode_id']
                            )
                            db.add(cached_ep)
                            cached_episodes[cache_key] = cached_ep

                        cached_ep.season_num = ep_data['season_num']
                        cached_ep.episode_num = ep_data['episode_num']
                        cached_ep.title = ep_data['title']
                        cached_ep.container_extension = ep_data['container_extension']

                    # Forget the episodes whose files were just removed
                    for stale_id in d.get('deleted_episode_ids', []):
                        stale_ep = cached_episodes.pop((series_id, stale_id), None)
                        cached_eps_by_series.get(series_id, {}).pop(stale_id, None)
                        if stale_ep is not None:
                            db.delete(stale_ep)

            db.commit()

        logger.info(
            f"Series sync: {total_episodes_added} episodes added/updated, "
            f"{total_episodes_skipped} skipped (unchanged), "
            f"{episodes_deleted} deleted with {len(to_delete)} series, "
            f"{strm_written} STRM files written"
        )

        sync_state.items_added = total_episodes_added
        sync_state.items_deleted = episodes_deleted
        sync_state.status = SyncStatus.SUCCESS
        db.commit()

        # Trigger Jellyfin library refresh
        trigger_jellyfin_refresh(db, "series")

        return {
            "items_added": total_episodes_added,
            "items_deleted": episodes_deleted,
            "files_written": strm_written,
        }

    except Exception as e:
        logger.exception("Error syncing series")
        sync_state.status = SyncStatus.FAILED
        sync_state.error_message = str(e)
        db.commit()
        raise

@celery_app.task
def sync_movies_task(subscription_id: int, execution_id: int = None):
    db = SessionLocal()
    execution = None
    try:
        sub = db.query(Subscription).filter(Subscription.id == subscription_id).first()
        if not sub:
            logger.error(f"Subscription {subscription_id} not found")
            return "Subscription not found"

        if not sub.is_active:
            logger.info(f"Subscription {sub.name} is inactive")
            return "Subscription inactive"

        # Mark any stale running executions as interrupted
        stale_executions = db.query(ScheduleExecution).filter(
            ScheduleExecution.subscription_id == subscription_id,
            ScheduleExecution.sync_type == "movies",
            ScheduleExecution.status == ExecutionStatus.RUNNING
        ).all()
        for stale in stale_executions:
            stale.status = ExecutionStatus.INTERRUPTED
            stale.completed_at = datetime.utcnow()
            stale.error_message = "Interrupted by new sync"
        if stale_executions:
            db.commit()

        # Get or create execution record
        if execution_id:
            execution = db.query(ScheduleExecution).filter(ScheduleExecution.id == execution_id).first()
        else:
            # Manual sync - create execution record
            execution = ScheduleExecution(
                subscription_id=subscription_id,
                sync_type="movies",
                status=ExecutionStatus.RUNNING
            )
            db.add(execution)
            db.commit()

        xc = build_xtream_client(db, sub, "SYNC_PARALLELISM_MOVIES")
        fm = FileManager(sub.movies_dir)

        stats = asyncio.run(_run_and_close(process_movies(db, xc, fm, subscription_id), xc)) or {}

        # Refresh session to get updated sync_state values
        db.expire_all()

        # Update execution record on success
        if execution:
            execution.status = ExecutionStatus.SUCCESS
            execution.completed_at = datetime.utcnow()
            execution.items_added = stats.get("items_added", 0)
            execution.items_deleted = stats.get("items_deleted", 0)
            execution.files_written = stats.get("files_written", 0)
            # Kept in sync for the screens still reading items_processed
            execution.items_processed = execution.items_added + execution.items_deleted
            db.commit()

        return f"Movies synced successfully for {sub.name}"
    except Exception as e:
        logger.exception(f"Error syncing movies for subscription {subscription_id}")
        if execution:
            execution.status = ExecutionStatus.FAILED
            execution.error_message = str(e)
            execution.completed_at = datetime.utcnow()
            db.commit()
        raise
    finally:
        db.close()

@celery_app.task
def sync_series_task(subscription_id: int, execution_id: int = None):
    db = SessionLocal()
    execution = None
    try:
        sub = db.query(Subscription).filter(Subscription.id == subscription_id).first()
        if not sub:
            logger.error(f"Subscription {subscription_id} not found")
            return "Subscription not found"

        if not sub.is_active:
            logger.info(f"Subscription {sub.name} is inactive")
            return "Subscription inactive"

        # Mark any stale running executions as interrupted
        stale_executions = db.query(ScheduleExecution).filter(
            ScheduleExecution.subscription_id == subscription_id,
            ScheduleExecution.sync_type == "series",
            ScheduleExecution.status == ExecutionStatus.RUNNING
        ).all()
        for stale in stale_executions:
            stale.status = ExecutionStatus.INTERRUPTED
            stale.completed_at = datetime.utcnow()
            stale.error_message = "Interrupted by new sync"
        if stale_executions:
            db.commit()

        # Get or create execution record
        if execution_id:
            execution = db.query(ScheduleExecution).filter(ScheduleExecution.id == execution_id).first()
        else:
            # Manual sync - create execution record
            execution = ScheduleExecution(
                subscription_id=subscription_id,
                sync_type="series",
                status=ExecutionStatus.RUNNING
            )
            db.add(execution)
            db.commit()

        xc = build_xtream_client(db, sub, "SYNC_PARALLELISM_SERIES")
        fm = FileManager(sub.series_dir)

        stats = asyncio.run(_run_and_close(process_series(db, xc, fm, subscription_id), xc)) or {}

        # Refresh session to get updated sync_state values
        db.expire_all()

        # Update execution record on success
        if execution:
            execution.status = ExecutionStatus.SUCCESS
            execution.completed_at = datetime.utcnow()
            execution.items_added = stats.get("items_added", 0)
            execution.items_deleted = stats.get("items_deleted", 0)
            execution.files_written = stats.get("files_written", 0)
            # Kept in sync for the screens still reading items_processed
            execution.items_processed = execution.items_added + execution.items_deleted
            db.commit()

        return f"Series synced successfully for {sub.name}"
    except Exception as e:
        logger.exception(f"Error syncing series for subscription {subscription_id}")
        if execution:
            execution.status = ExecutionStatus.FAILED
            execution.error_message = str(e)
            execution.completed_at = datetime.utcnow()
            db.commit()
        raise
    finally:
        db.close()

@celery_app.task
def check_schedules_task():
    """Check schedules and trigger syncs if needed"""
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        # Get enabled schedules that are due
        schedules = db.query(Schedule).filter(
            Schedule.enabled == True,
            Schedule.next_run <= now
        ).all()

        for schedule in schedules:
            # Create execution record
            execution = ScheduleExecution(
                schedule_id=schedule.id,
                subscription_id=schedule.subscription_id,
                sync_type=schedule.type.value if hasattr(schedule.type, 'value') else str(schedule.type),
                status=ExecutionStatus.RUNNING
            )
            db.add(execution)
            db.commit()

            try:
                # Trigger appropriate sync with execution_id
                # The sync task will update the execution status
                if schedule.type == ScheduleSyncType.MOVIES:
                    sync_movies_task.apply_async(args=[schedule.subscription_id, execution.id])
                else:
                    sync_series_task.apply_async(args=[schedule.subscription_id, execution.id])

            except Exception as e:
                logger.exception(f"Error triggering scheduled sync for {schedule.type}")
                execution.status = ExecutionStatus.FAILED
                execution.error_message = str(e)
                execution.completed_at = datetime.utcnow()
                db.commit()

            # Update schedule for next run
            schedule.last_run = now
            schedule.next_run = schedule.calculate_next_run()
            db.commit()

    finally:
        db.close()
