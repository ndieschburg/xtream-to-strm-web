import httpx
import logging
from lxml import etree
from datetime import datetime
from typing import List, Optional
from app.models.live import EPGSource, LivePlaylist
from app.core.redis import get_redis
from app.core.config import settings

logger = logging.getLogger(__name__)

class EPGService:
    def __init__(self):
        self.redis = get_redis()

    async def fetch_and_cache_epg(self, source: EPGSource):
        """Fetch XMLTV from source and cache in Redis."""
        logger.info(f"fetching EPG from {source.source_url or source.file_path}")
        
        try:
            content = None
            if source.source_type == "url" and source.source_url:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    resp = await client.get(source.source_url)
                    resp.raise_for_status()
                    content = resp.content
            elif source.source_type == "file" and source.file_path:
                with open(source.file_path, "rb") as f:
                    content = f.read()
            elif source.source_type == "xtream":
                # Xtream XMLTV is handled a bit differently or mapped to a URL
                # For now, we assume url/file are the main drivers.
                pass

            if not content:
                logger.error("No content to parse")
                return

            self._parse_and_cache_xml(source.id, content)
            
        except Exception as e:
            logger.error(f"Failed to fetch/cache EPG: {e}")

    def _parse_and_cache_xml(self, source_id: int, content: bytes):
        """Parse XMLTV and store channel list and programs in Redis."""
        try:
            parser = etree.XMLParser(recover=True)
            tree = etree.fromstring(content, parser=parser)
            
            # 1. Cache Channels
            channels = tree.xpath("//channel")
            channel_ids = []
            for ch in channels:
                ch_id = ch.get("id")
                if ch_id:
                    channel_ids.append(ch_id)
                    # Store channel details (displayName, icon)
                    display_name = ch.findtext("display-name")
                    icon = ch.find("icon").get("src") if ch.find("icon") is not None else ""
                    self.redis.hset(f"epg:src:{source_id}:channel:{ch_id}", mapping={
                        "name": display_name or "",
                        "icon": icon or ""
                    })
            
            if channel_ids:
                # Store the list of IDs for search/mapping
                self.redis.delete(f"epg:src:{source_id}:channels")
                self.redis.sadd(f"epg:src:{source_id}:channels", *channel_ids)

            # 2. Cache Programs (simplified version for now)
            # We only store current/future programs (next 24h) to save memory
            now = datetime.now().timestamp()
            programs = tree.xpath("//programme")
            
            # Group programs by channel to avoid too many redis calls
            channel_programs = {}
            for prog in programs:
                ch_id = prog.get("channel")
                start_str = prog.get("start") # Format: 20260210110000 +0100
                stop_str = prog.get("stop")
                
                if not ch_id or not start_str: continue
                
                start_ts = self._parse_xmltv_date(start_str)
                stop_ts = self._parse_xmltv_date(stop_str) if stop_str else start_ts + 3600
                
                if stop_ts < now: continue # Skip past programs
                
                title = prog.findtext("title")
                desc = prog.findtext("desc") or ""
                
                prog_data = {
                    "start": start_ts,
                    "stop": stop_ts,
                    "title": title,
                    "desc": desc
                }
                
                if ch_id not in channel_programs: channel_programs[ch_id] = []
                channel_programs[ch_id].append(prog_data)

            # Bulk write to Redis
            for ch_id, progs in channel_programs.items():
                key = f"epg:src:{source_id}:prog:{ch_id}"
                self.redis.delete(key)
                for p in progs:
                    # Use zadd with start_ts as score for easy range queries
                    import json
                    self.redis.zadd(key, {json.dumps(p): p["start"]})
                self.redis.expire(key, 86400) # Expire in 24h

            logger.info(f"Successfully cached {len(channel_ids)} channels and programs for source {source_id}")

        except Exception as e:
            logger.error(f"Error parsing XMLTV: {e}")

    def _parse_xmltv_date(self, date_str: str) -> float:
        """Parse XMLTV date format (YYYYMMDDHHMMSS [+/-]HHMM)"""
        # Format: 20260210110000 +0100
        try:
            # Strip timezone for simplicity if needed, or parse properly
            clean_date = date_str.split(" ")[0]
            dt = datetime.strptime(clean_date[:14], "%Y%m%d%H%M%S")
            return dt.timestamp()
        except Exception:
            return 0.0

    def search_channels(self, source_id: int, query: str) -> List[dict]:
        """Search available channels in a source."""
        all_ids = self.redis.smembers(f"epg:src:{source_id}:channels")
        results = []
        query = query.lower()
        
        for ch_id in all_ids:
            details = self.redis.hgetall(f"epg:src:{source_id}:channel:{ch_id}")
            name = details.get("name", "").lower()
            if query in ch_id.lower() or query in name:
                results.append({
                    "id": ch_id,
                    "name": details.get("name"),
                    "icon": details.get("icon")
                })
        return results[:50] # Limit results

    def generate_playlist_xmltv(self, playlist: LivePlaylist) -> str:
        """Generate a custom XMLTV guide for a specific playlist."""
        logger.info(f"Generating custom XMLTV for playlist {playlist.id}")
        
        # 1. Start XML
        root = etree.Element("tv", generator_info_name="XtreamToSTRM EPG Proxy")
        
        # 2. Get active EPG sources for this playlist (sorted by priority)
        sources = sorted([s for s in playlist.epg_sources if s.is_active], key=lambda x: x.priority, reverse=True)
        if not sources:
            return etree.tostring(root, encoding="utf-8", xml_declaration=True, pretty_print=True).decode()

        # 3. Get all channels in the playlist
        # Map them by epg_channel_id
        selected_channels = []
        for bouquet in playlist.bouquets:
            for channel in bouquet.channels:
                if not channel.is_excluded:
                    selected_channels.append(channel)

        # 4. For each selected channel, fetch programs from prioritized sources
        import json
        now = datetime.now().timestamp()
        
        for channel in selected_channels:
            epg_id = channel.epg_channel_id
            if not epg_id: continue # No mapping
            
            # Find first source that has this channel
            target_source = None
            for src in sources:
                if self.redis.sismember(f"epg:src:{src.id}:channels", epg_id):
                    target_source = src
                    break
            
            if not target_source: continue
            
            # Add channel element
            chan_details = self.redis.hgetall(f"epg:src:{target_source.id}:channel:{epg_id}")
            chan_elem = etree.SubElement(root, "channel", id=epg_id)
            etree.SubElement(chan_elem, "display-name").text = chan_details.get("name") or epg_id
            if chan_details.get("icon"):
                etree.SubElement(chan_elem, "icon", src=chan_details.get("icon"))

            # Add programs
            prog_key = f"epg:src:{target_source.id}:prog:{epg_id}"
            # Get programs that stop after now
            progs = self.redis.zrangebyscore(prog_key, now, "+inf")
            for p_json in progs:
                p_data = json.loads(p_json)
                p_elem = etree.SubElement(root, "programme", 
                    channel=epg_id,
                    start=self._format_xmltv_date(p_data["start"]),
                    stop=self._format_xmltv_date(p_data["stop"])
                )
                etree.SubElement(p_elem, "title").text = p_data["title"]
                if p_data.get("desc"):
                    etree.SubElement(p_elem, "desc").text = p_data["desc"]

        return etree.tostring(root, encoding="utf-8", xml_declaration=True, pretty_print=True).decode()

    def _format_xmltv_date(self, ts: float) -> str:
        """Format timestamp to XMLTV date string."""
        dt = datetime.fromtimestamp(ts)
        return dt.strftime("%Y%m%d%H%M%S +0000")

    async def auto_match_channels(self, playlist: LivePlaylist, db_session):
        """Try to automatically match channels to EPG using fuzzy matching."""
        from rapidfuzz import process, fuzz
        from app.services.xtream import XtreamClient
        import re
        
        sources = [s for s in playlist.epg_sources if s.is_active]
        if not sources: return 0
        
        # 1. Build EPG name pool
        epg_pool = []
        epg_names = []
        for src in sources:
            all_ids = self.redis.smembers(f"epg:src:{src.id}:channels")
            for ch_id in all_ids:
                details = self.redis.hgetall(f"epg:src:{src.id}:channel:{ch_id}")
                if details.get("name"):
                    name = details.get("name")
                    epg_pool.append({"name": name, "id": ch_id})
                    epg_names.append(name)

        if not epg_pool: return 0

        # Helper to clean channel names for better matching
        def clean_name(n: str):
            if not n: return ""
            # 1. Normalize unicode (e.g., ᴿᴬᵂ -> RAW)
            import unicodedata
            n = unicodedata.normalize('NFKD', n).encode('ascii', 'ignore').decode('ascii')
            
            # 2. Remove any prefix before ":" or "|" (e.g., "PRIME: TIJI" -> "TIJI")
            n = re.sub(r'^.*?[:|]\s*', '', n)
            
            # 3. Remove common tags/suffixes
            n = re.sub(r'(\b)(HD|SD|FHD|4K|UHD|FR|EN|ES|DE|IT|VIP|BACKUP|H265|HEVC|REPLAY|AC3|RAW)(\b)', r'\1\3', n, flags=re.IGNORECASE)
            
            # 4. Remove special characters and normalize whitespace
            n = re.sub(r'[^a-zA-Z0-9]', ' ', n)
            return " ".join(n.split()).lower()

        clean_epg_names = [clean_name(name) for name in epg_names]
        # Map cleaned name to original index
        clean_map = {i: name for i, name in enumerate(clean_epg_names)}

        # 2. Fetch stream names
        sub = playlist.subscription
        client = XtreamClient(sub.xtream_url, sub.username, sub.password)
        try:
            all_streams_list = await client.get_live_streams()
            stream_map = {str(s.get("stream_id")): s.get("name") for s in all_streams_list}
        except Exception as e:
            logger.error(f"Failed to fetch streams: {e}")
            stream_map = {}
        finally:
            await client.aclose()

        # 3. Perform matching
        match_count = 0
        for bouquet in playlist.bouquets:
            for channel in bouquet.channels:
                if channel.epg_channel_id: continue
                
                target_name = channel.custom_name or stream_map.get(str(channel.stream_id))
                if not target_name: continue
                
                clean_target = clean_name(target_name)
                if not clean_target: continue

                # First try exact match on cleaned names
                found_idx = None
                if clean_target in clean_epg_names:
                    found_idx = clean_epg_names.index(clean_target)
                    score = 100
                else:
                    # Strategy 1: Token Sort Ratio (most reliable for word rearrangements)
                    result = process.extractOne(clean_target, clean_epg_names, scorer=fuzz.token_sort_ratio)
                    if result and result[1] >= 85:
                        found_idx = result[2]
                        score = result[1]
                    else:
                        # Strategy 2: Partial Token Sort Ratio (better for "PRIME: TIJI" vs "TIJI")
                        # We only use this if the target is long enough to avoid false positives
                        if len(clean_target) >= 3:
                            result = process.extractOne(clean_target, clean_epg_names, scorer=fuzz.partial_token_sort_ratio)
                            if result and result[1] >= 90: # Higher threshold for partial matches
                                found_idx = result[2]
                                score = result[1]
                
                if found_idx is not None:
                    original_name = epg_names[found_idx]
                    epg_id = next((e["id"] for e in epg_pool if e["name"] == original_name), None)
                    if epg_id:
                        channel.epg_channel_id = epg_id
                        match_count += 1
                        logger.info(f"Auto-matched '{target_name}' -> '{original_name}' (Score: {score})")
        
        if match_count > 0:
            db_session.commit()
        return match_count

epg_service = EPGService()
