"""
Plex.tv integration API endpoints.

Handles Plex account management, server discovery, library selection, and sync operations.

@description Provides endpoints for:
- Plex.tv authentication (login to get auth token)
- Account CRUD operations
- Server listing and refresh
- Library sync and selection
- Sync trigger and status
"""
from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import RedirectResponse, StreamingResponse
import httpx
import asyncio
from typing import Dict, Tuple, Any
import time
import base64
import urllib.parse
import hashlib
from contextlib import asynccontextmanager


# Shared HTTP client for connection pooling - keeps connections alive
_http_client: httpx.AsyncClient = None


def get_http_client() -> httpx.AsyncClient:
    """
    Get or create a shared HTTP client with connection pooling.

    Using a shared client improves performance by reusing TCP connections
    and keeps Plex transcoding sessions alive.
    """
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(
            follow_redirects=True,
            timeout=httpx.Timeout(60.0, connect=10.0),  # Longer timeout for transcoding
            limits=httpx.Limits(max_keepalive_connections=20, max_connections=50),
            http2=True,  # HTTP/2 for better multiplexing
        )
    return _http_client


async def close_http_client():
    """Close the shared HTTP client on application shutdown."""
    global _http_client
    if _http_client is not None:
        await _http_client.aclose()
        _http_client = None
        logger.info("Plex HLS HTTP client closed")


def get_plex_headers(access_token: str, session_id: str = None) -> dict:
    """
    Generate standard Plex API headers to maintain session.

    @param access_token Plex server access token
    @param session_id Stable session identifier, so Plex reuses one transcode
    session for the whole playback instead of opening one per request
    @returns Dict of headers to include in requests
    """
    headers = {
        "X-Plex-Token": access_token,
        "X-Plex-Client-Identifier": "xtream-to-strm",
        "X-Plex-Product": "Xtream to STRM",
        "X-Plex-Platform": "Chrome",
        "X-Plex-Device": "Linux",
        "Accept": "*/*",
        "Connection": "keep-alive",
    }

    if session_id:
        headers["X-Plex-Session-Identifier"] = session_id

    return headers


# Query parameters whose values must never reach the logs or an HTTP response
_SENSITIVE_QUERY_PARAMS = ("X-Plex-Token", "key")


def _redact_url(url: str) -> str:
    """
    Mask credential query parameters so a URL can safely be logged.

    @param url URL that may carry a Plex token or the proxy shared key
    @returns Same URL with sensitive parameter values replaced by a placeholder

    @example
    _redact_url("https://plex.direct:32400/start.m3u8?X-Plex-Token=abc&offset=0")
    # -> "https://plex.direct:32400/start.m3u8?X-Plex-Token=%3Credacted%3E&offset=0"
    """
    try:
        parsed = urllib.parse.urlsplit(url)
        if not parsed.query:
            return url

        redacted = [
            (name, "<redacted>" if name in _SENSITIVE_QUERY_PARAMS else value)
            for name, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        ]
        return urllib.parse.urlunsplit(
            parsed._replace(query=urllib.parse.urlencode(redacted))
        )
    except Exception:
        # Log formatting must never break a request
        return "<unparsable url>"


def _describe_upstream_failure(exc: Exception, url: str, started_at: float) -> str:
    """
    Build a diagnostic line for a failed request to the Plex server.

    @description httpx timeout exceptions carry an empty message, so `str(exc)`
    alone is unusable. The exception class plus the elapsed time are what
    identify the failure: a ConnectTimeout near the connect deadline means the
    server URI is unreachable, while a ReadTimeout near the read deadline means
    Plex accepted the connection but never answered (typically a stalled
    transcode session).

    @param exc Exception raised while calling Plex
    @param url Upstream URL that was requested (redacted before logging)
    @param started_at time.monotonic() captured just before the request
    @returns Diagnostic string safe to log

    @example
    logger.error(f"playlist failed: {_describe_upstream_failure(e, url, t0)}")
    # -> "playlist failed: type=httpx.ReadTimeout elapsed=60.0s repr=... url=..."
    """
    details = [
        f"type=httpx.{type(exc).__name__}" if isinstance(exc, httpx.HTTPError)
        else f"type={type(exc).__module__}.{type(exc).__name__}",
        f"elapsed={time.monotonic() - started_at:.1f}s",
    ]

    if isinstance(exc, httpx.HTTPStatusError):
        # The upstream body is dropped by httpx's own message but often holds
        # the actual Plex error (XML <Response code="..." status="..."/>)
        details.append(f"status={exc.response.status_code}")
        details.append(f"body={exc.response.text[:300]!r}")

    details.append(f"repr={exc!r}")
    details.append(f"url={_redact_url(url)}")
    return " ".join(details)


def stable_hash(s: str) -> str:
    """Generate a stable hash for a string (deterministic across processes)."""
    return hashlib.md5(s.encode()).hexdigest()[:16]


# 64 KiB keeps the relay responsive without a syscall per TS packet
_SEGMENT_CHUNK_SIZE = 65536

# Upstream media types accepted for a segment; anything else is an error page
_SEGMENT_MEDIA_PREFIXES = ("video/", "audio/", "application/octet-stream")


async def relay_segment(response: httpx.Response):
    """
    Relay an already-open segment response to the client, chunk by chunk.

    @description The upstream response is handed over open so the first bytes
    reach the player immediately. Buffering a whole segment added its full
    download time to every single one, which stalls playback when Plex emits
    one-second segments. The connection is released even if the client
    disconnects halfway through.

    @param response Open streaming response from the shared HTTP client
    @yields Chunks of the segment body

    @example
    return StreamingResponse(relay_segment(response), media_type="video/mp2t")
    """
    try:
        async for chunk in response.aiter_bytes(_SEGMENT_CHUNK_SIZE):
            yield chunk
    finally:
        await response.aclose()


def build_session_identifier(server_id: int, rating_key: int) -> str:
    """
    Build a stable Plex session identifier for one media item.

    @description Plex opens a new transcode session for every request carrying a
    different session identifier. Without a stable value, each reload of the
    master playlist spawned another session: transcodes piled up on the server
    and Plex could invalidate the playlist already handed to the player.

    @param server_id Database ID of the Plex server
    @param rating_key Plex rating key of the media
    @returns Deterministic identifier, stable across requests and processes

    @example
    build_session_identifier(2, 34304)  # -> "xts-0b1c2d3e4f506172"
    """
    return f"xts-{stable_hash(f'{server_id}:{rating_key}')}"

def rewrite_playlist_urls(
    content: str,
    base_url: str,
    plex_base_url: str,
    access_token: str,
    server_id: int,
    rating_key: int,
    proxy_base_url: str,
    key: str
) -> str:
    """
    Rewrite all URLs in an HLS playlist to go through our proxy.
    Both playlists and segments are proxied to maintain session.
    """
    lines = content.split('\n')
    rewritten_lines = []

    for line in lines:
        if line and not line.startswith('#'):
            # Resolve relative URLs to absolute
            if line.startswith('http'):
                full_url = line
            elif line.startswith('/'):
                parsed = urllib.parse.urlparse(base_url)
                full_url = f"{parsed.scheme}://{parsed.netloc}{line}"
            else:
                parent = base_url.rsplit('/', 1)[0]
                full_url = f"{parent}/{line}"

            # Add token if needed
            if 'X-Plex-Token' not in full_url:
                if '?' in full_url:
                    full_url += f"&X-Plex-Token={access_token}"
                else:
                    full_url += f"?X-Plex-Token={access_token}"

            # ALL URLs go through our proxy to maintain Plex session
            encoded_url = base64.urlsafe_b64encode(full_url.encode()).decode()
            line = f"{proxy_base_url}/api/v1/plex/hls-stream/{server_id}/{rating_key}?url={encoded_url}&key={key or ''}"

        rewritten_lines.append(line)

    return '\n'.join(rewritten_lines)
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime
from app.api import deps
from app.models.plex_account import PlexAccount
from app.models.plex_server import PlexServer
from app.models.plex_library import PlexLibrary
from app.models.plex_sync_state import PlexSyncState
from app.models.plex_schedule_execution import PlexScheduleExecution, PlexExecutionStatus
from app.models.plex_cache import PlexMovieCache, PlexSeriesCache, PlexEpisodeCache
from app.models.settings import SettingsModel
from app.schemas import (
    PlexLoginRequest, PlexLoginResponse,
    PlexAccountCreate, PlexAccountResponse,
    PlexAccountTokenRefresh, PlexTokenRefreshResponse,
    PlexServerResponse, PlexServerUpdate,
    PlexLibraryResponse, PlexLibrarySelection,
    PlexSyncStatusResponse
)
from app.services.plex import PlexClient, PlexAuthError, PlexApiError
import logging

logger = logging.getLogger(__name__)
router = APIRouter()


# --- Authentication ---

@router.post("/login", response_model=PlexLoginResponse)
def plex_login(request: PlexLoginRequest):
    """
    Test Plex.tv login credentials.

    @param request Login credentials (username/password)
    @returns Success status with auth token if successful
    """
    result = PlexClient.login(request.username, request.password, code=request.code)
    return PlexLoginResponse(
        success=result.get("success", False),
        message=result.get("message", "Unknown error"),
        auth_token=result.get("auth_token"),
        username=result.get("username")
    )


# --- Account Management ---

@router.get("/accounts", response_model=List[PlexAccountResponse])
def get_accounts(db: Session = Depends(deps.get_db)):
    """Get all Plex accounts."""
    return db.query(PlexAccount).all()


@router.post("/accounts", response_model=PlexAccountResponse)
def create_account(account: PlexAccountCreate, db: Session = Depends(deps.get_db)):
    """
    Create new Plex account by logging in to Plex.tv.

    @param account Account info with password for initial login
    @returns Created account (password not stored, only auth token)
    """
    # Check for duplicate name
    existing = db.query(PlexAccount).filter(PlexAccount.name == account.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Account name already exists")

    # Login to get auth token
    result = PlexClient.login(account.username, account.password)
    if not result.get("success"):
        raise HTTPException(status_code=401, detail=result.get("message", "Login failed"))

    # Create account record
    db_account = PlexAccount(
        name=account.name,
        username=account.username,
        auth_token=result["auth_token"],
        output_base_dir=account.output_base_dir
    )
    db.add(db_account)
    db.commit()
    db.refresh(db_account)

    # Fetch and store servers; the account stays usable if this step fails
    try:
        _sync_servers_for_account(db, db_account)
    except (PlexAuthError, PlexApiError) as e:
        logger.error(f"Failed to fetch servers for new account '{db_account.name}': {e}")
        # Account created, servers can be refreshed later

    return db_account


@router.delete("/accounts/{account_id}")
def delete_account(account_id: int, db: Session = Depends(deps.get_db)):
    """
    Delete a Plex account and all associated data.

    @param account_id Account ID to delete
    """
    account = db.query(PlexAccount).filter(PlexAccount.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    # Delete related data (cascade should handle this, but be explicit)
    servers = db.query(PlexServer).filter(PlexServer.account_id == account_id).all()
    for server in servers:
        db.query(PlexLibrary).filter(PlexLibrary.server_id == server.id).delete()
        db.query(PlexSyncState).filter(PlexSyncState.server_id == server.id).delete()
        db.query(PlexMovieCache).filter(PlexMovieCache.server_id == server.id).delete()
        db.query(PlexSeriesCache).filter(PlexSeriesCache.server_id == server.id).delete()
        db.query(PlexEpisodeCache).filter(PlexEpisodeCache.server_id == server.id).delete()
    db.query(PlexServer).filter(PlexServer.account_id == account_id).delete()

    db.delete(account)
    db.commit()
    return {"message": "Account deleted"}


@router.put("/accounts/{account_id}/token", response_model=PlexTokenRefreshResponse)
def refresh_account_token(
    account_id: int,
    request: PlexAccountTokenRefresh,
    db: Session = Depends(deps.get_db)
):
    """
    Re-authenticate an existing account and store a fresh Plex.tv token.

    @description Plex.tv revokes tokens on a password change or when the device
    is removed from the authorized list. Without this endpoint the only way to
    renew one was to delete and recreate the account, which cascades and destroys
    its servers, libraries, caches and schedules. Server URIs are refreshed right
    after, since that is what a stale token was blocking.

    @param account_id Account whose token must be renewed
    @param request Plex.tv password and optional two-factor code
    @returns Renewal result, including how many servers were re-synced

    @example
    PUT /api/v1/plex/accounts/1/token
    {"password": "...", "code": "123456"}
    """
    account = db.query(PlexAccount).filter(PlexAccount.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    result = PlexClient.login(account.username, request.password, code=request.code)
    if not result.get("success"):
        logger.warning(f"Token renewal failed for account '{account.name}'")
        raise HTTPException(status_code=401, detail=result.get("message", "Login failed"))

    account.auth_token = result["auth_token"]
    db.commit()
    logger.info(f"Plex.tv token renewed for account '{account.name}'")

    try:
        summary = _sync_servers_for_account(db, account)
    except (PlexAuthError, PlexApiError) as e:
        # The token itself is valid, so this is not a failure of the renewal
        logger.error(f"Server refresh after token renewal failed: {e}")
        return PlexTokenRefreshResponse(
            success=True,
            message=f"Token renewed, but refreshing servers failed: {e}",
        )

    return PlexTokenRefreshResponse(
        success=True,
        message=_describe_sync(summary, "Token renewed"),
        servers_refreshed=summary["total"],
        unreachable=summary["unreachable"],
    )


def _sync_servers_for_account(db: Session, account: PlexAccount) -> Dict[str, Any]:
    """
    Fetch an account's servers from Plex.tv and upsert them into the database.

    @description Shared by account creation, the manual refresh and the token
    renewal so the upsert rules live in one place. An unreachable URI never
    overwrites a stored one that still works: Plex.tv keeps advertising stale
    addresses, and clobbering a good URI with a dead one is what broke playback.

    @param db Active database session
    @param account Account whose servers must be refreshed
    @returns Summary with total, added, updated and unreachable server names
    @raises PlexAuthError When Plex.tv rejects the account token
    @raises PlexApiError When the Plex.tv request fails for another reason

    @example
    summary = _sync_servers_for_account(db, account)
    if summary["unreachable"]:
        warn(summary["unreachable"])
    """
    servers = PlexClient(account.auth_token).get_servers()

    existing = {
        s.server_id: s
        for s in db.query(PlexServer).filter(PlexServer.account_id == account.id).all()
    }

    added = 0
    updated = 0
    unreachable: List[str] = []

    for srv in servers:
        if not srv.get("uri_reachable", True):
            unreachable.append(srv["name"])

        row = existing.get(srv["server_id"])
        if row:
            # Only trust a probed URI; otherwise keep whatever already works
            if srv.get("uri_reachable"):
                row.uri = srv["uri"]
            row.access_token = srv["access_token"]
            row.version = srv.get("version")
            row.name = srv["name"]
            updated += 1
        else:
            safe_name = srv["name"].replace(" ", "_").replace("/", "_").replace("\\", "_")
            db.add(PlexServer(
                account_id=account.id,
                server_id=srv["server_id"],
                name=srv["name"],
                uri=srv["uri"],
                access_token=srv["access_token"],
                version=srv.get("version"),
                is_owned=srv.get("is_owned", False),
                movies_dir=f"{account.output_base_dir}/{safe_name}/movies",
                series_dir=f"{account.output_base_dir}/{safe_name}/series"
            ))
            added += 1

    db.commit()
    logger.info(
        f"Plex servers synced for '{account.name}': total={len(servers)} "
        f"added={added} updated={updated} unreachable={unreachable}"
    )
    return {
        "total": len(servers),
        "added": added,
        "updated": updated,
        "unreachable": unreachable,
    }


def _describe_sync(summary: Dict[str, Any], prefix: str) -> str:
    """
    Turn a sync summary into a message suitable for the UI.

    @param summary Result of _sync_servers_for_account
    @param prefix Leading sentence, e.g. "Token renewed"
    @returns Single-line human readable message
    """
    message = f"{prefix}, {summary['total']} server(s) refreshed"
    if summary["unreachable"]:
        message += f" - unreachable: {', '.join(summary['unreachable'])}"
    return message


# --- Server Management ---

@router.get("/servers/{account_id}", response_model=List[PlexServerResponse])
def get_servers(account_id: int, db: Session = Depends(deps.get_db)):
    """Get servers for an account."""
    account = db.query(PlexAccount).filter(PlexAccount.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    servers = db.query(PlexServer).filter(PlexServer.account_id == account_id).all()
    return servers


@router.post("/servers/{account_id}/refresh")
def refresh_servers(account_id: int, db: Session = Depends(deps.get_db)):
    """
    Refresh server list and connection URIs from Plex.tv.

    @description A revoked token used to be swallowed and reported as a success
    with zero servers updated, which made the button look broken. Failures now
    surface as 401/502 so the UI can tell the user to renew the token.

    @param account_id Account ID to refresh servers for
    @returns Summary with the number of servers seen and any unreachable ones
    """
    account = db.query(PlexAccount).filter(PlexAccount.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    try:
        summary = _sync_servers_for_account(db, account)
    except PlexAuthError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except PlexApiError as e:
        raise HTTPException(status_code=502, detail=str(e))

    return {
        "message": _describe_sync(summary, "Servers refreshed"),
        "count": summary["total"],
        **summary,
    }


@router.put("/servers/{server_id}", response_model=PlexServerResponse)
def update_server(server_id: int, update: PlexServerUpdate, db: Session = Depends(deps.get_db)):
    """
    Update server settings (selection, directories).

    @param server_id Server ID to update
    @param update Fields to update
    """
    server = db.query(PlexServer).filter(PlexServer.id == server_id).first()
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")

    if update.is_selected is not None:
        server.is_selected = update.is_selected
    if update.movies_dir is not None:
        server.movies_dir = update.movies_dir
    if update.series_dir is not None:
        server.series_dir = update.series_dir

    db.commit()
    db.refresh(server)
    return server


# --- Library Management ---

@router.get("/libraries/{server_id}", response_model=List[PlexLibraryResponse])
def get_libraries(server_id: int, db: Session = Depends(deps.get_db)):
    """Get libraries for a server."""
    server = db.query(PlexServer).filter(PlexServer.id == server_id).first()
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")

    libraries = db.query(PlexLibrary).filter(PlexLibrary.server_id == server_id).all()
    return libraries


@router.post("/libraries/{server_id}/sync")
def sync_libraries(server_id: int, db: Session = Depends(deps.get_db)):
    """
    Fetch libraries from Plex server and store in database.

    @param server_id Server ID to fetch libraries from
    """
    server = db.query(PlexServer).filter(PlexServer.id == server_id).first()
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")

    account = db.query(PlexAccount).filter(PlexAccount.id == server.account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    client = PlexClient(account.auth_token)
    plex_server = client.connect_server(server.uri, server.access_token)

    if not plex_server:
        raise HTTPException(status_code=500, detail="Cannot connect to server")

    libraries = client.get_libraries(plex_server)

    # Keep track of existing selections
    existing = {lib.library_key: lib.is_selected for lib in db.query(PlexLibrary).filter(PlexLibrary.server_id == server_id).all()}

    # Clear and re-add libraries
    db.query(PlexLibrary).filter(PlexLibrary.server_id == server_id).delete()

    for lib in libraries:
        db_lib = PlexLibrary(
            server_id=server_id,
            library_key=lib["key"],
            title=lib["title"],
            type=lib["type"],
            item_count=lib.get("item_count", 0),
            is_selected=existing.get(lib["key"], False)  # Preserve selection
        )
        db.add(db_lib)

    db.commit()
    return {"message": "Libraries synced", "count": len(libraries)}


@router.post("/libraries/{server_id}/selection")
def update_library_selection(server_id: int, selection: PlexLibrarySelection, db: Session = Depends(deps.get_db)):
    """
    Update selected libraries for sync.

    @param server_id Server ID
    @param selection List of library IDs to select
    """
    server = db.query(PlexServer).filter(PlexServer.id == server_id).first()
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")

    # Deselect all
    db.query(PlexLibrary).filter(PlexLibrary.server_id == server_id).update({"is_selected": False})
    # Select specified
    if selection.library_ids:
        db.query(PlexLibrary).filter(PlexLibrary.id.in_(selection.library_ids)).update({"is_selected": True})
    db.commit()
    return {"message": "Selection updated"}


# --- Sync Operations ---

@router.get("/sync/status/{server_id}", response_model=List[PlexSyncStatusResponse])
def get_sync_status(server_id: int, db: Session = Depends(deps.get_db)):
    """Get sync status for a server."""
    server = db.query(PlexServer).filter(PlexServer.id == server_id).first()
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")

    statuses = db.query(PlexSyncState).filter(PlexSyncState.server_id == server_id).all()

    # If no status records exist, create default ones
    if not statuses:
        for sync_type in ["movies", "series"]:
            status = PlexSyncState(server_id=server_id, type=sync_type, status="idle")
            db.add(status)
        db.commit()
        statuses = db.query(PlexSyncState).filter(PlexSyncState.server_id == server_id).all()

    return statuses


@router.post("/sync/movies/{server_id}")
def trigger_movies_sync(server_id: int, db: Session = Depends(deps.get_db)):
    """
    Trigger movie sync for a server.

    @param server_id Server ID to sync movies from
    """
    server = db.query(PlexServer).filter(PlexServer.id == server_id).first()
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")

    # Check if already running
    status = db.query(PlexSyncState).filter(
        PlexSyncState.server_id == server_id,
        PlexSyncState.type == "movies"
    ).first()
    if status and status.status == "running":
        raise HTTPException(status_code=400, detail="Sync already in progress")

    # Import and trigger Celery task
    from app.tasks.plex_sync import sync_plex_movies_task
    task = sync_plex_movies_task.delay(server_id)

    # Update status
    if not status:
        status = PlexSyncState(server_id=server_id, type="movies")
        db.add(status)
    status.status = "running"
    status.task_id = task.id
    status.error_message = None
    db.commit()

    return {"message": "Movies sync started", "task_id": task.id}


@router.post("/sync/series/{server_id}")
def trigger_series_sync(server_id: int, db: Session = Depends(deps.get_db)):
    """
    Trigger series sync for a server.

    @param server_id Server ID to sync series from
    """
    server = db.query(PlexServer).filter(PlexServer.id == server_id).first()
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")

    # Check if already running
    status = db.query(PlexSyncState).filter(
        PlexSyncState.server_id == server_id,
        PlexSyncState.type == "series"
    ).first()
    if status and status.status == "running":
        raise HTTPException(status_code=400, detail="Sync already in progress")

    # Import and trigger Celery task
    from app.tasks.plex_sync import sync_plex_series_task
    task = sync_plex_series_task.delay(server_id)

    # Update status
    if not status:
        status = PlexSyncState(server_id=server_id, type="series")
        db.add(status)
    status.status = "running"
    status.task_id = task.id
    status.error_message = None
    db.commit()

    return {"message": "Series sync started", "task_id": task.id}


@router.post("/sync/stop/{server_id}/{sync_type}")
def stop_plex_sync(server_id: int, sync_type: str, db: Session = Depends(deps.get_db)):
    """
    Stop a running Plex sync task.

    @param server_id Server ID
    @param sync_type Type of sync (movies or series)
    """
    from app.core.celery_app import celery_app

    sync_state = db.query(PlexSyncState).filter(
        PlexSyncState.server_id == server_id,
        PlexSyncState.type == sync_type
    ).first()

    if not sync_state or not sync_state.task_id:
        return {"message": "No running task found"}

    # Revoke the task
    celery_app.control.revoke(sync_state.task_id, terminate=True)

    # Update sync_state status
    sync_state.status = "idle"
    sync_state.task_id = None

    # Update any running execution records to cancelled
    running_executions = db.query(PlexScheduleExecution).filter(
        PlexScheduleExecution.server_id == server_id,
        PlexScheduleExecution.sync_type == sync_type,
        PlexScheduleExecution.status == PlexExecutionStatus.RUNNING
    ).all()

    for execution in running_executions:
        execution.status = PlexExecutionStatus.CANCELLED
        execution.completed_at = datetime.utcnow()

    db.commit()

    return {"message": f"{sync_type.capitalize()} sync stopped successfully"}


# --- Proxy Streaming ---

@router.get("/proxy/{server_id}/{rating_key}/stream.m3u8")
@router.get("/proxy/{server_id}/{rating_key}")
async def proxy_plex_stream(
    server_id: int,
    rating_key: int,
    key: str = None,
    direct_play: int = 0,
    direct_stream: int = 1,
    db: Session = Depends(deps.get_db)
):
    """
    Proxy or redirect to Plex streaming URL.

    If PLEX_HLS_PROXY_MODE is enabled, fetches the HLS playlist and rewrites URLs.
    This is needed for clients like Findroid (ExoPlayer-based) that don't follow redirects.
    Otherwise, returns a 302 redirect to Plex.

    @param server_id Database ID of the Plex server
    @param rating_key Plex rating key of the media
    @param key Shared key for authentication (must match PLEX_SHARED_KEY setting)
    @param direct_play 0=transcode allowed, 1=direct play only
    @param direct_stream 0=full transcode, 1=remux only
    @returns HLS playlist content or HTTP 302 redirect
    """
    # Verify shared key
    shared_key_setting = db.query(SettingsModel).filter(SettingsModel.key == "PLEX_SHARED_KEY").first()
    expected_key = shared_key_setting.value if shared_key_setting else None

    if expected_key and key != expected_key:
        raise HTTPException(status_code=403, detail="Invalid or missing shared key")

    server = db.query(PlexServer).filter(PlexServer.id == server_id).first()
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")

    # Check if HLS proxy mode is enabled
    hls_proxy_setting = db.query(SettingsModel).filter(SettingsModel.key == "PLEX_HLS_PROXY_MODE").first()
    hls_proxy_enabled = hls_proxy_setting and hls_proxy_setting.value.lower() == "true"

    # One stable session per media item, reused by every request below
    session_id = build_session_identifier(server_id, rating_key)

    # Build Plex streaming URL
    params = {
        'path': f'/library/metadata/{rating_key}',
        'mediaIndex': '0',
        'partIndex': '0',
        'protocol': 'hls',
        'fastSeek': '1',
        'copyts': '1',
        'offset': '0',
        'directPlay': str(direct_play),
        'directStream': str(direct_stream),
        'directStreamAudio': '1',
        'location': 'wan',
        'X-Plex-Platform': 'Chrome',
        'X-Plex-Client-Identifier': 'xtream-to-strm',
        'X-Plex-Product': 'Xtream to STRM',
        'X-Plex-Session-Identifier': session_id,
        'X-Plex-Token': server.access_token,
    }

    query_string = urllib.parse.urlencode(params)
    plex_url = f"{server.uri}/video/:/transcode/universal/start.m3u8?{query_string}"

    if not hls_proxy_enabled:
        # Mode redirect (default behavior)
        return RedirectResponse(url=plex_url, status_code=302)

    # HLS Full Proxy Mode - proxy ALL requests to maintain Plex session
    proxy_base_setting = db.query(SettingsModel).filter(SettingsModel.key == "PLEX_PROXY_BASE_URL").first()
    proxy_base_url = (proxy_base_setting.value if proxy_base_setting else "").rstrip('/')

    if not proxy_base_url:
        logger.warning(
            "PLEX_PROXY_BASE_URL is not set: rewritten playlist URLs will be "
            "relative and most clients will fail to resolve them"
        )

    logger.info(
        f"HLS proxy request: server_id={server_id} rating_key={rating_key} "
        f"upstream={_redact_url(plex_url)}"
    )

    started_at = time.monotonic()

    try:
        client = get_http_client()
        headers = get_plex_headers(server.access_token, session_id)
        response = await client.get(plex_url, headers=headers)
        response.raise_for_status()

        master_content = response.text
        logger.info(
            f"HLS master playlist fetched in {time.monotonic() - started_at:.1f}s, "
            f"status={response.status_code} http={response.http_version} "
            f"content_type={response.headers.get('content-type')} length={len(master_content)}"
        )

        # Plex can answer 200 with an XML/HTML error instead of a playlist, which
        # would otherwise be rewritten into a valid-looking but unplayable file.
        # A leading BOM is tolerated so a valid playlist is never rejected here.
        if not master_content.lstrip("﻿ \t\r\n").startswith("#EXTM3U"):
            logger.error(
                f"HLS master playlist is not an M3U8 document: {master_content[:300]!r}"
            )
            raise HTTPException(
                status_code=502,
                detail="Plex did not return an HLS playlist"
            )

        # Rewrite ALL URLs to go through our proxy (both playlists AND segments)
        rewritten_content = rewrite_playlist_urls(
            content=master_content,
            base_url=plex_url,
            plex_base_url=server.uri.rstrip('/'),
            access_token=server.access_token,
            server_id=server_id,
            rating_key=rating_key,
            proxy_base_url=proxy_base_url,
            key=key or ''
        )

        return Response(
            content=rewritten_content,
            media_type="application/vnd.apple.mpegurl",
            headers={
                "Access-Control-Allow-Origin": "*",
                "Cache-Control": "no-cache, no-store, must-revalidate"
            }
        )
    except HTTPException:
        # Already diagnosed above, keep the intended status code
        raise
    except httpx.HTTPError as e:
        logger.error(
            f"HLS master playlist error: {_describe_upstream_failure(e, plex_url, started_at)}"
        )
        # str(e) is empty for timeouts and leaks the Plex token for status
        # errors, so only the exception class is exposed to the client
        raise HTTPException(
            status_code=502,
            detail=f"Failed to fetch HLS playlist ({type(e).__name__})"
        )
    except Exception as e:
        logger.exception(
            f"HLS master playlist unexpected error: "
            f"{_describe_upstream_failure(e, plex_url, started_at)}"
        )
        raise HTTPException(
            status_code=502,
            detail=f"Unexpected error fetching HLS playlist ({type(e).__name__})"
        )


@router.get("/hls-stream/{server_id}/{rating_key}")
async def hls_stream(
    server_id: int,
    rating_key: int,
    url: str,
    key: str = None,
    db: Session = Depends(deps.get_db)
):
    """
    Full passthrough HLS proxy endpoint with streaming support.

    Uses a persistent HTTP client and streams segments in real-time
    to minimize latency and keep the Plex transcoding session alive.

    For playlists (.m3u8), rewrites URLs to continue through this proxy.
    For segments (.ts), streams binary data directly without buffering.

    @param server_id Database ID of the Plex server
    @param rating_key Plex rating key
    @param url Base64-encoded URL to fetch from Plex
    @param key Shared key for authentication
    """
    # Verify shared key
    shared_key_setting = db.query(SettingsModel).filter(SettingsModel.key == "PLEX_SHARED_KEY").first()
    expected_key = shared_key_setting.value if shared_key_setting else None

    if expected_key and key != expected_key:
        raise HTTPException(status_code=403, detail="Invalid or missing shared key")

    server = db.query(PlexServer).filter(PlexServer.id == server_id).first()
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")

    # Decode the URL
    try:
        decoded_url = base64.urlsafe_b64decode(url.encode()).decode()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid URL encoding")

    # Get proxy base URL for rewriting playlists
    proxy_base_setting = db.query(SettingsModel).filter(SettingsModel.key == "PLEX_PROXY_BASE_URL").first()
    proxy_base_url = (proxy_base_setting.value if proxy_base_setting else "").rstrip('/')

    # Check if this is a playlist or segment based on URL extension
    is_playlist = decoded_url.endswith(".m3u8") or "m3u8" in decoded_url

    client = get_http_client()
    headers = get_plex_headers(
        server.access_token,
        build_session_identifier(server_id, rating_key)
    )

    if is_playlist:
        # For playlists, fetch fully and rewrite URLs
        logger.info(
            f"HLS playlist request: server_id={server_id} rating_key={rating_key} "
            f"upstream={_redact_url(decoded_url)}"
        )
        started_at = time.monotonic()

        try:
            response = await client.get(decoded_url, headers=headers)
            response.raise_for_status()

            content = response.text
            logger.info(
                f"HLS playlist fetched in {time.monotonic() - started_at:.1f}s, "
                f"status={response.status_code} length={len(content)}"
            )
            rewritten_content = rewrite_playlist_urls(
                content=content,
                base_url=decoded_url,
                plex_base_url=server.uri.rstrip('/'),
                access_token=server.access_token,
                server_id=server_id,
                rating_key=rating_key,
                proxy_base_url=proxy_base_url,
                key=key or ''
            )

            return Response(
                content=rewritten_content,
                media_type="application/vnd.apple.mpegurl",
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Cache-Control": "no-cache, no-store, must-revalidate"
                }
            )
        except httpx.HTTPError as e:
            logger.error(
                f"HLS playlist error: {_describe_upstream_failure(e, decoded_url, started_at)}"
            )
            raise HTTPException(
                status_code=502,
                detail=f"Failed to fetch HLS playlist ({type(e).__name__})"
            )
        except Exception as e:
            logger.exception(
                f"HLS playlist unexpected error: "
                f"{_describe_upstream_failure(e, decoded_url, started_at)}"
            )
            raise HTTPException(
                status_code=502,
                detail=f"Unexpected error fetching HLS playlist ({type(e).__name__})"
            )
    else:
        # Segments are relayed as they arrive: the status code is checked before
        # any body is read, so a retry is still possible, but a successful
        # segment is never buffered in full before the player gets its first byte
        max_retries = 2

        logger.debug(f"HLS segment request: upstream={_redact_url(decoded_url)}")

        for attempt in range(max_retries):
            started_at = time.monotonic()
            response = None
            try:
                request = client.build_request("GET", decoded_url, headers=headers)
                response = await client.send(request, stream=True)

                if response.status_code >= 400:
                    # Read the short error body so it reaches the logs
                    await response.aread()
                    response.raise_for_status()

                # Plex can answer 200 with an XML error; forwarding that as
                # video/mp2t injects garbage into the stream and leaves the
                # demuxer unable to lock onto a packet size
                upstream_type = response.headers.get("content-type", "")
                if upstream_type and not upstream_type.startswith(_SEGMENT_MEDIA_PREFIXES):
                    await response.aread()
                    logger.error(
                        f"Segment is not media: content_type={upstream_type!r} "
                        f"body={response.text[:200]!r} url={_redact_url(decoded_url)}"
                    )
                    raise HTTPException(
                        status_code=502,
                        detail="Plex did not return a media segment"
                    )

                logger.debug(
                    f"Segment relay started: status={response.status_code} "
                    f"length={response.headers.get('content-length')} "
                    f"ttfb={time.monotonic() - started_at:.2f}s"
                )
                return StreamingResponse(
                    relay_segment(response),
                    media_type=upstream_type or "video/mp2t",
                    headers={
                        "Access-Control-Allow-Origin": "*",
                        "Cache-Control": "no-cache, no-store, must-revalidate",
                    }
                )
            except httpx.HTTPStatusError as e:
                if response is not None:
                    await response.aclose()
                diagnosis = _describe_upstream_failure(e, decoded_url, started_at)

                if e.response.status_code == 404:
                    # 404 means segment may not be ready yet or expired
                    if attempt < max_retries - 1:
                        logger.warning(
                            f"Segment 404, retry {attempt + 1}/{max_retries}: {diagnosis}"
                        )
                        await asyncio.sleep(0.3 * (attempt + 1))  # Brief backoff
                        continue

                    logger.error(f"Segment 404 after {max_retries} retries: {diagnosis}")
                    raise HTTPException(status_code=502, detail="Segment not available (404)")

                logger.error(f"Segment HTTP error: {diagnosis}")
                raise HTTPException(status_code=502, detail=f"Plex returned {e.response.status_code}")
            except httpx.RequestError as e:
                if response is not None:
                    await response.aclose()
                diagnosis = _describe_upstream_failure(e, decoded_url, started_at)

                if attempt < max_retries - 1:
                    logger.warning(
                        f"Segment request error, retry {attempt + 1}/{max_retries}: {diagnosis}"
                    )
                    await asyncio.sleep(0.3 * (attempt + 1))
                    continue

                logger.error(f"Segment request error after {max_retries} retries: {diagnosis}")
                raise HTTPException(
                    status_code=502,
                    detail=f"Failed to fetch segment ({type(e).__name__})"
                )
            except HTTPException:
                # Already diagnosed above; release the upstream connection
                if response is not None:
                    await response.aclose()
                raise
            except Exception as e:
                if response is not None:
                    await response.aclose()
                logger.exception(
                    f"Segment unexpected error: "
                    f"{_describe_upstream_failure(e, decoded_url, started_at)}"
                )
                raise HTTPException(
                    status_code=502,
                    detail=f"Unexpected error fetching segment ({type(e).__name__})"
                )

        # Only reachable if every attempt asked for a retry
        raise HTTPException(status_code=502, detail=f"Failed after {max_retries} retries")


@router.get("/hls-cache/{server_id}/{rating_key}")
async def hls_cache_redirect(
    server_id: int,
    rating_key: int,
    cache_key: str = None,
    key: str = None
):
    """
    Legacy endpoint - redirects to hls-stream.
    Kept for backwards compatibility with any cached STRM files.
    """
    # This endpoint is deprecated, redirect to the new streaming endpoint
    raise HTTPException(
        status_code=410,
        detail="This endpoint is deprecated. Please use /hls-stream/ instead."
    )
