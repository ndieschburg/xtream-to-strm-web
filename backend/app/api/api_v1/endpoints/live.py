from typing import Any, List, Optional
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session
from app.api import deps
from app.models.subscription import Subscription
from app.models.live import LivePlaylist, LivePlaylistBouquet, LivePlaylistChannel, LiveStreamSubscription, EPGSource
from app.models import live as models
from app.services.xtream import XtreamClient
from app.services.epg import epg_service
from app import schemas
from datetime import datetime

router = APIRouter()

@router.get("/categories", response_model=List[Any])
async def get_live_categories(
    db: Session = Depends(deps.get_db),
    subscription_id: int = Query(...)
) -> Any:
    """Get all live categories from the Xtream provider."""
    sub = db.query(Subscription).filter(Subscription.id == subscription_id).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")

    client = XtreamClient(sub.xtream_url, sub.username, sub.password)
    try:
        categories = await client.get_live_categories()
        return categories
    except (httpx.ConnectTimeout, httpx.ReadTimeout):
        raise HTTPException(status_code=504, detail="Provider connection timed out")
    except (httpx.ConnectError, httpx.RequestError) as e:
        raise HTTPException(status_code=502, detail=f"Provider connection failed: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch categories: {str(e)}")
    finally:
        await client.aclose()

@router.get("/streams/{category_id}", response_model=List[Any])
async def get_live_streams(
    category_id: str,
    db: Session = Depends(deps.get_db),
    subscription_id: int = Query(...)
) -> Any:
    """Get live streams for a specific category from the Xtream provider."""
    sub = db.query(Subscription).filter(Subscription.id == subscription_id).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")

    client = XtreamClient(sub.xtream_url, sub.username, sub.password)
    try:
        streams = await client.get_live_streams(category_id)
        return streams
    except (httpx.ConnectTimeout, httpx.ReadTimeout):
        raise HTTPException(status_code=504, detail="Provider connection timed out")
    except (httpx.ConnectError, httpx.RequestError) as e:
        raise HTTPException(status_code=502, detail=f"Provider connection failed: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch streams: {str(e)}")
    finally:
        await client.aclose()

# --- Playlist Management ---

@router.get("/playlists", response_model=List[schemas.LivePlaylist])
def list_playlists(
    db: Session = Depends(deps.get_db),
    subscription_id: Optional[int] = Query(None)
) -> Any:
    """List all live playlists, optionally filtered by subscription."""
    query = db.query(LivePlaylist)
    if subscription_id:
        query = query.filter(LivePlaylist.subscription_id == subscription_id)
    return query.all()

@router.post("/playlists", response_model=schemas.LivePlaylist)
def create_playlist(
    playlist_in: schemas.LivePlaylistCreate,
    db: Session = Depends(deps.get_db)
) -> Any:
    """Create a new live playlist."""
    playlist = LivePlaylist(**playlist_in.model_dump())
    db.add(playlist)
    db.commit()
    db.refresh(playlist)
    return playlist

@router.get("/playlists/{playlist_id}", response_model=schemas.LivePlaylistDetail)
def get_playlist(
    playlist_id: int,
    db: Session = Depends(deps.get_db)
) -> Any:
    """Get detailed information for a specific playlist."""
    playlist = db.query(LivePlaylist).filter(LivePlaylist.id == playlist_id).first()
    if not playlist:
        raise HTTPException(status_code=404, detail="Playlist not found")
    return playlist

@router.put("/playlists/{playlist_id}", response_model=schemas.LivePlaylist)
def update_playlist(
    playlist_id: int,
    playlist_in: schemas.LivePlaylistUpdate,
    db: Session = Depends(deps.get_db)
) -> Any:
    """Update playlist basic info."""
    playlist = db.query(LivePlaylist).filter(LivePlaylist.id == playlist_id).first()
    if not playlist:
        raise HTTPException(status_code=404, detail="Playlist not found")
    
    update_data = playlist_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(playlist, field, value)
    
    db.commit()
    db.refresh(playlist)
    return playlist

@router.delete("/playlists/{playlist_id}")
def delete_playlist(
    playlist_id: int,
    db: Session = Depends(deps.get_db)
) -> Any:
    """Delete a playlist."""
    playlist = db.query(LivePlaylist).filter(LivePlaylist.id == playlist_id).first()
    if not playlist:
        raise HTTPException(status_code=404, detail="Playlist not found")
    db.delete(playlist)
    db.commit()
    return {"status": "success"}

@router.post("/playlists/{playlist_id}/bouquets", response_model=List[schemas.LivePlaylistBouquet])
def add_playlist_bouquets(
    playlist_id: int,
    bouquets_in: List[schemas.LivePlaylistBouquetBase],
    db: Session = Depends(deps.get_db)
) -> Any:
    """Add or update multiple bouquets in a playlist."""
    playlist = db.query(LivePlaylist).filter(LivePlaylist.id == playlist_id).first()
    if not playlist:
        raise HTTPException(status_code=404, detail="Playlist not found")
    
    results = []
    for b_in in bouquets_in:
        existing = None
        if b_in.id:
            existing = db.query(LivePlaylistBouquet).filter_by(id=b_in.id, playlist_id=playlist_id).first()
        elif b_in.category_id:
            # For smart groups, check by category_id as fallback
            existing = db.query(LivePlaylistBouquet).filter_by(
                playlist_id=playlist_id, 
                category_id=b_in.category_id
            ).first()
        
        if existing:
            existing.custom_name = b_in.custom_name
            existing.order = b_in.order
            results.append(existing)
        else:
            # Create new (virtual or smart)
            bouquet = LivePlaylistBouquet(
                playlist_id=playlist_id,
                **b_in.model_dump(exclude={'id'})
            )
            db.add(bouquet)
            results.append(bouquet)
    
    db.commit()
    for r in results: db.refresh(r)
    return results

@router.delete("/playlists/{playlist_id}/bouquets/{bouquet_id}")
def remove_playlist_bouquet(
    playlist_id: int,
    bouquet_id: int,
    db: Session = Depends(deps.get_db)
) -> Any:
    """Remove a bouquet from a playlist."""
    bouquet = db.query(LivePlaylistBouquet).filter_by(id=bouquet_id, playlist_id=playlist_id).first()
    if not bouquet:
        raise HTTPException(status_code=404, detail="Bouquet not found")
    db.delete(bouquet)
    db.commit()
    return {"status": "success"}

@router.post("/channels/{channel_id}/move", response_model=schemas.LivePlaylistChannel)
def move_playlist_channel(
    channel_id: int,
    move_in: schemas.LivePlaylistChannelMove,
    db: Session = Depends(deps.get_db)
) -> Any:
    """Move a channel to a different bouquet or update its order."""
    channel = db.query(LivePlaylistChannel).filter(LivePlaylistChannel.id == channel_id).first()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    
    channel.bouquet_id = move_in.new_bouquet_id
    channel.order = move_in.new_order
    db.commit()
    db.refresh(channel)
    return channel

@router.post("/bouquets/{bouquet_id}/channels/add", response_model=schemas.LivePlaylistChannel)
def add_channel_to_bouquet(
    bouquet_id: int,
    channel_in: schemas.LivePlaylistChannelBase,
    db: Session = Depends(deps.get_db)
) -> Any:
    """Add a specific stream to a virtual or existing bouquet."""
    bouquet = db.query(LivePlaylistBouquet).filter(LivePlaylistBouquet.id == bouquet_id).first()
    if not bouquet:
        raise HTTPException(status_code=404, detail="Bouquet not found")
    
    channel = LivePlaylistChannel(
        bouquet_id=bouquet_id,
        **channel_in.model_dump()
    )
    db.add(channel)
    db.commit()
    db.refresh(channel)
    return channel

@router.post("/playlists/{playlist_id}/bouquets/{bouquet_id}/channels", response_model=List[schemas.LivePlaylistChannel])
def update_bouquet_channels(
    playlist_id: int,
    bouquet_id: int,
    channels_in: List[schemas.LivePlaylistChannelBase],
    db: Session = Depends(deps.get_db)
) -> Any:
    """Update channel overrides (naming, ordering, exclusion) for a bouquet."""
    bouquet = db.query(LivePlaylistBouquet).filter_by(id=bouquet_id, playlist_id=playlist_id).first()
    if not bouquet:
        raise HTTPException(status_code=404, detail="Bouquet not found")
    
    results = []
    for c_in in channels_in:
        # Check if override already exists
        existing = db.query(LivePlaylistChannel).filter_by(
            bouquet_id=bouquet_id,
            stream_id=c_in.stream_id
        ).first()
        
        if existing:
            update_data = c_in.model_dump(exclude_unset=True)
            for field, value in update_data.items():
                setattr(existing, field, value)
            results.append(existing)
        else:
            channel = LivePlaylistChannel(
                bouquet_id=bouquet_id,
                **c_in.model_dump()
            )
            db.add(channel)
            results.append(channel)
            
    db.commit()
    for r in results: db.refresh(r)
    return results

@router.delete("/playlists/{playlist_id}/channels/{channel_id}")
def remove_playlist_channel(
    playlist_id: int,
    channel_id: int,
    db: Session = Depends(deps.get_db)
) -> Any:
    """Remove a channel from a playlist bouquet."""
    channel = db.query(LivePlaylistChannel).join(LivePlaylistBouquet).filter(
        LivePlaylistChannel.id == channel_id,
        LivePlaylistBouquet.playlist_id == playlist_id
    ).first()
    
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
        
    db.delete(channel)
    db.commit()
    return {"status": "success"}

@router.post("/playlists/{playlist_id}/channels/{channel_id}/rename", response_model=schemas.LivePlaylistChannel)
def rename_playlist_channel(
    playlist_id: int,
    channel_id: int,
    update_in: schemas.LivePlaylistChannelUpdate,
    db: Session = Depends(deps.get_db)
) -> Any:
    """Rename a channel in a playlist bouquet."""
    channel = db.query(LivePlaylistChannel).join(LivePlaylistBouquet).filter(
        LivePlaylistChannel.id == channel_id,
        LivePlaylistBouquet.playlist_id == playlist_id
    ).first()
    
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
        
    if update_in.custom_name is not None:
        channel.custom_name = update_in.custom_name
        
    db.commit()
    db.refresh(channel)
    return channel

@router.post("/playlists/{playlist_id}/channels/bulk")
def bulk_remove_playlist_channels(
    playlist_id: int,
    bulk_in: schemas.LivePlaylistChannelBulkDelete,
    db: Session = Depends(deps.get_db)
) -> Any:
    """Remove multiple channels from a playlist."""
    # Use subquery to avoid join in delete which is not supported by all DBs
    bouquet_ids = db.query(LivePlaylistBouquet.id).filter(LivePlaylistBouquet.playlist_id == playlist_id)
    db.query(LivePlaylistChannel).filter(
        LivePlaylistChannel.id.in_(bulk_in.channel_ids),
        LivePlaylistChannel.bouquet_id.in_(bouquet_ids)
    ).delete(synchronize_session=False)
    
    db.commit()
    return {"status": "success"}

@router.post("/playlists/{playlist_id}/bouquets/{bouquet_id}/duplicate", response_model=schemas.LivePlaylistBouquet)
def duplicate_bouquet(
    playlist_id: int,
    bouquet_id: int,
    db: Session = Depends(deps.get_db)
) -> Any:
    """Duplicate a bouquet and all its channels."""
    source = db.query(LivePlaylistBouquet).filter_by(id=bouquet_id, playlist_id=playlist_id).first()
    if not source:
        raise HTTPException(status_code=404, detail="Bouquet not found")
    
    # Create new bouquet
    new_bouquet = LivePlaylistBouquet(
        playlist_id=playlist_id,
        category_id=source.category_id,
        custom_name=f"{source.custom_name} (Copy)" if source.custom_name else "Copy",
        order=db.query(LivePlaylistBouquet).filter_by(playlist_id=playlist_id).count()
    )
    db.add(new_bouquet)
    db.flush() # Get new_bouquet.id
    
    # Duplicate channels
    for ch in source.channels:
        new_ch = LivePlaylistChannel(
            bouquet_id=new_bouquet.id,
            stream_id=ch.stream_id,
            custom_name=ch.custom_name,
            order=ch.order,
            is_excluded=ch.is_excluded,
            epg_channel_id=ch.epg_channel_id
        )
        db.add(new_ch)
    
    db.commit()
    db.refresh(new_bouquet)
    return new_bouquet

# --- EPG Source Management v3.3.0 ---

@router.get("/playlists/{playlist_id}/epg-sources", response_model=List[schemas.EPGSourceResponse])
def list_epg_sources(
    playlist_id: int,
    db: Session = Depends(deps.get_db)
) -> Any:
    """List all EPG sources for a playlist."""
    return db.query(models.EPGSource).filter_by(playlist_id=playlist_id).all()

@router.post("/playlists/{playlist_id}/epg-sources", response_model=schemas.EPGSourceResponse)
def create_epg_source(
    playlist_id: int,
    source_in: schemas.EPGSourceCreate,
    db: Session = Depends(deps.get_db)
) -> Any:
    """Add a new EPG source to a playlist."""
    playlist = db.query(LivePlaylist).filter(LivePlaylist.id == playlist_id).first()
    if not playlist:
        raise HTTPException(status_code=404, detail="Playlist not found")
    
    source = models.EPGSource(**source_in.model_dump())
    db.add(source)
    db.commit()
    db.refresh(source)
    return source

@router.put("/epg-sources/{source_id}", response_model=schemas.EPGSourceResponse)
def update_epg_source(
    source_id: int,
    source_in: schemas.EPGSourceUpdate,
    db: Session = Depends(deps.get_db)
) -> Any:
    """Update an EPG source."""
    source = db.query(models.EPGSource).filter(models.EPGSource.id == source_id).first()
    if not source:
        raise HTTPException(status_code=404, detail="EPG Source not found")
    
    update_data = source_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(source, field, value)
    
    db.commit()
    db.refresh(source)
    return source

@router.delete("/epg-sources/{source_id}")
def delete_epg_source(
    source_id: int,
    db: Session = Depends(deps.get_db)
) -> Any:
    """Delete an EPG source."""
    source = db.query(models.EPGSource).filter(models.EPGSource.id == source_id).first()
    if not source:
        raise HTTPException(status_code=404, detail="EPG Source not found")
    db.delete(source)
    db.commit()
    return {"status": "success"}

@router.post("/epg-mapping/{channel_id}", response_model=schemas.LivePlaylistChannel)
def update_channel_epg_mapping(
    channel_id: int,
    mapping_in: schemas.EPGMappingUpdate,
    db: Session = Depends(deps.get_db)
) -> Any:
    """Update EPG mapping for a specific channel."""
    channel = db.query(LivePlaylistChannel).filter(LivePlaylistChannel.id == channel_id).first()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    
    channel.epg_channel_id = mapping_in.epg_channel_id
    db.commit()
    db.refresh(channel)
    return channel

@router.get("/epg-sources/{source_id}/search", response_model=List[Any])
def search_epg_channels(
    source_id: int,
    query: str = Query(...),
    db: Session = Depends(deps.get_db)
) -> Any:
    """Search for channels within an EPG source."""
    return epg_service.search_channels(source_id, query)

@router.post("/playlists/{playlist_id}/epg-auto-match")
async def auto_match_epg(
    playlist_id: int,
    db: Session = Depends(deps.get_db)
) -> Any:
    """Trigger fuzzy matching for unmapped channels in a playlist."""
    playlist = db.query(LivePlaylist).filter(LivePlaylist.id == playlist_id).first()
    if not playlist:
        raise HTTPException(status_code=404, detail="Playlist not found")
    
    count = await epg_service.auto_match_channels(playlist, db)
    return {"status": "success", "matched_count": count}

@router.post("/epg-sources/{source_id}/refresh")
async def refresh_epg_source(
    source_id: int,
    db: Session = Depends(deps.get_db)
) -> Any:
    """Trigger a refresh for an EPG source."""
    source = db.query(models.EPGSource).filter(models.EPGSource.id == source_id).first()
    if not source:
        raise HTTPException(status_code=404, detail="EPG Source not found")
    
    # In a real app, this should be a Celery task
    # For now, we call it directly (async)
    await epg_service.fetch_and_cache_epg(source)
    
    source.last_updated = datetime.utcnow()
    db.commit()
    
    return {"status": "success", "message": "EPG refresh started"}

@router.get("/streams/search")
async def search_live_streams(
    subscription_id: int,
    q: str = Query(...),
    db: Session = Depends(deps.get_db)
) -> Any:
    """Search for live streams across all categories in a subscription."""
    sub = db.query(LiveStreamSubscription).filter(LiveStreamSubscription.subscription_id == subscription_id).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")
    
    async with XtreamClient(sub.xtream_url, sub.username, sub.password) as client:
        all_streams = await client.get_live_streams()
        categories = await client.get_live_categories()
    
    cat_map = {str(c.get("category_id")): c.get("category_name") for c in categories}
    
    query = q.lower()
    results = []
    
    for s in all_streams:
        if query in s.get("name", "").lower():
            results.append({
                "stream_id": s.get("stream_id"),
                "name": s.get("name"),
                "category_id": s.get("category_id"),
                "category_name": cat_map.get(str(s.get("category_id")), "Unknown"),
                "stream_icon": s.get("stream_icon"),
                "epg_channel_id": s.get("epg_channel_id")
            })
            
    # Grouping by category
    grouped = {}
    for r in results:
        cid = str(r["category_id"])
        cname = r["category_name"]
        if cid not in grouped:
            grouped[cid] = {"category_id": cid, "category_name": cname, "streams": []}
        grouped[cid]["streams"].append(r)
        
    return list(grouped.values())

@router.get("/playlist.xml")
async def get_playlist_epg(
    db: Session = Depends(deps.get_db),
    playlist_id: int = Query(...)
) -> Any:
    """Serve the custom XMLTV guide for a specific playlist."""
    playlist = db.query(LivePlaylist).filter(LivePlaylist.id == playlist_id).first()
    if not playlist:
        raise HTTPException(status_code=404, detail="Playlist not found")
    
    xml_content = epg_service.generate_playlist_xmltv(playlist)
    return Response(content=xml_content, media_type="application/xml")

@router.get("/playlist.m3u")
async def generate_m3u_playlist(
    db: Session = Depends(deps.get_db),
    playlist_id: int = Query(...)
):
    """Generate M3U playlist based on specific playlist configuration."""
    playlist = db.query(LivePlaylist).filter(LivePlaylist.id == playlist_id).first()
    if not playlist:
        raise HTTPException(status_code=404, detail="Playlist not found")

    sub = playlist.subscription
    client = XtreamClient(sub.xtream_url, sub.username, sub.password)
    
    # Build EPG URL for this playlist (relative to API if client supports it, or full)
    epg_url = f"/api/v1/live/playlist.xml?playlist_id={playlist_id}"
    
    m3u_content = [f'#EXTM3U x-tvg-url="{epg_url}"']
    
    # Performance: Fetch ALL streams from subscription once to handle cross-category mixing
    # In a very large account this might be slow, but for 4-pane builder it's necessary.
    try:
        all_streams_list = await client.get_live_streams()
    finally:
        await client.aclose()
    all_streams = {str(s.get("stream_id")): s for s in all_streams_list}
    
    # Iterate through bouquets in order
    bouquets = sorted(playlist.bouquets, key=lambda x: x.order)
    
    for bouquet in bouquets:
        group_title = bouquet.custom_name if bouquet.custom_name else (f"Category {bouquet.category_id}" if bouquet.category_id else "Custom Group")
        
        # Determine which streams belong to this bouquet
        bouquet_streams = [] # List of (stream_data, override_data)
        
        if bouquet.category_id:
            # Smart Group: Include all streams from category unless excluded
            cat_streams = [s for s in all_streams_list if str(s.get("category_id")) == str(bouquet.category_id)]
            channel_overrides = {str(c.stream_id): c for c in bouquet.channels}
            
            for s in cat_streams:
                sid = str(s.get("stream_id"))
                override = channel_overrides.get(sid)
                if override and override.is_excluded:
                    continue
                bouquet_streams.append((s, override))
        else:
            # Virtual Group: Only include channels explicitly added
            for channel in sorted(bouquet.channels, key=lambda x: x.order):
                sid = str(channel.stream_id)
                s = all_streams.get(sid)
                if s:
                    bouquet_streams.append((s, channel))
        
        # Sort bouquet_streams by order (override.order if exists, else -1 to stay at top or 999 to stay at bottom)
        # For simplicity, if override exists, use its order.
        bouquet_streams.sort(key=lambda x: x[1].order if x[1] else 999)
        
        for stream, override in bouquet_streams:
            stream_id = str(stream.get("stream_id"))
            name = override.custom_name if (override and override.custom_name) else stream.get("name")
            logo = stream.get("stream_icon", "")
            epg_id = override.epg_channel_id if (override and override.epg_channel_id) else stream.get("epg_channel_id", "")
            
            stream_url = f"{sub.xtream_url}/live/{sub.username}/{sub.password}/{stream_id}.ts"
            extinf = f'#EXTINF:-1 tvg-id="{epg_id}" tvg-name="{name}" tvg-logo="{logo}" group-title="{group_title}",{name}'
            m3u_content.append(extinf)
            m3u_content.append(stream_url)

    return Response(content="\n".join(m3u_content), media_type="text/plain")

@router.get("/playlists/{playlist_id}/m3u/preview")
async def preview_m3u_playlist(
    playlist_id: int,
    db: Session = Depends(deps.get_db)
) -> Any:
    """Get M3U content for preview."""
    # Re-use the logic from generate_m3u_playlist but return as JSON
    # For now, let's just call the function logic or keep it DRY
    # Actually, the logic in generate_m3u_playlist is a bit large, 
    # so I'll extract it to a helper or just duplicate a simplified version for now.
    
    playlist = db.query(LivePlaylist).filter(LivePlaylist.id == playlist_id).first()
    if not playlist:
        raise HTTPException(status_code=404, detail="Playlist not found")

    # [Logic same as generate_m3u_playlist - simplified for preview]
    # To keep it efficient, I'll just return first 100 lines or full if requested
    # But usually a preview is full.
    
    # Actually, I'll just call the internal logic if possible.
    # For now, I'll just return the full M3U as a string in a JSON field.
    resp = await generate_m3u_playlist(db, playlist_id)
    return {"content": resp.body.decode()}

@router.get("/playlists/{playlist_id}/validation")
def get_playlist_validation(
    playlist_id: int,
    db: Session = Depends(deps.get_db)
) -> Any:
    """Get EPG mapping validation statistics for a playlist."""
    playlist = db.query(LivePlaylist).filter(LivePlaylist.id == playlist_id).first()
    if not playlist:
        raise HTTPException(status_code=404, detail="Playlist not found")
    
    total_channels = 0
    mapped_channels = 0
    missing_epg = []
    
    for b in playlist.bouquets:
        for ch in b.channels:
            total_channels += 1
            if ch.epg_channel_id:
                mapped_channels += 1
            else:
                missing_epg.append({
                    "id": ch.id,
                    "stream_id": ch.stream_id,
                    "name": ch.custom_name,
                    "bouquet": b.custom_name
                })
                
    return {
        "total_channels": total_channels,
        "mapped_channels": mapped_channels,
        "missing_count": len(missing_epg),
        "missing_channels": missing_epg[:50] # Limit list
    }

# Legacy compatibility (optional)
@router.get("/config", response_model=schemas.LiveConfig)
def get_live_config_legacy(
    db: Session = Depends(deps.get_db),
    subscription_id: int = Query(...)
) -> Any:
    config = db.query(LiveStreamSubscription).filter(LiveStreamSubscription.subscription_id == subscription_id).first()
    if not config:
        return schemas.LiveConfig(id=0, subscription_id=subscription_id, included_categories=[], excluded_streams=[])
    return config
