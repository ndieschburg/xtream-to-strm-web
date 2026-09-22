-- Add change-detection columns to plex_series_cache
-- Lets the series sync skip get_show_episodes for shows Plex reports as unchanged,
-- instead of calling the API once per show on every run.
-- updated_at catches metadata edits, leaf_count catches added/removed episodes.

ALTER TABLE plex_series_cache ADD COLUMN updated_at VARCHAR;
ALTER TABLE plex_series_cache ADD COLUMN leaf_count INTEGER;
