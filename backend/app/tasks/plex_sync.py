"""
Celery tasks for Plex media synchronization.

Syncs movies and series from Plex servers to STRM/NFO files.

@description Follows the same pattern as sync.py for Xtream:
- Fetches media from Plex libraries
- Detects changes via cache
- Generates STRM and NFO files using FileManager
"""
import asyncio
import ast
import os
import shutil
from collections import defaultdict
from app.core.celery_app import celery_app
from sqlalchemy.orm import Session
from app.db.session import SessionLocal
from app.models.plex_account import PlexAccount
from app.models.plex_server import PlexServer
from app.models.plex_library import PlexLibrary
from app.models.plex_sync_state import PlexSyncState
from app.models.plex_cache import PlexMovieCache, PlexSeriesCache, PlexEpisodeCache
from app.models.plex_schedule import PlexSchedule, PlexSyncType as PlexScheduleSyncType
from app.models.plex_schedule_execution import PlexScheduleExecution, PlexExecutionStatus
from app.models.settings import SettingsModel
from app.services.plex import PlexClient
from app.services.file_manager import FileManager
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


def normalize_year(year):
    """
    Year as it is stored in cache: a string, or None when Plex has none.

    Both sides of a change detection must go through this, otherwise a movie
    without a year compares None against "None" and looks changed forever.
    """
    return str(year) if year else None


def build_plex_folder_name(fm: FileManager, title: str, year, tmdb_id) -> str:
    """Folder name of a Plex movie or show, shared by creation and cleanup"""
    safe_title = fm.sanitize_name(title or "Unknown")

    if tmdb_id:
        return f"{safe_title} ({year}) {{tmdb-{tmdb_id}}}" if year else f"{safe_title} {{tmdb-{tmdb_id}}}"

    return f"{safe_title} ({year})" if year else safe_title


def cached_item_dir(fm: FileManager, cached_item, library, use_library_folders: bool) -> str:
    """
    Rebuild the directory of an already synced item from its cache row.

    The cache stores the GUID dict as a string, hence the literal_eval.
    """
    tmdb_id = None
    if cached_item.guid:
        try:
            guid = ast.literal_eval(cached_item.guid)
            if isinstance(guid, dict):
                tmdb_id = guid.get("tmdb")
        except (ValueError, SyntaxError):
            logger.warning(f"Unreadable cached GUID for {cached_item.title}: {cached_item.guid}")

    folder_name = build_plex_folder_name(fm, cached_item.title, cached_item.year, tmdb_id)

    if use_library_folders and library is not None:
        return os.path.join(fm.output_dir, fm.sanitize_name(library.title), folder_name)

    return os.path.join(fm.output_dir, folder_name)


def generate_plex_movie_nfo(movie: dict, fm: FileManager) -> str:
    """
    Generate NFO content for a Plex movie.

    @param movie Movie data dict from PlexClient
    @param fm FileManager for XML escaping
    @returns NFO XML content string
    """
    guid = movie.get("guid", {})

    nfo = '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>\n<movie>\n'
    nfo += f'  <title>{fm._escape_xml(movie.get("title", "Unknown"))}</title>\n'

    if movie.get("original_title"):
        nfo += f'  <originaltitle>{fm._escape_xml(movie["original_title"])}</originaltitle>\n'

    if guid.get("tmdb"):
        nfo += f'  <tmdbid>{guid["tmdb"]}</tmdbid>\n'
        nfo += f'  <uniqueid type="tmdb" default="true">{guid["tmdb"]}</uniqueid>\n'
    if guid.get("imdb"):
        nfo += f'  <uniqueid type="imdb">{guid["imdb"]}</uniqueid>\n'

    if movie.get("summary"):
        nfo += f'  <plot>{fm._escape_xml(movie["summary"])}</plot>\n'
        nfo += f'  <outline>{fm._escape_xml(movie["summary"][:200])}</outline>\n'

    if movie.get("year"):
        nfo += f'  <year>{movie["year"]}</year>\n'
        nfo += f'  <premiered>{movie["year"]}-01-01</premiered>\n'

    if movie.get("rating"):
        try:
            r_val = float(movie["rating"])
            nfo += '  <ratings>\n'
            nfo += f'    <rating name="plex" default="true"><value>{r_val:.1f}</value></rating>\n'
            nfo += '  </ratings>\n'
            nfo += f'  <userrating>{int(round(r_val))}</userrating>\n'
        except (ValueError, TypeError):
            pass

    for genre in movie.get("genres", []):
        nfo += f'  <genre>{fm._escape_xml(genre)}</genre>\n'

    for director in movie.get("directors", []):
        nfo += f'  <director>{fm._escape_xml(director)}</director>\n'

    for actor in movie.get("actors", []):
        nfo += f'  <actor><name>{fm._escape_xml(actor)}</name></actor>\n'

    if movie.get("duration"):
        runtime = movie["duration"] // 60000  # ms to minutes
        nfo += f'  <runtime>{runtime}</runtime>\n'

    # Media info
    media = movie.get("media", {})
    if media:
        nfo += '  <fileinfo>\n    <streamdetails>\n'
        nfo += '      <video>\n'
        if media.get("video_codec"):
            nfo += f'        <codec>{fm._escape_xml(media["video_codec"])}</codec>\n'
        if media.get("resolution"):
            nfo += f'        <aspect>{fm._escape_xml(media["resolution"])}</aspect>\n'
        nfo += '      </video>\n'
        if media.get("audio_codec"):
            nfo += '      <audio>\n'
            nfo += f'        <codec>{fm._escape_xml(media["audio_codec"])}</codec>\n'
            nfo += '      </audio>\n'
        nfo += '    </streamdetails>\n  </fileinfo>\n'

    # Artwork (would need Plex server URL to construct full path)
    # For now, skip as STRM players usually fetch from TMDB

    nfo += '</movie>'
    return nfo


def generate_plex_show_nfo(show: dict, fm: FileManager) -> str:
    """
    Generate NFO content for a Plex TV show.

    @param show Show data dict from PlexClient
    @param fm FileManager for XML escaping
    @returns NFO XML content string
    """
    guid = show.get("guid", {})

    nfo = '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>\n<tvshow>\n'
    nfo += f'  <title>{fm._escape_xml(show.get("title", "Unknown"))}</title>\n'

    if show.get("original_title"):
        nfo += f'  <originaltitle>{fm._escape_xml(show["original_title"])}</originaltitle>\n'

    if guid.get("tmdb"):
        nfo += f'  <tmdbid>{guid["tmdb"]}</tmdbid>\n'
        nfo += f'  <uniqueid type="tmdb" default="true">{guid["tmdb"]}</uniqueid>\n'
    if guid.get("tvdb"):
        nfo += f'  <uniqueid type="tvdb">{guid["tvdb"]}</uniqueid>\n'
    if guid.get("imdb"):
        nfo += f'  <uniqueid type="imdb">{guid["imdb"]}</uniqueid>\n'

    if show.get("summary"):
        nfo += f'  <plot>{fm._escape_xml(show["summary"])}</plot>\n'

    if show.get("year"):
        nfo += f'  <year>{show["year"]}</year>\n'
        nfo += f'  <premiered>{show["year"]}-01-01</premiered>\n'

    if show.get("rating"):
        try:
            r_val = float(show["rating"])
            nfo += '  <ratings>\n'
            nfo += f'    <rating name="plex" default="true"><value>{r_val:.1f}</value></rating>\n'
            nfo += '  </ratings>\n'
        except (ValueError, TypeError):
            pass

    for genre in show.get("genres", []):
        nfo += f'  <genre>{fm._escape_xml(genre)}</genre>\n'

    for actor in show.get("actors", []):
        nfo += f'  <actor><name>{fm._escape_xml(actor)}</name></actor>\n'

    nfo += '</tvshow>'
    return nfo


def generate_plex_episode_nfo(episode: dict, show_title: str, fm: FileManager) -> str:
    """
    Generate NFO content for a Plex episode.

    @param episode Episode data dict from PlexClient
    @param show_title Parent show title
    @param fm FileManager for XML escaping
    @returns NFO XML content string
    """
    nfo = '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>\n<episodedetails>\n'
    nfo += f'  <title>{fm._escape_xml(episode.get("title", "Unknown"))}</title>\n'
    nfo += f'  <showtitle>{fm._escape_xml(show_title)}</showtitle>\n'
    nfo += f'  <season>{episode.get("season_num", 0)}</season>\n'
    nfo += f'  <episode>{episode.get("episode_num", 0)}</episode>\n'

    if episode.get("summary"):
        nfo += f'  <plot>{fm._escape_xml(episode["summary"])}</plot>\n'

    if episode.get("duration"):
        runtime = episode["duration"] // 60000  # ms to minutes
        nfo += f'  <runtime>{runtime}</runtime>\n'

    # Media info
    media = episode.get("media", {})
    if media:
        nfo += '  <fileinfo>\n    <streamdetails>\n'
        nfo += '      <video>\n'
        if media.get("video_codec"):
            nfo += f'        <codec>{fm._escape_xml(media["video_codec"])}</codec>\n'
        nfo += '      </video>\n'
        nfo += '    </streamdetails>\n  </fileinfo>\n'

    nfo += '</episodedetails>'
    return nfo


async def process_plex_movies(db: Session, client: PlexClient, plex_server, fm: FileManager, server_id: int):
    """
    Process movies from selected Plex libraries.

    @param db Database session
    @param client PlexClient instance
    @param plex_server Connected PlexServer instance
    @param fm FileManager for file operations
    @param server_id Database server ID
    """
    settings = {s.key: s.value for s in db.query(SettingsModel).all()}
    use_library_folders = settings.get("PLEX_USE_LIBRARY_FOLDERS", "true") == "true"
    proxy_base_url = settings.get("PLEX_PROXY_BASE_URL", "http://localhost:8000")
    shared_key = settings.get("PLEX_SHARED_KEY", "")

    # Get sync state
    sync_state = db.query(PlexSyncState).filter(
        PlexSyncState.server_id == server_id,
        PlexSyncState.type == "movies"
    ).first()

    if not sync_state:
        sync_state = PlexSyncState(server_id=server_id, type="movies")
        db.add(sync_state)

    sync_state.status = "running"
    sync_state.last_sync = datetime.utcnow()
    sync_state.error_message = None
    db.commit()

    try:
        # Get selected movie libraries
        libraries = db.query(PlexLibrary).filter(
            PlexLibrary.server_id == server_id,
            PlexLibrary.type == "movie",
            PlexLibrary.is_selected == True
        ).all()

        if not libraries:
            sync_state.status = "success"
            sync_state.items_added = 0
            sync_state.items_deleted = 0
            db.commit()
            return {"items_added": 0, "items_deleted": 0, "files_written": 0}

        # Counters are movie-based here, one STRM file per movie
        total_added = 0
        total_deleted = 0
        strm_written = 0

        for library in libraries:
            logger.info(f"Processing Plex movie library: {library.title}")

            # Fetch movies from this library
            movies = client.get_movies(plex_server, library.library_key)

            # Get cached movies for this library
            cached_movies = {
                m.plex_key: m for m in db.query(PlexMovieCache).filter(
                    PlexMovieCache.server_id == server_id,
                    PlexMovieCache.library_id == library.id
                ).all()
            }

            to_add_update = []
            current_keys = set()

            for movie in movies:
                key = movie["key"]
                current_keys.add(key)

                cached = cached_movies.get(key)
                if not cached:
                    # New movie - needs processing
                    to_add_update.append(movie)
                else:
                    # Existing movie - only reprocess if critical metadata changed
                    # (title, year, or TMDB ID affect folder/filename)
                    guid = movie.get("guid", {})
                    new_tmdb = guid.get("tmdb")
                    cached_tmdb = None
                    if cached.guid:
                        try:
                            import ast
                            cached_guid = ast.literal_eval(cached.guid)
                            cached_tmdb = cached_guid.get("tmdb")
                        except Exception:
                            pass

                    if (cached.title != movie.get("title") or
                        cached.year != normalize_year(movie.get("year")) or
                        cached_tmdb != new_tmdb):
                        to_add_update.append(movie)

            # Detect deletions
            to_delete = [c for k, c in cached_movies.items() if k not in current_keys]

            # Process deletions: the movie is gone from Plex, drop its folder
            for cached_movie in to_delete:
                movie_dir = cached_item_dir(fm, cached_movie, library, use_library_folders)
                try:
                    if os.path.isdir(movie_dir):
                        shutil.rmtree(movie_dir)
                except OSError as e:
                    logger.warning(f"Could not remove {movie_dir}: {e}")

                db.delete(cached_movie)
                total_deleted += 1

            db.commit()

            # Process additions/updates
            for movie in to_add_update:
                try:
                    guid = movie.get("guid", {})
                    tmdb_id = guid.get("tmdb")

                    title = movie.get("title", "Unknown")
                    year = movie.get("year", "")

                    folder_name = build_plex_folder_name(fm, title, year, tmdb_id)

                    # Determine target directory
                    if use_library_folders:
                        safe_lib = fm.sanitize_name(library.title)
                        target_dir = os.path.join(fm.output_dir, safe_lib, folder_name)
                    else:
                        target_dir = os.path.join(fm.output_dir, folder_name)

                    fm.ensure_directory(target_dir)

                    # Build proxy URL for streaming (includes shared key for authentication)
                    # The /stream.m3u8 suffix helps ExoPlayer-based clients detect HLS content
                    rating_key = movie.get("rating_key")
                    key_param = f"?key={shared_key}" if shared_key else ""
                    stream_url = f"{proxy_base_url}/api/v1/plex/proxy/{server_id}/{rating_key}/stream.m3u8{key_param}"

                    # Write STRM
                    strm_path = os.path.join(target_dir, f"{folder_name}.strm")
                    if await fm.write_strm(strm_path, stream_url):
                        strm_written += 1

                    # Generate and write NFO
                    nfo_content = generate_plex_movie_nfo(movie, fm)
                    nfo_path = os.path.join(target_dir, f"{folder_name}.nfo")
                    await fm.write_nfo(nfo_path, nfo_content)

                    # Update cache
                    cached = cached_movies.get(movie["key"])
                    if not cached:
                        cached = PlexMovieCache(
                            server_id=server_id,
                            library_id=library.id,
                            plex_key=movie["key"]
                        )
                        db.add(cached)

                    cached.title = title
                    cached.year = normalize_year(year)
                    cached.guid = str(guid)
                    cached.updated_at = movie.get("updated_at")

                    total_added += 1

                except Exception as e:
                    logger.error(f"Error processing Plex movie {movie.get('title')}: {e}")
                    continue

            db.commit()

            # Update library last sync
            library.last_sync = datetime.utcnow()
            db.commit()

        logger.info(
            f"Plex movies sync: {total_added} movies added/updated, "
            f"{total_deleted} deleted, {strm_written} STRM files written"
        )

        sync_state.items_added = total_added
        sync_state.items_deleted = total_deleted
        sync_state.status = "success"
        db.commit()

        return {
            "items_added": total_added,
            "items_deleted": total_deleted,
            "files_written": strm_written,
        }

    except Exception as e:
        logger.exception("Error syncing Plex movies")
        sync_state.status = "failed"
        sync_state.error_message = str(e)
        db.commit()
        raise


async def process_plex_series(db: Session, client: PlexClient, plex_server, fm: FileManager, server_id: int):
    """
    Process series from selected Plex libraries.

    @param db Database session
    @param client PlexClient instance
    @param plex_server Connected PlexServer instance
    @param fm FileManager for file operations
    @param server_id Database server ID
    """
    settings = {s.key: s.value for s in db.query(SettingsModel).all()}
    use_library_folders = settings.get("PLEX_USE_LIBRARY_FOLDERS", "true") == "true"
    use_season_folders = settings.get("SERIES_USE_SEASON_FOLDERS", "true") == "true"
    proxy_base_url = settings.get("PLEX_PROXY_BASE_URL", "http://localhost:8000")
    shared_key = settings.get("PLEX_SHARED_KEY", "")

    # Get sync state
    sync_state = db.query(PlexSyncState).filter(
        PlexSyncState.server_id == server_id,
        PlexSyncState.type == "series"
    ).first()

    if not sync_state:
        sync_state = PlexSyncState(server_id=server_id, type="series")
        db.add(sync_state)

    sync_state.status = "running"
    sync_state.last_sync = datetime.utcnow()
    sync_state.error_message = None
    db.commit()

    try:
        # Get selected show libraries
        libraries = db.query(PlexLibrary).filter(
            PlexLibrary.server_id == server_id,
            PlexLibrary.type == "show",
            PlexLibrary.is_selected == True
        ).all()

        if not libraries:
            sync_state.status = "success"
            sync_state.items_added = 0
            sync_state.items_deleted = 0
            db.commit()
            return {"items_added": 0, "items_deleted": 0, "files_written": 0}

        # Load episode cache for this server
        # Key: plex_key -> PlexEpisodeCache
        all_cached_episodes = db.query(PlexEpisodeCache).filter(
            PlexEpisodeCache.server_id == server_id
        ).all()
        cached_episodes = {e.plex_key: e for e in all_cached_episodes}

        # Same rows indexed per show, to spot the episodes that vanished
        cached_eps_by_show = defaultdict(dict)
        for cached_ep in all_cached_episodes:
            cached_eps_by_show[cached_ep.series_key][cached_ep.plex_key] = cached_ep

        # Counters are episode-based here, one STRM file per episode
        total_episodes_added = 0
        total_episodes_skipped = 0
        total_episodes_deleted = 0
        total_series_deleted = 0
        total_series_skipped = 0
        strm_written = 0

        for library in libraries:
            logger.info(f"Processing Plex TV library: {library.title}")

            # Fetch shows from this library
            shows = client.get_shows(plex_server, library.library_key)

            # Get cached series for this library
            cached_series = {
                s.plex_key: s for s in db.query(PlexSeriesCache).filter(
                    PlexSeriesCache.server_id == server_id,
                    PlexSeriesCache.library_id == library.id
                ).all()
            }

            current_keys = set()
            for show in shows:
                current_keys.add(show["key"])

            # Detect deletions
            to_delete = [c for k, c in cached_series.items() if k not in current_keys]

            # Process deletions: the show is gone from Plex, drop its folder
            for cached_show in to_delete:
                show_dir = cached_item_dir(fm, cached_show, library, use_library_folders)
                try:
                    if os.path.isdir(show_dir):
                        shutil.rmtree(show_dir)
                except OSError as e:
                    logger.warning(f"Could not remove {show_dir}: {e}")

                db.delete(cached_show)
                # Also delete episodes
                total_episodes_deleted += db.query(PlexEpisodeCache).filter(
                    PlexEpisodeCache.server_id == server_id,
                    PlexEpisodeCache.series_key == cached_show.plex_key
                ).delete()
                total_series_deleted += 1

            db.commit()

            # Process ALL shows - episode cache will skip unchanged episodes
            for show in shows:
                try:
                    guid = show.get("guid", {})
                    tmdb_id = guid.get("tmdb")

                    title = show.get("title", "Unknown")
                    year = show.get("year", "")

                    folder_name = build_plex_folder_name(fm, title, year, tmdb_id)

                    # Determine target directory
                    if use_library_folders:
                        safe_lib = fm.sanitize_name(library.title)
                        series_dir = os.path.join(fm.output_dir, safe_lib, folder_name)
                    else:
                        series_dir = os.path.join(fm.output_dir, folder_name)

                    fm.ensure_directory(series_dir)

                    # Write tvshow.nfo (will be skipped if unchanged)
                    show_nfo_path = os.path.join(series_dir, "tvshow.nfo")
                    show_nfo_content = generate_plex_show_nfo(show, fm)
                    await fm.write_nfo(show_nfo_path, show_nfo_content)

                    # Plex reports the show as unchanged: skip the episode
                    # fetch entirely. The episode cache below only avoids file
                    # writes, the API call happened on every sync regardless.
                    cached = cached_series.get(show["key"])
                    show_updated_at = show.get("updated_at")
                    show_leaf_count = show.get("leaf_count")
                    unchanged = (
                        cached is not None
                        and show_updated_at is not None
                        and show_leaf_count is not None
                        and cached.updated_at == show_updated_at
                        and cached.leaf_count == show_leaf_count
                    )

                    if unchanged:
                        total_series_skipped += 1
                    else:
                        # Fetch episodes
                        episodes_by_season = client.get_show_episodes(plex_server, show["key"])
                        current_ep_keys = set()

                        for season_num, episodes in episodes_by_season.items():
                            # Season folder
                            if use_season_folders:
                                season_dir = os.path.join(series_dir, f"Season {season_num:02d}")
                            else:
                                season_dir = series_dir

                            fm.ensure_directory(season_dir)

                            for episode in episodes:
                                ep_num = episode.get("episode_num", 0)
                                ep_title = episode.get("title", "")
                                ep_plex_key = episode.get("key")
                                ep_rating_key = episode.get("rating_key")
                                current_ep_keys.add(ep_plex_key)

                                # Check episode cache - skip if unchanged
                                cached_ep = cached_episodes.get(ep_plex_key)
                                if cached_ep:
                                    # Episode exists in cache - check if changed
                                    if (cached_ep.title == ep_title and
                                        cached_ep.season_num == season_num and
                                        cached_ep.episode_num == ep_num):
                                        # Episode unchanged, skip
                                        total_episodes_skipped += 1
                                        continue

                                # New or changed episode - process it
                                total_episodes_added += 1

                                # Format episode filename
                                filename = fm.build_episode_filename(
                                    "", season_num, ep_num, ep_title
                                )

                                # Build proxy URL for streaming
                                key_param = f"?key={shared_key}" if shared_key else ""
                                stream_url = f"{proxy_base_url}/api/v1/plex/proxy/{server_id}/{ep_rating_key}/stream.m3u8{key_param}"

                                # Write STRM
                                strm_path = os.path.join(season_dir, f"{filename}.strm")
                                if await fm.write_strm(strm_path, stream_url):
                                    strm_written += 1

                                # Write episode NFO
                                ep_nfo_path = os.path.join(season_dir, f"{filename}.nfo")
                                ep_nfo_content = generate_plex_episode_nfo(episode, title, fm)
                                await fm.write_nfo(ep_nfo_path, ep_nfo_content)

                                # Update episode cache
                                if not cached_ep:
                                    cached_ep = PlexEpisodeCache(
                                        server_id=server_id,
                                        series_key=show["key"],
                                        plex_key=ep_plex_key
                                    )
                                    db.add(cached_ep)
                                    cached_episodes[ep_plex_key] = cached_ep

                                cached_ep.season_num = season_num
                                cached_ep.episode_num = ep_num
                                cached_ep.title = ep_title

                        # Episodes that vanished from Plex: drop their files.
                        # An empty fetch is treated as a glitch, not as a show
                        # losing every episode, so nothing is removed then.
                        stale_candidates = cached_eps_by_show.get(show["key"], {}) if current_ep_keys else {}

                        for stale_key, stale_ep in list(stale_candidates.items()):
                            if stale_key in current_ep_keys:
                                continue

                            stale_season = stale_ep.season_num or 0
                            if use_season_folders:
                                stale_dir = os.path.join(series_dir, f"Season {stale_season:02d}")
                            else:
                                stale_dir = series_dir

                            stale_filename = fm.build_episode_filename(
                                "", stale_season, stale_ep.episode_num or 0, stale_ep.title
                            )

                            await fm.delete_file(os.path.join(stale_dir, f"{stale_filename}.strm"))
                            await fm.delete_file(os.path.join(stale_dir, f"{stale_filename}.nfo"))
                            await fm.delete_directory_if_empty(stale_dir)

                            cached_episodes.pop(stale_key, None)
                            cached_eps_by_show[show["key"]].pop(stale_key, None)
                            db.delete(stale_ep)
                            total_episodes_deleted += 1

                    # Update series cache
                    cached = cached_series.get(show["key"])
                    if not cached:
                        cached = PlexSeriesCache(
                            server_id=server_id,
                            library_id=library.id,
                            plex_key=show["key"]
                        )
                        db.add(cached)
                        cached_series[show["key"]] = cached

                    cached.title = title
                    cached.year = normalize_year(year)
                    cached.guid = str(guid)
                    cached.updated_at = show_updated_at
                    cached.leaf_count = show_leaf_count

                except Exception as e:
                    logger.error(f"Error processing Plex show {show.get('title')}: {e}")
                    continue

            db.commit()

            # Update library last sync
            library.last_sync = datetime.utcnow()
            db.commit()

        logger.info(
            f"Plex series sync: {total_episodes_added} episodes added/updated, "
            f"{total_episodes_skipped} skipped (unchanged), "
            f"{total_series_skipped} shows skipped without an API call, "
            f"{total_episodes_deleted} episodes deleted ({total_series_deleted} shows removed), "
            f"{strm_written} STRM files written"
        )

        sync_state.items_added = total_episodes_added
        sync_state.items_deleted = total_episodes_deleted
        sync_state.status = "success"
        db.commit()

        return {
            "items_added": total_episodes_added,
            "items_deleted": total_episodes_deleted,
            "files_written": strm_written,
        }

    except Exception as e:
        logger.exception("Error syncing Plex series")
        sync_state.status = "failed"
        sync_state.error_message = str(e)
        db.commit()
        raise


@celery_app.task
def sync_plex_movies_task(server_id: int, execution_id: int = None):
    """
    Celery task to sync Plex movies.

    @param server_id Database ID of the Plex server to sync
    @param execution_id Optional execution record ID (for scheduled syncs)
    """
    db = SessionLocal()
    execution = None
    try:
        server = db.query(PlexServer).filter(PlexServer.id == server_id).first()
        if not server:
            logger.error(f"Plex server {server_id} not found")
            return "Server not found"

        # Mark any stale running executions as interrupted
        stale_executions = db.query(PlexScheduleExecution).filter(
            PlexScheduleExecution.server_id == server_id,
            PlexScheduleExecution.sync_type == "movies",
            PlexScheduleExecution.status == PlexExecutionStatus.RUNNING
        ).all()
        for stale in stale_executions:
            stale.status = PlexExecutionStatus.INTERRUPTED
            stale.completed_at = datetime.utcnow()
            stale.error_message = "Interrupted by new sync"
        if stale_executions:
            db.commit()

        # Get or create execution record
        if execution_id:
            execution = db.query(PlexScheduleExecution).filter(PlexScheduleExecution.id == execution_id).first()
        else:
            # Manual sync - create execution record
            execution = PlexScheduleExecution(
                server_id=server_id,
                sync_type="movies",
                status=PlexExecutionStatus.RUNNING
            )
            db.add(execution)
            db.commit()

        account = db.query(PlexAccount).filter(PlexAccount.id == server.account_id).first()
        if not account:
            logger.error(f"Plex account for server {server_id} not found")
            if execution:
                execution.status = PlexExecutionStatus.FAILED
                execution.error_message = "Account not found"
                execution.completed_at = datetime.utcnow()
                db.commit()
            return "Account not found"

        client = PlexClient(account.auth_token)
        plex_server = client.connect_server(server.uri, server.access_token)

        if not plex_server:
            # Update sync state with error
            sync_state = db.query(PlexSyncState).filter(
                PlexSyncState.server_id == server_id,
                PlexSyncState.type == "movies"
            ).first()
            if sync_state:
                sync_state.status = "failed"
                sync_state.error_message = "Cannot connect to Plex server"
                db.commit()
            if execution:
                execution.status = PlexExecutionStatus.FAILED
                execution.error_message = "Cannot connect to Plex server"
                execution.completed_at = datetime.utcnow()
                db.commit()
            return "Cannot connect to Plex server"

        fm = FileManager(server.movies_dir)

        stats = asyncio.run(process_plex_movies(db, client, plex_server, fm, server_id)) or {}

        # Refresh session to get updated sync_state values
        db.expire_all()

        # Update execution record on success
        if execution:
            execution.status = PlexExecutionStatus.SUCCESS
            execution.completed_at = datetime.utcnow()
            execution.items_added = stats.get("items_added", 0)
            execution.items_deleted = stats.get("items_deleted", 0)
            execution.files_written = stats.get("files_written", 0)
            # Kept in sync for the screens still reading items_processed
            execution.items_processed = execution.items_added + execution.items_deleted
            db.commit()

        return f"Plex movies synced for {server.name}"

    except Exception as e:
        logger.exception(f"Error in sync_plex_movies_task: {e}")
        if execution:
            execution.status = PlexExecutionStatus.FAILED
            execution.error_message = str(e)
            execution.completed_at = datetime.utcnow()
            db.commit()
        return f"Error: {str(e)}"
    finally:
        db.close()


@celery_app.task
def sync_plex_series_task(server_id: int, execution_id: int = None):
    """
    Celery task to sync Plex series.

    @param server_id Database ID of the Plex server to sync
    @param execution_id Optional execution record ID (for scheduled syncs)
    """
    db = SessionLocal()
    execution = None
    try:
        server = db.query(PlexServer).filter(PlexServer.id == server_id).first()
        if not server:
            logger.error(f"Plex server {server_id} not found")
            return "Server not found"

        # Mark any stale running executions as interrupted
        stale_executions = db.query(PlexScheduleExecution).filter(
            PlexScheduleExecution.server_id == server_id,
            PlexScheduleExecution.sync_type == "series",
            PlexScheduleExecution.status == PlexExecutionStatus.RUNNING
        ).all()
        for stale in stale_executions:
            stale.status = PlexExecutionStatus.INTERRUPTED
            stale.completed_at = datetime.utcnow()
            stale.error_message = "Interrupted by new sync"
        if stale_executions:
            db.commit()

        # Get or create execution record
        if execution_id:
            execution = db.query(PlexScheduleExecution).filter(PlexScheduleExecution.id == execution_id).first()
        else:
            # Manual sync - create execution record
            execution = PlexScheduleExecution(
                server_id=server_id,
                sync_type="series",
                status=PlexExecutionStatus.RUNNING
            )
            db.add(execution)
            db.commit()

        account = db.query(PlexAccount).filter(PlexAccount.id == server.account_id).first()
        if not account:
            logger.error(f"Plex account for server {server_id} not found")
            if execution:
                execution.status = PlexExecutionStatus.FAILED
                execution.error_message = "Account not found"
                execution.completed_at = datetime.utcnow()
                db.commit()
            return "Account not found"

        client = PlexClient(account.auth_token)
        plex_server = client.connect_server(server.uri, server.access_token)

        if not plex_server:
            # Update sync state with error
            sync_state = db.query(PlexSyncState).filter(
                PlexSyncState.server_id == server_id,
                PlexSyncState.type == "series"
            ).first()
            if sync_state:
                sync_state.status = "failed"
                sync_state.error_message = "Cannot connect to Plex server"
                db.commit()
            if execution:
                execution.status = PlexExecutionStatus.FAILED
                execution.error_message = "Cannot connect to Plex server"
                execution.completed_at = datetime.utcnow()
                db.commit()
            return "Cannot connect to Plex server"

        fm = FileManager(server.series_dir)

        stats = asyncio.run(process_plex_series(db, client, plex_server, fm, server_id)) or {}

        # Refresh session to get updated sync_state values
        db.expire_all()

        # Update execution record on success
        if execution:
            execution.status = PlexExecutionStatus.SUCCESS
            execution.completed_at = datetime.utcnow()
            execution.items_added = stats.get("items_added", 0)
            execution.items_deleted = stats.get("items_deleted", 0)
            execution.files_written = stats.get("files_written", 0)
            # Kept in sync for the screens still reading items_processed
            execution.items_processed = execution.items_added + execution.items_deleted
            db.commit()

        return f"Plex series synced for {server.name}"

    except Exception as e:
        logger.exception(f"Error in sync_plex_series_task: {e}")
        if execution:
            execution.status = PlexExecutionStatus.FAILED
            execution.error_message = str(e)
            execution.completed_at = datetime.utcnow()
            db.commit()
        return f"Error: {str(e)}"
    finally:
        db.close()


@celery_app.task
def check_plex_schedules_task():
    """Check Plex schedules and trigger syncs if needed"""
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        # Get enabled schedules that are due
        schedules = db.query(PlexSchedule).filter(
            PlexSchedule.enabled == True,
            PlexSchedule.next_run <= now
        ).all()

        for schedule in schedules:
            # Create execution record
            execution = PlexScheduleExecution(
                schedule_id=schedule.id,
                server_id=schedule.server_id,
                sync_type=schedule.type.value if hasattr(schedule.type, 'value') else str(schedule.type),
                status=PlexExecutionStatus.RUNNING
            )
            db.add(execution)
            db.commit()

            try:
                # Trigger appropriate sync with execution_id
                # The sync task will update the execution status
                if schedule.type == PlexScheduleSyncType.MOVIES:
                    sync_plex_movies_task.apply_async(args=[schedule.server_id, execution.id])
                else:
                    sync_plex_series_task.apply_async(args=[schedule.server_id, execution.id])

            except Exception as e:
                logger.exception(f"Error triggering scheduled Plex sync for {schedule.type}")
                execution.status = PlexExecutionStatus.FAILED
                execution.error_message = str(e)
                execution.completed_at = datetime.utcnow()
                db.commit()

            # Update schedule for next run
            schedule.last_run = now
            schedule.next_run = schedule.calculate_next_run()
            db.commit()

    finally:
        db.close()
