from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models.settings import SettingsModel
from app.models.downloads import DownloadSettingsGlobal
from app.schemas import ConfigUpdate, ConfigResponse, DownloadSettingsGlobalResponse, DownloadSettingsGlobalUpdate
from app.api import deps

router = APIRouter()

@router.get("/downloads", response_model=DownloadSettingsGlobalResponse)
def get_download_settings(db: Session = Depends(get_db)):
    settings = db.query(DownloadSettingsGlobal).first()
    if not settings:
        settings = DownloadSettingsGlobal()
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings

@router.post("/downloads", response_model=DownloadSettingsGlobalResponse)
def update_download_settings(settings_in: DownloadSettingsGlobalUpdate, db: Session = Depends(get_db)):
    settings = db.query(DownloadSettingsGlobal).first()
    if not settings:
        settings = DownloadSettingsGlobal()
        db.add(settings)
    
    update_data = settings_in.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(settings, field, value)
        
    db.commit()
    db.refresh(settings)
    return settings

@router.get("/", response_model=ConfigResponse)
def get_config(db: Session = Depends(get_db)):
    settings = {s.key: s.value for s in db.query(SettingsModel).all()}

    # Convert string booleans to actual booleans for Pydantic
    bool_fields = [
        "FORMAT_DATE_IN_TITLE", "CLEAN_NAME", "SERIES_USE_SEASON_FOLDERS",
        "SERIES_USE_CATEGORY_FOLDERS", "SERIES_INCLUDE_NAME_IN_FILENAME",
        "PLEX_HLS_PROXY_MODE"
    ]
    for field in bool_fields:
        if field in settings:
            settings[field] = settings[field].lower() == "true"

    # Convert string integers to actual integers
    int_fields = ["SYNC_PARALLELISM_MOVIES", "SYNC_PARALLELISM_SERIES"]
    for field in int_fields:
        if field in settings:
            try:
                settings[field] = int(settings[field])
            except (ValueError, TypeError):
                pass

    # Convert string floats to actual floats
    float_fields = ["SYNC_RATE_LIMIT_RPS"]
    for field in float_fields:
        if field in settings:
            try:
                settings[field] = float(settings[field])
            except (ValueError, TypeError):
                pass

    return ConfigResponse(**settings)

@router.post("/", response_model=ConfigResponse)
def update_config(config: ConfigUpdate, db: Session = Depends(get_db)):
    updates = {}
    if config.XC_URL is not None:
        updates["XC_URL"] = config.XC_URL
    if config.XC_USER is not None:
        updates["XC_USER"] = config.XC_USER
    if config.XC_PASS is not None:
        updates["XC_PASS"] = config.XC_PASS
    if config.OUTPUT_DIR is not None:
        updates["OUTPUT_DIR"] = config.OUTPUT_DIR
    if config.MOVIES_DIR is not None:
        updates["MOVIES_DIR"] = config.MOVIES_DIR
    if config.SERIES_DIR is not None:
        updates["SERIES_DIR"] = config.SERIES_DIR
    if config.PREFIX_REGEX is not None:
        updates["PREFIX_REGEX"] = config.PREFIX_REGEX
    if config.FORMAT_DATE_IN_TITLE is not None:
        updates["FORMAT_DATE_IN_TITLE"] = str(config.FORMAT_DATE_IN_TITLE).lower()
    if config.CLEAN_NAME is not None:
        updates["CLEAN_NAME"] = str(config.CLEAN_NAME).lower()
    if config.SERIES_USE_SEASON_FOLDERS is not None:
        updates["SERIES_USE_SEASON_FOLDERS"] = str(config.SERIES_USE_SEASON_FOLDERS).lower()
    if config.SERIES_USE_CATEGORY_FOLDERS is not None:
        updates["SERIES_USE_CATEGORY_FOLDERS"] = str(config.SERIES_USE_CATEGORY_FOLDERS).lower()
    if config.SERIES_INCLUDE_NAME_IN_FILENAME is not None:
        updates["SERIES_INCLUDE_NAME_IN_FILENAME"] = str(config.SERIES_INCLUDE_NAME_IN_FILENAME).lower()
    if config.SYNC_PARALLELISM_MOVIES is not None:
        updates["SYNC_PARALLELISM_MOVIES"] = str(config.SYNC_PARALLELISM_MOVIES)
    if config.SYNC_PARALLELISM_SERIES is not None:
        updates["SYNC_PARALLELISM_SERIES"] = str(config.SYNC_PARALLELISM_SERIES)
    if config.SYNC_RATE_LIMIT_RPS is not None:
        updates["SYNC_RATE_LIMIT_RPS"] = str(config.SYNC_RATE_LIMIT_RPS)
    if config.SERIES_USE_CATEGORY_FOLDERS is not None:
        updates["SERIES_USE_CATEGORY_FOLDERS"] = str(config.SERIES_USE_CATEGORY_FOLDERS).lower()
    if config.MOVIE_USE_CATEGORY_FOLDERS is not None:
        updates["MOVIE_USE_CATEGORY_FOLDERS"] = str(config.MOVIE_USE_CATEGORY_FOLDERS).lower()
    if config.PLEX_PROXY_BASE_URL is not None:
        updates["PLEX_PROXY_BASE_URL"] = config.PLEX_PROXY_BASE_URL
    if config.PLEX_SHARED_KEY is not None:
        updates["PLEX_SHARED_KEY"] = config.PLEX_SHARED_KEY
    if config.PLEX_HLS_PROXY_MODE is not None:
        updates["PLEX_HLS_PROXY_MODE"] = str(config.PLEX_HLS_PROXY_MODE).lower()

    for key, value in updates.items():
        setting = db.query(SettingsModel).filter(SettingsModel.key == key).first()
        if not setting:
            setting = SettingsModel(key=key, value=value)
            db.add(setting)
        else:
            setting.value = value
    db.commit()
    
    settings = {s.key: s.value for s in db.query(SettingsModel).all()}
    return ConfigResponse(**settings)
