from pydantic import BaseModel, ConfigDict
from typing import Optional, List
from datetime import datetime

class ConfigUpdate(BaseModel):
    XC_URL: Optional[str] = None
    XC_USER: Optional[str] = None
    XC_PASS: Optional[str] = None
    OUTPUT_DIR: Optional[str] = None
    MOVIES_DIR: Optional[str] = None
    SERIES_DIR: Optional[str] = None
    PREFIX_REGEX: Optional[str] = None
    FORMAT_DATE_IN_TITLE: Optional[bool] = None
    CLEAN_NAME: Optional[bool] = None
    SERIES_USE_SEASON_FOLDERS: Optional[bool] = None
    SERIES_USE_CATEGORY_FOLDERS: Optional[bool] = None
    SERIES_INCLUDE_NAME_IN_FILENAME: Optional[bool] = None
    SYNC_PARALLELISM_MOVIES: Optional[int] = None
    SYNC_PARALLELISM_SERIES: Optional[int] = None
    SERIES_USE_CATEGORY_FOLDERS: Optional[bool] = None
    MOVIE_USE_CATEGORY_FOLDERS: Optional[bool] = None
    PLEX_PROXY_BASE_URL: Optional[str] = None
    PLEX_SHARED_KEY: Optional[str] = None
    PLEX_HLS_PROXY_MODE: Optional[bool] = None

class ConfigResponse(BaseModel):
    XC_URL: Optional[str] = None
    XC_USER: Optional[str] = None
    XC_PASS: Optional[str] = None
    OUTPUT_DIR: Optional[str] = None
    MOVIES_DIR: Optional[str] = None
    SERIES_DIR: Optional[str] = None
    PREFIX_REGEX: Optional[str] = None
    FORMAT_DATE_IN_TITLE: Optional[bool] = None
    CLEAN_NAME: Optional[bool] = None
    SERIES_USE_SEASON_FOLDERS: Optional[bool] = None
    SERIES_USE_CATEGORY_FOLDERS: Optional[bool] = None
    SERIES_INCLUDE_NAME_IN_FILENAME: Optional[bool] = None
    SYNC_PARALLELISM_MOVIES: Optional[int] = None
    SYNC_PARALLELISM_SERIES: Optional[int] = None
    SERIES_USE_CATEGORY_FOLDERS: Optional[bool] = None
    MOVIE_USE_CATEGORY_FOLDERS: Optional[bool] = None
    PLEX_PROXY_BASE_URL: Optional[str] = None
    PLEX_SHARED_KEY: Optional[str] = None
    PLEX_HLS_PROXY_MODE: Optional[bool] = None

class SyncStatusResponse(BaseModel):
    id: Optional[int] = None
    subscription_id: int
    type: str
    last_sync: Optional[datetime]
    status: str
    items_added: int
    items_deleted: int
    error_message: Optional[str] = None

class M3USyncStatusResponse(BaseModel):
    id: Optional[int] = None
    m3u_source_id: int
    type: str
    last_sync: Optional[datetime]
    status: str
    items_added: int
    items_deleted: int
    error_message: Optional[str] = None

class SyncTriggerResponse(BaseModel):
    message: str
    task_id: str

class CategoryBase(BaseModel):
    category_id: str
    category_name: str

class CategoryResponse(CategoryBase):
    selected: bool
    item_count: int = 0

class SelectionUpdate(BaseModel):
    categories: list[CategoryBase]

class SyncResponse(BaseModel):
    categories_synced: int
    timestamp: datetime

class SubscriptionBase(BaseModel):
    name: str
    xtream_url: str
    username: str
    password: str
    movies_dir: str
    series_dir: str
    download_movies_dir: Optional[str] = "/output/downloads/movies"
    download_series_dir: Optional[str] = "/output/downloads/series"
    max_parallel_downloads: int = 2
    download_segments: int = 1
    is_active: bool = True

class SubscriptionCreate(SubscriptionBase):
    pass

class SubscriptionUpdate(BaseModel):
    name: Optional[str] = None
    xtream_url: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    movies_dir: Optional[str] = None
    series_dir: Optional[str] = None
    download_movies_dir: Optional[str] = None
    download_series_dir: Optional[str] = None
    max_parallel_downloads: Optional[int] = None
    download_segments: Optional[int] = None
    is_active: Optional[bool] = None

class SubscriptionResponse(SubscriptionBase):
    id: int

    class Config:
        from_attributes = True

class MonitoredMediaCreate(BaseModel):
    subscription_id: int
    media_type: str
    media_id: str
    title: str

class DownloadQueueCreate(BaseModel):
    subscription_id: int
    media_type: str
    media_id: int | str

class DownloadBulkQueueCreate(BaseModel):
    subscription_id: int
    media_ids: list[int | str]
    media_type: str
    titles: Optional[list[str]] = None

class DownloadSettingsUpdate(BaseModel):
    max_parallel_downloads: Optional[int] = None
    download_base_path: Optional[str] = None

class DownloadTaskResponse(BaseModel):
    id: int
    subscription_id: int
    media_type: str
    media_id: int
    title: str
    url: str
    save_path: Optional[str] = None
    status: str
    progress: float
    file_size: Optional[int] = None
    downloaded_bytes: int
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    priority: int
    retry_count: int
    max_retries: int
    next_retry_at: Optional[datetime] = None
    paused_at: Optional[datetime] = None
    current_speed_kbps: float
    estimated_time_remaining: Optional[int] = None
    scheduled_start_at: Optional[datetime] = None
    thumbnail_url: Optional[str] = None

    class Config:
        from_attributes = True

class DownloadSettingsGlobalResponse(BaseModel):
    id: int
    global_speed_limit_kbps: int
    per_download_speed_limit_kbps: Optional[int] = None
    quiet_hours_enabled: bool
    quiet_hours_start: str
    quiet_hours_end: str
    pause_during_quiet_hours: bool
    download_mode: str
    default_max_retries: int
    retry_delay_base_seconds: int
    retry_delay_multiplier: float
    max_redirects: int
    connection_timeout_seconds: int
    keep_completed_days: int
    keep_failed_days: int
    auto_cleanup_enabled: bool
    updated_at: datetime

    class Config:
        from_attributes = True

class DownloadSettingsGlobalUpdate(BaseModel):
    global_speed_limit_kbps: Optional[int] = None
    per_download_speed_limit_kbps: Optional[int] = None
    quiet_hours_enabled: Optional[bool] = None
    quiet_hours_start: Optional[str] = None
    quiet_hours_end: Optional[str] = None
    pause_during_quiet_hours: Optional[bool] = None
    download_mode: Optional[str] = None
    default_max_retries: Optional[int] = None
    retry_delay_base_seconds: Optional[int] = None
    retry_delay_multiplier: Optional[float] = None
    max_redirects: Optional[int] = None
    connection_timeout_seconds: Optional[int] = None
    keep_completed_days: Optional[int] = None
    keep_failed_days: Optional[int] = None
    auto_cleanup_enabled: Optional[bool] = None

class DownloadStatisticsResponse(BaseModel):
    id: int
    date: str
    total_downloads: int
    completed_downloads: int
    failed_downloads: int
    cancelled_downloads: int
    total_bytes_downloaded: float
    average_speed_kbps: float

    class Config:
        from_attributes = True

class LiveConfigBase(BaseModel):
    subscription_id: int
    included_categories: list[str] = []
    excluded_streams: list[str] = []

class LiveConfigCreate(LiveConfigBase):
    pass

class LiveConfigUpdate(LiveConfigBase):
    pass

class LiveConfig(LiveConfigBase):
    id: int

    class Config:
        from_attributes = True


# Jellyfin Integration Schemas
class JellyfinConfigUpdate(BaseModel):
    url: Optional[str] = None
    api_token: Optional[str] = None
    movies_library_id: Optional[str] = None
    series_library_id: Optional[str] = None
    refresh_enabled: Optional[bool] = None


class JellyfinConfigResponse(BaseModel):
    url: Optional[str] = None
    api_token_set: bool = False
    movies_library_id: Optional[str] = None
    movies_library_name: Optional[str] = None
    series_library_id: Optional[str] = None
    series_library_name: Optional[str] = None
    refresh_enabled: bool = False
    is_configured: bool = False


class JellyfinLibrary(BaseModel):
    id: str
    name: str
    collection_type: Optional[str] = None


class JellyfinLibrariesResponse(BaseModel):
    libraries: List[JellyfinLibrary] = []
    error: Optional[str] = None


class JellyfinTestResponse(BaseModel):
    success: bool
    message: str
    server_name: Optional[str] = None
    version: Optional[str] = None


# --- Live TV v2 Playlists ---

class LivePlaylistChannelBase(BaseModel):
    stream_id: str
    custom_name: Optional[str] = None
    order: int = 0
    is_excluded: bool = False
    epg_channel_id: Optional[str] = None

class LivePlaylistChannelCreate(LivePlaylistChannelBase):
    bouquet_id: int

class LivePlaylistChannelUpdate(BaseModel):
    custom_name: Optional[str] = None
    order: Optional[int] = None
    is_excluded: Optional[bool] = None
    epg_channel_id: Optional[str] = None

class LivePlaylistChannel(LivePlaylistChannelBase):
    id: int
    bouquet_id: int
    model_config = ConfigDict(from_attributes=True)

class LivePlaylistBouquetBase(BaseModel):
    id: Optional[int] = None
    category_id: Optional[str] = None
    custom_name: Optional[str] = None
    order: int = 0

class LivePlaylistChannelMove(BaseModel):
    new_bouquet_id: int
    new_order: int

class LivePlaylistBouquetCreate(LivePlaylistBouquetBase):
    playlist_id: int

class LivePlaylistBouquetUpdate(BaseModel):
    custom_name: Optional[str] = None
    order: Optional[int] = None

class LivePlaylistBouquet(LivePlaylistBouquetBase):
    id: int
    playlist_id: int
    channels: List[LivePlaylistChannel] = []
    model_config = ConfigDict(from_attributes=True)

class LivePlaylistBase(BaseModel):
    subscription_id: int
    name: str
    description: Optional[str] = None

class LivePlaylistCreate(LivePlaylistBase):
    pass

class LivePlaylistUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None

class LivePlaylist(LivePlaylistBase):
    id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

class LivePlaylistDetail(LivePlaylist):
    bouquets: List[LivePlaylistBouquet] = []
    epg_sources: List["EPGSourceResponse"] = []
    model_config = ConfigDict(from_attributes=True)

# --- EPG Engine v3.3.0 ---

class EPGSourceBase(BaseModel):
    source_type: str  # "xtream", "url", "file"
    source_url: Optional[str] = None
    file_path: Optional[str] = None
    priority: int = 0
    is_active: bool = True

class EPGSourceCreate(EPGSourceBase):
    playlist_id: int

class EPGSourceUpdate(BaseModel):
    source_url: Optional[str] = None
    file_path: Optional[str] = None
    priority: Optional[int] = None
    is_active: Optional[bool] = None

class EPGSourceResponse(EPGSourceBase):
    id: int
    playlist_id: int
    last_updated: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)

class EPGMappingUpdate(BaseModel):
    epg_channel_id: Optional[str] = None

class LivePlaylistChannelBulkDelete(BaseModel):
    channel_ids: List[int]


# --- Plex Integration Schemas ---

class PlexLoginRequest(BaseModel):
    """Request to test Plex.tv login credentials."""
    username: str
    password: str
    code: Optional[str] = None  # Two-factor code, when the account requires one


class PlexAccountTokenRefresh(BaseModel):
    """
    Request to renew the stored Plex.tv token of an existing account.

    @description Only the password is needed: the username is already stored,
    and renewing in place avoids deleting the account, which would cascade to
    its servers, libraries, caches and schedules.
    """
    password: str
    code: Optional[str] = None


class PlexTokenRefreshResponse(BaseModel):
    """Result of a Plex.tv token renewal and the server refresh that follows."""
    success: bool
    message: str
    servers_refreshed: int = 0
    unreachable: List[str] = []


class PlexLoginResponse(BaseModel):
    """Response from Plex.tv login attempt."""
    success: bool
    message: str
    auth_token: Optional[str] = None
    username: Optional[str] = None


class PlexAccountBase(BaseModel):
    """Base schema for Plex account."""
    name: str
    username: str
    output_base_dir: str = "/output/plex"


class PlexAccountCreate(PlexAccountBase):
    """Schema for creating a Plex account (requires password for login)."""
    password: str


class PlexAccountResponse(PlexAccountBase):
    """Response schema for Plex account."""
    id: int
    is_active: bool

    class Config:
        from_attributes = True


class PlexServerBase(BaseModel):
    """Base schema for Plex server."""
    server_id: str
    name: str
    uri: str
    is_owned: bool
    is_selected: bool = False


class PlexServerResponse(PlexServerBase):
    """Response schema for Plex server."""
    id: int
    account_id: int
    movies_dir: str
    series_dir: str
    last_sync: Optional[datetime] = None
    version: Optional[str] = None

    class Config:
        from_attributes = True


class PlexServerUpdate(BaseModel):
    """Schema for updating Plex server settings."""
    is_selected: Optional[bool] = None
    movies_dir: Optional[str] = None
    series_dir: Optional[str] = None


class PlexLibraryBase(BaseModel):
    """Base schema for Plex library."""
    library_key: str
    title: str
    type: str  # "movie" or "show"
    item_count: int = 0


class PlexLibraryResponse(PlexLibraryBase):
    """Response schema for Plex library."""
    id: int
    server_id: int
    is_selected: bool
    last_sync: Optional[datetime] = None

    class Config:
        from_attributes = True


class PlexLibrarySelection(BaseModel):
    """Schema for updating library selection."""
    library_ids: List[int]


class PlexSyncStatusResponse(BaseModel):
    """Response schema for Plex sync status."""
    id: Optional[int] = None
    server_id: int
    type: str
    last_sync: Optional[datetime] = None
    status: str
    items_added: int
    items_deleted: int
    error_message: Optional[str] = None
    task_id: Optional[str] = None

    class Config:
        from_attributes = True
