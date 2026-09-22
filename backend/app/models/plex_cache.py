"""
Plex cache models for tracking synced items and detecting changes.

Used for incremental sync - only process items that have changed.
"""
from sqlalchemy import Column, Integer, String, ForeignKey
from app.db.base_class import Base


class PlexMovieCache(Base):
    """
    Cache for Plex movies - tracks synced items for change detection.

    @description Uses plex_key and updated_at to detect changes.
    """
    __tablename__ = "plex_movie_cache"

    id = Column(Integer, primary_key=True, index=True)
    server_id = Column(Integer, ForeignKey("plex_servers.id", ondelete="CASCADE"), nullable=False, index=True)
    library_id = Column(Integer, ForeignKey("plex_libraries.id", ondelete="CASCADE"), nullable=False, index=True)
    plex_key = Column(String, nullable=False, index=True)  # /library/metadata/xxx
    title = Column(String)
    year = Column(String, nullable=True)
    guid = Column(String, nullable=True)  # Plex GUID string (tmdb://xxx, imdb://xxx)
    updated_at = Column(String, nullable=True)  # Plex item's updatedAt timestamp


class PlexSeriesCache(Base):
    """
    Cache for Plex TV shows.

    @description Tracks series for change detection.
    """
    __tablename__ = "plex_series_cache"

    id = Column(Integer, primary_key=True, index=True)
    server_id = Column(Integer, ForeignKey("plex_servers.id", ondelete="CASCADE"), nullable=False, index=True)
    library_id = Column(Integer, ForeignKey("plex_libraries.id", ondelete="CASCADE"), nullable=False, index=True)
    plex_key = Column(String, nullable=False, index=True)
    title = Column(String)
    year = Column(String, nullable=True)
    guid = Column(String, nullable=True)
    updated_at = Column(String, nullable=True)
    leaf_count = Column(Integer, nullable=True)


class PlexEpisodeCache(Base):
    """
    Cache for Plex episodes.

    @description Tracks episodes within a series for change detection.
    """
    __tablename__ = "plex_episode_cache"

    id = Column(Integer, primary_key=True, index=True)
    server_id = Column(Integer, ForeignKey("plex_servers.id", ondelete="CASCADE"), nullable=False, index=True)
    series_key = Column(String, nullable=False, index=True)  # Parent show key
    plex_key = Column(String, nullable=False, index=True)
    season_num = Column(Integer)
    episode_num = Column(Integer)
    title = Column(String, nullable=True)
    updated_at = Column(String, nullable=True)
