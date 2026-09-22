import os
import aiofiles
import re
from typing import Optional

class FileManager:
    def __init__(self, output_dir: str):
        self.output_dir = output_dir

    def sanitize_name(self, name: str) -> str:
        # Replace invalid characters with underscore
        sanitized = re.sub(r'[\\/:*?"<>|]', '_', name)
        
        # Truncate to max 200 characters to ensure full path stays under 255
        # (leaving room for directory path, extension, etc.)
        max_length = 200
        if len(sanitized) > max_length:
            sanitized = sanitized[:max_length]
        
        return sanitized


    def ensure_directory(self, path: str):
        os.makedirs(path, exist_ok=True)

    async def _read_existing(self, path: str) -> Optional[str]:
        """Read a file for comparison purposes, None if unreadable"""
        try:
            async with aiofiles.open(path, 'r', encoding='utf-8', errors='replace') as f:
                return await f.read()
        except (OSError, ValueError):
            return None

    async def _write_if_changed(self, path: str, content: str) -> bool:
        """
        Write content only when it differs from what is already on disk.

        Media servers (Jellyfin/Kodi) use the modification time to decide what
        to rescan, so an unchanged file must keep its mtime untouched.

        @param path Path to the file
        @param content Content to write
        @returns True if the file was written, False if left untouched
        """
        if os.path.exists(path):
            existing_content = await self._read_existing(path)
            # Unreadable file: rewrite it rather than leaving it broken
            if existing_content is not None and existing_content.strip() == content.strip():
                return False

        async with aiofiles.open(path, 'w', encoding='utf-8') as f:
            await f.write(content)
        return True

    async def write_strm(self, path: str, url: str) -> bool:
        """
        Write STRM file only if content has changed.

        @param path Path to the STRM file
        @param url URL content to write
        @returns True if file was written, False if unchanged
        """
        return await self._write_if_changed(path, url)

    async def write_nfo(self, path: str, content: str, skip_if_exists: bool = False) -> bool:
        """
        Write NFO file only if content has changed.

        @param path Path to the NFO file
        @param content NFO XML content to write
        @param skip_if_exists If True, never overwrite existing NFO files
        @returns True if file was written, False if unchanged/skipped
        """
        if skip_if_exists and os.path.exists(path):
            return False

        return await self._write_if_changed(path, content)

    async def delete_file(self, path: str):
        if os.path.exists(path):
            os.remove(path)

    async def delete_directory_if_empty(self, path: str):
        try:
            os.rmdir(path)
        except OSError:
            pass # Directory not empty

    def clean_title(self, title: str, prefix_regex: Optional[str] = None, format_date: bool = False, clean_name: bool = False) -> str:
        """Centralized logic to clean media titles based on settings"""
        if not title:
            return "Unknown"
            
        # Strip language prefix
        regex = prefix_regex if prefix_regex else r'^(?:[A-Za-z0-9.-]+_|[A-Za-z]{2,}\s*-\s*)'
        try:
            title = re.sub(regex, '', title)
        except re.error:
            title = re.sub(r'^(?:[A-Za-z0-9.-]+_|[A-Za-z]{2,}\s*-\s*)', '', title)
            
        # Format date at end (e.g. "Movie_2024" -> "Movie (2024)")
        if format_date:
            title = re.sub(r'[_\s](\d{4})$', r' (\1)', title)
            
        # Clean name (underscores to spaces)
        if clean_name:
            title = title.replace('_', ' ')
            
        return title.strip()

    def get_movie_target_info(self, movie_data: dict, cat_name: str, prefix_regex: Optional[str] = None, format_date: bool = False, clean_name: bool = False, use_category_folders: bool = True) -> dict:
        """Determine target directory and filename for a movie"""
        name = movie_data.get('name', 'Unknown')
        o_name = movie_data.get('o_name')
        tmdb_id = movie_data.get('tmdb') or movie_data.get('tmdb_id', '')
        
        # Priority for cleaning: o_name > name
        title_to_clean = o_name or name
        cleaned_title = self.clean_title(title_to_clean, prefix_regex, format_date, clean_name)
        
        safe_cat = self.sanitize_name(cat_name)
        safe_title = self.sanitize_name(cleaned_title)
        
        cat_dir = os.path.join(self.output_dir, safe_cat)
        
        if use_category_folders:
            base_parent_dir = cat_dir
        else:
            base_parent_dir = self.output_dir

        if tmdb_id and str(tmdb_id) not in ['0', 'None', 'null', '']:
            folder_name = f"{safe_title} {{tmdb-{tmdb_id}}}"
            target_dir = os.path.join(base_parent_dir, folder_name)
            filename_base = folder_name
        else:
            target_dir = base_parent_dir
            filename_base = safe_title
            
        return {
            "cat_dir": cat_dir,
            "target_dir": target_dir,
            "filename_base": filename_base,
            "cleaned_title": cleaned_title,
            "tmdb_id": tmdb_id if tmdb_id and str(tmdb_id) not in ['0', 'None', 'null', ''] else None
        }

    def get_series_target_info(self, series_data: dict, cat_name: str, prefix_regex: Optional[str] = None, format_date: bool = False, clean_name: bool = False, use_category_folders: bool = True) -> dict:
        """Determine target directory and base folder name for a series"""
        name = series_data.get('name', 'Unknown')
        o_name = series_data.get('o_name')
        tmdb_id = series_data.get('tmdb') or series_data.get('tmdb_id', '')
        
        title_to_clean = o_name or name
        cleaned_title = self.clean_title(title_to_clean, prefix_regex, format_date, clean_name)
        
        safe_cat = self.sanitize_name(cat_name)
        safe_title = self.sanitize_name(cleaned_title)
        
        if use_category_folders:
            base_parent_dir = os.path.join(self.output_dir, safe_cat)
        else:
            base_parent_dir = self.output_dir
            
        if tmdb_id and str(tmdb_id) not in ['0', 'None', 'null', '']:
            folder_name = f"{safe_title} {{tmdb-{tmdb_id}}}"
        else:
            folder_name = safe_title
            
        series_dir = os.path.join(base_parent_dir, folder_name)
        
        return {
            "cat_dir": os.path.join(self.output_dir, safe_cat),
            "series_dir": series_dir,
            "folder_name": folder_name,
            "cleaned_title": cleaned_title,
            "safe_series_name": safe_title,
            "tmdb_id": tmdb_id if tmdb_id and str(tmdb_id) not in ['0', 'None', 'null', ''] else None
        }

    def build_episode_filename(self, safe_series_name: str, season_num: int, episode_num: int,
                               title: Optional[str] = None, container_extension: Optional[str] = None,
                               include_series_name: bool = False) -> str:
        """
        Build the base filename of an episode, without extension.

        Shared by the sync (file creation) and the cleanup (file removal) so
        both always agree on the name of a given episode.
        """
        filename = f"S{season_num:02d}E{episode_num:02d}"

        if include_series_name and safe_series_name:
            filename = f"{safe_series_name} - {filename}"

        if title:
            # Some panels put the container extension in the episode title
            if container_extension and title.lower().endswith(f".{container_extension.lower()}"):
                title = title[:-len(container_extension) - 1]

            safe_title = self.sanitize_name(title)
            if safe_title:
                filename = f"{filename} - {safe_title}"

        return filename

    def generate_movie_nfo(self, movie_data: dict, prefix_regex: Optional[str] = None, format_date: bool = False, clean_name: bool = False) -> str:
        """Generate NFO file for a movie with comprehensive metadata"""
        tmdb_id = movie_data.get('tmdb') or movie_data.get('tmdb_id', '')
        title = self.clean_title(movie_data.get('o_name') or movie_data.get('name', 'Unknown'), prefix_regex, format_date, clean_name)
        
        plot = movie_data.get('plot') or movie_data.get('description', '')
        year = movie_data.get('year') or movie_data.get('releasedate', '')
        rating = movie_data.get('rating') or movie_data.get('rating_5based', '')
        genre = movie_data.get('genre', '')
        director = movie_data.get('director', '')
        cast_list = movie_data.get('cast') or movie_data.get('actors', '')
        duration = movie_data.get('duration') or movie_data.get('episode_run_time', '')
        trailer = movie_data.get('youtube_trailer', '')
        cover = movie_data.get('movie_image') or movie_data.get('cover_big') or movie_data.get('stream_icon') or movie_data.get('backdrop_path_original', '')
        
        # Handle backdrop/fanart
        backdrop_path = movie_data.get('backdrop_path', [])
        fanart = backdrop_path[0] if isinstance(backdrop_path, list) and backdrop_path else ''
        
        nfo = '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>\n<movie>\n'
        
        nfo += f'  <title>{self._escape_xml(title)}</title>\n'
        nfo += f'  <originaltitle>{self._escape_xml(movie_data.get("o_name", ""))}</originaltitle>\n'
        
        # TMDB / IMDB IDs
        if tmdb_id and str(tmdb_id) not in ['0', 'None', 'null', '']:
            nfo += f'  <tmdbid>{tmdb_id}</tmdbid>\n'
            nfo += f'  <uniqueid type="tmdb" default="true">{tmdb_id}</uniqueid>\n'
        
        # Try to find IMDB ID in info if available
        # (This usually requires detailed info fetch)
        
        if plot:
            nfo += f'  <plot>{self._escape_xml(plot)}</plot>\n'
            nfo += f'  <outline>{self._escape_xml(plot[:200])}</outline>\n'
        
        if year:
            year_str = str(year)[:4] if len(str(year)) >= 4 else str(year)
            nfo += f'  <year>{year_str}</year>\n'
            nfo += f'  <premiered>{year_str}-01-01</premiered>\n'
        
        # Ratings
        if rating:
            try:
                r_val = float(rating)
                # If it was 5-based, convert
                if movie_data.get('rating_5based'):
                    r_val *= 2
                
                nfo += '  <ratings>\n'
                nfo += f'    <rating name="tmdb" default="true"><value>{r_val:.1f}</value></rating>\n'
                nfo += '  </ratings>\n'
                nfo += f'  <userrating>{int(round(r_val))}</userrating>\n'
            except (ValueError, TypeError):
                pass
        
        # Genre
        if genre:
            # Split by comma or slash
            for g in re.split(r'[,/]', str(genre)):
                g_str = g.strip()
                if g_str:
                    nfo += f'  <genre>{self._escape_xml(g_str)}</genre>\n'
        
        # Director
        if director:
            nfo += f'  <director>{self._escape_xml(director)}</director>\n'
        
        # Cast
        if cast_list:
            for actor in str(cast_list).split(','):
                actor_name = actor.strip()
                if actor_name:
                    nfo += f'  <actor><name>{self._escape_xml(actor_name)}</name></actor>\n'
        
        # Duration
        if duration:
            try:
                total_mins = 0
                if ':' in str(duration):
                    parts = str(duration).split(':')
                    total_mins = int(parts[0]) * 60 + int(parts[1])
                else:
                    total_mins = int(duration)
                nfo += f'  <runtime>{total_mins}</runtime>\n'
            except (ValueError, TypeError, IndexError):
                pass

        # Stream Details (Video/Audio)
        # Usually from detailed info 'info' dict
        info = movie_data.get('info', {})
        nfo += '  <fileinfo>\n    <streamdetails>\n'
        
        # Video
        nfo += '      <video>\n'
        nfo += f'        <codec>{self._escape_xml(movie_data.get("container_extension", ""))}</codec>\n'
        if info.get('videoing'): # Check if present
             pass # Use info from API if mapped
        if info.get('bitrate'):
             nfo += f'        <bitrate>{info.get("bitrate")}</bitrate>\n'
        nfo += '      </video>\n'
        
        # Audio
        if info.get('audio'):
             nfo += '      <audio>\n'
             nfo += f'        <codec>{self._escape_xml(info.get("audio", {}).get("codec", ""))}</codec>\n'
             nfo += '      </audio>\n'
             
        nfo += '    </streamdetails>\n  </fileinfo>\n'

        if trailer:
            nfo += f'  <trailer>plugin://plugin.video.youtube/?action=play_video&amp;videoid={trailer}</trailer>\n'
        
        if cover:
            nfo += f'  <thumb>{cover}</thumb>\n'
        
        if fanart:
            nfo += f'  <fanart><thumb>{fanart}</thumb></fanart>\n'
        elif cover:
            nfo += f'  <fanart><thumb>{cover}</thumb></fanart>\n'
            
        # MPAA
        mpaa = movie_data.get('mpaa') or info.get('mpaa')
        if mpaa:
             nfo += f'  <mpaa>{self._escape_xml(mpaa)}</mpaa>\n'
        
        nfo += '</movie>'
        return nfo


    def generate_show_nfo(self, series_data: dict, prefix_regex: Optional[str] = None, format_date: bool = False, clean_name: bool = False) -> str:
        """Generate NFO file for a TV show"""
        tmdb_id = series_data.get('tmdb') or series_data.get('tmdb_id', '')
        title = self.clean_title(series_data.get('o_name') or series_data.get('name', 'Unknown'), prefix_regex, format_date, clean_name)
        
        plot = series_data.get('plot') or series_data.get('description', '')
        year = series_data.get('year') or series_data.get('releaseDate', '')
        rating = series_data.get('rating') or series_data.get('rating_5based', '')
        genre = series_data.get('genre', '')
        cast_list = series_data.get('cast') or series_data.get('actors', '')
        director = series_data.get('director', '')
        cover = series_data.get('cover') or series_data.get('cover_big') or series_data.get('stream_icon') or series_data.get('backdrop_path_original', '')
        
        backdrop_path = series_data.get('backdrop_path', [])
        fanart = backdrop_path[0] if isinstance(backdrop_path, list) and backdrop_path else ''
        
        nfo = '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>\n<tvshow>\n'
        
        nfo += f'  <title>{self._escape_xml(title)}</title>\n'
        
        if tmdb_id and str(tmdb_id) not in ['0', 'None', 'null', '']:
             nfo += f'  <tmdbid>{tmdb_id}</tmdbid>\n'
             nfo += f'  <uniqueid type="tmdb" default="true">{tmdb_id}</uniqueid>\n'

        if plot:
            nfo += f'  <plot>{self._escape_xml(plot)}</plot>\n'
        
        if year:
            year_str = str(year)[:4] if len(str(year)) >= 4 else str(year)
            nfo += f'  <year>{year_str}</year>\n'
            nfo += f'  <premiered>{year_str}-01-01</premiered>\n'
        
        if rating:
            try:
                r_val = float(rating)
                if series_data.get('rating_5based'):
                    r_val *= 2
                
                nfo += '  <ratings>\n'
                nfo += f'    <rating name="tmdb" default="true"><value>{r_val:.1f}</value></rating>\n'
                nfo += '  </ratings>\n'
                nfo += f'  <userrating>{int(round(r_val))}</userrating>\n'
            except (ValueError, TypeError):
                pass
        
        if genre:
            for g in re.split(r'[,/]', str(genre)):
                g_str = g.strip()
                if g_str:
                    nfo += f'  <genre>{self._escape_xml(g_str)}</genre>\n'
        
        if director:
            nfo += f'  <director>{self._escape_xml(director)}</director>\n'
        
        if cast_list:
            for actor in str(cast_list).split(','):
                actor_name = actor.strip()
                if actor_name:
                    nfo += f'  <actor><name>{self._escape_xml(actor_name)}</name></actor>\n'
        
        if cover:
            nfo += f'  <thumb>{cover}</thumb>\n'
        
        if fanart:
            nfo += f'  <fanart><thumb>{fanart}</thumb></fanart>\n'
        elif cover:
            nfo += f'  <fanart><thumb>{cover}</thumb></fanart>\n'
        
        nfo += '</tvshow>'
        return nfo

    def generate_episode_nfo(self, episode_data: dict, series_name: str, season_num: int, episode_num: int) -> str:
        """Generate NFO file for an episode"""
        title = episode_data.get('title', '')
        if not title:
            title = f"Episode {episode_num}"
            
        plot = episode_data.get('info', {}).get('plot') or episode_data.get('plot', '')
        duration = episode_data.get('info', {}).get('duration') or episode_data.get('duration', '')
        
        nfo = '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>\n<episodedetails>\n'
        nfo += f'  <title>{self._escape_xml(title)}</title>\n'
        nfo += f'  <showtitle>{self._escape_xml(series_name)}</showtitle>\n'
        nfo += f'  <season>{season_num}</season>\n'
        nfo += f'  <episode>{episode_num}</episode>\n'
        
        if plot:
            nfo += f'  <plot>{self._escape_xml(plot)}</plot>\n'
            
        # Parse duration "HH:MM:SS" -> minutes
        if duration:
             try:
                total_mins = 0
                if ':' in str(duration):
                    parts = str(duration).split(':')
                    if len(parts) == 3:
                        total_mins = int(parts[0]) * 60 + int(parts[1])
                    elif len(parts) == 2:
                        total_mins = int(parts[0])
                elif str(duration).isdigit():
                     total_mins = int(duration)
                
                if total_mins > 0:
                    nfo += f'  <runtime>{total_mins}</runtime>\n'
             except (ValueError, TypeError):
                 pass

        # Stream Details
        # Usually from detailed info 'info' dict of the episode
        info = episode_data.get('info', {})
        nfo += '  <fileinfo>\n    <streamdetails>\n'
        nfo += '      <video>\n'
        nfo += f'        <codec>{self._escape_xml(episode_data.get("container_extension", ""))}</codec>\n'
        if info.get('bitrate'):
             nfo += f'        <bitrate>{info.get("bitrate")}</bitrate>\n'
        nfo += '      </video>\n'
        nfo += '    </streamdetails>\n  </fileinfo>\n'

        nfo += '</episodedetails>'
        return nfo



    def _escape_xml(self, text: str) -> str:
        """Escape XML special characters"""
        if not text:
            return ''
        return (str(text)
                .replace('&', '&amp;')
                .replace('<', '&lt;')
                .replace('>', '&gt;')
                .replace('"', '&quot;')
                .replace("'", '&apos;'))
