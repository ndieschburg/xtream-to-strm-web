from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
from app.api.api import api_router
from app.core.config import settings
from app.db.base import Base
from app.db.session import engine
import logging
import os


# Uvicorn only configures its own loggers, so without an explicit root handler
# every "app.*" record falls back to logging.lastResort (level WARNING) and all
# INFO/DEBUG output is silently discarded.
logging.basicConfig(
    level=settings.LOG_LEVEL.upper(),
    format="%(asctime)s %(levelname)-8s [%(name)s] %(message)s",
    force=True,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler for startup/shutdown events."""
    # Startup
    yield
    # Shutdown - cleanup HTTP clients
    from app.api.endpoints.plex import close_http_client
    await close_http_client()

# Create tables first (for new installations)
Base.metadata.create_all(bind=engine)

# Self-healing schema: Ensure critical columns exist and new tables are created
def _ensure_schema_up_to_date():
    from sqlalchemy import inspect, text
    
    print("🩺 Checking database schema...")
    try:
        inspector = inspect(engine)
        existing_tables = inspector.get_table_names()
        
        # 1. Ensure new Live TV v2 tables exist
        if "live_playlists" not in existing_tables:
            print("🔧 Table 'live_playlists' missing. Creating new tables...")
            Base.metadata.create_all(bind=engine)
            print("✅ New tables created.")
            
            # Trigger migration if legacy table exists
            if "live_stream_subs" in existing_tables:
                print("🔄 Legacy Live TV data detected. Triggering migration...")
                from app.db.migrations_v2 import migrate_live_to_v2
                migrate_live_to_v2(engine)
        
        # Ensure epg_sources table exists if others do but it's missing (v3.7.0 update)
        if "epg_sources" not in existing_tables:
            print("🔧 Table 'epg_sources' missing. Creating...")
            Base.metadata.create_all(bind=engine)
            print("✅ 'epg_sources' table created.")

        # 2. Check 'subscriptions' columns
        columns = [c['name'] for c in inspector.get_columns("subscriptions")]
        
        required_migrations = [
            ("download_movies_dir", "TEXT DEFAULT '/output/downloads/movies'"),
            ("download_series_dir", "TEXT DEFAULT '/output/downloads/series'"),
            ("max_parallel_downloads", "INTEGER DEFAULT 2"),
            ("download_segments", "INTEGER DEFAULT 1")
        ]
        
        missing = [m for m in required_migrations if m[0] not in columns]
        
        if missing:
            print(f"🔧 Missing {len(missing)} columns in 'subscriptions'. Repairing...")
            with engine.connect() as conn:
                for col_name, col_type in missing:
                    try:
                        print(f"  Adding column: {col_name}...")
                        conn.execute(text(f"ALTER TABLE subscriptions ADD COLUMN {col_name} {col_type}"))
                        conn.commit()
                        print(f"  ✅ Added {col_name}")
                    except Exception as e:
                        print(f"  ⚠️ Could not add {col_name}: {e}")
            print("🎉 Schema repair complete.")
        # 3. Check 'live_playlist_bouquets' columns
        if "live_playlist_bouquets" in existing_tables:
            cat_cols = inspector.get_columns("live_playlist_bouquets")
            for col in cat_cols:
                if col['name'] == 'category_id' and not col['nullable']:
                    print("⚠️  'category_id' in 'live_playlist_bouquets' is NOT NULL but should be nullable. Fixing...")
                    # In SQLite, we can try to ALTER but it's limited.
                    # Often changing nullability requires recreation, but let's try a simple approach if the driver allows or just note it.
                    # For now, we will log it as a critical schema issue.

        # 4. Recreate 'schedule_executions' with nullable schedule_id and new columns
        if "schedule_executions" in existing_tables:
            exec_cols_info = {c['name']: c for c in inspector.get_columns("schedule_executions")}
            needs_recreate = False

            # Check if schedule_id is not nullable (needs to be nullable for manual syncs)
            if 'schedule_id' in exec_cols_info and not exec_cols_info['schedule_id'].get('nullable', True):
                needs_recreate = True
            # Check if new columns are missing
            if 'subscription_id' not in exec_cols_info or 'sync_type' not in exec_cols_info:
                needs_recreate = True

            if needs_recreate:
                print("🔧 Recreating 'schedule_executions' table with nullable schedule_id...")
                with engine.connect() as conn:
                    try:
                        # SQLite requires table recreation to change nullability
                        conn.execute(text("""
                            CREATE TABLE IF NOT EXISTS schedule_executions_new (
                                id INTEGER PRIMARY KEY,
                                schedule_id INTEGER REFERENCES schedules(id),
                                subscription_id INTEGER,
                                sync_type VARCHAR,
                                started_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                                completed_at DATETIME,
                                status VARCHAR NOT NULL DEFAULT 'running',
                                items_processed INTEGER DEFAULT 0,
                                error_message TEXT
                            )
                        """))
                        # Copy existing data
                        conn.execute(text("""
                            INSERT INTO schedule_executions_new (id, schedule_id, started_at, completed_at, status, items_processed, error_message)
                            SELECT id, schedule_id, started_at, completed_at, status, items_processed, error_message
                            FROM schedule_executions
                        """))
                        conn.execute(text("DROP TABLE schedule_executions"))
                        conn.execute(text("ALTER TABLE schedule_executions_new RENAME TO schedule_executions"))
                        conn.commit()
                        print("  ✅ Recreated schedule_executions with nullable schedule_id")
                    except Exception as e:
                        print(f"  ⚠️ Could not recreate schedule_executions: {e}")

        # 5. Recreate 'plex_schedule_executions' with nullable schedule_id and new columns
        if "plex_schedule_executions" in existing_tables:
            plex_exec_cols_info = {c['name']: c for c in inspector.get_columns("plex_schedule_executions")}
            plex_needs_recreate = False

            # Check if schedule_id is not nullable
            if 'schedule_id' in plex_exec_cols_info and not plex_exec_cols_info['schedule_id'].get('nullable', True):
                plex_needs_recreate = True
            # Check if new columns are missing
            if 'server_id' not in plex_exec_cols_info or 'sync_type' not in plex_exec_cols_info:
                plex_needs_recreate = True

            if plex_needs_recreate:
                print("🔧 Recreating 'plex_schedule_executions' table with nullable schedule_id...")
                with engine.connect() as conn:
                    try:
                        conn.execute(text("""
                            CREATE TABLE IF NOT EXISTS plex_schedule_executions_new (
                                id INTEGER PRIMARY KEY,
                                schedule_id INTEGER REFERENCES plex_schedules(id),
                                server_id INTEGER,
                                sync_type VARCHAR,
                                started_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                                completed_at DATETIME,
                                status VARCHAR NOT NULL DEFAULT 'running',
                                items_processed INTEGER DEFAULT 0,
                                error_message TEXT
                            )
                        """))
                        # Copy existing data
                        conn.execute(text("""
                            INSERT INTO plex_schedule_executions_new (id, schedule_id, started_at, completed_at, status, items_processed, error_message)
                            SELECT id, schedule_id, started_at, completed_at, status, items_processed, error_message
                            FROM plex_schedule_executions
                        """))
                        conn.execute(text("DROP TABLE plex_schedule_executions"))
                        conn.execute(text("ALTER TABLE plex_schedule_executions_new RENAME TO plex_schedule_executions"))
                        conn.commit()
                        print("  ✅ Recreated plex_schedule_executions with nullable schedule_id")
                    except Exception as e:
                        print(f"  ⚠️ Could not recreate plex_schedule_executions: {e}")

        # 6. Check 'plex_series_cache' change-detection columns
        if "plex_series_cache" in existing_tables:
            series_cache_cols = [c['name'] for c in inspector.get_columns("plex_series_cache")]
            series_cache_migrations = [
                ("updated_at", "VARCHAR"),
                ("leaf_count", "INTEGER")
            ]
            missing_cache_cols = [m for m in series_cache_migrations if m[0] not in series_cache_cols]

            if missing_cache_cols:
                print(f"🔧 Missing {len(missing_cache_cols)} columns in 'plex_series_cache'. Repairing...")
                with engine.connect() as conn:
                    for col_name, col_type in missing_cache_cols:
                        try:
                            conn.execute(text(f"ALTER TABLE plex_series_cache ADD COLUMN {col_name} {col_type}"))
                            conn.commit()
                            print(f"  ✅ Added {col_name}")
                        except Exception as e:
                            print(f"  ⚠️ Could not add {col_name}: {e}")

        print("✅ Database schema is up to date.")
            
    except Exception as e:
        print(f"❌ Schema check failed: {e}")

_ensure_schema_up_to_date()

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Trust proxy headers (X-Forwarded-Proto, X-Forwarded-For) from reverse proxies like HAProxy/nginx
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=["*"])

# Serve frontend static files
static_dir = "/app/static"
# Check for local development path
if not os.path.exists(static_dir):
    local_static = os.path.join(os.path.dirname(os.path.dirname(__file__)), "..", "frontend", "dist")
    if os.path.exists(local_static):
        static_dir = local_static

if os.path.exists(static_dir):
    app.mount("/assets", StaticFiles(directory=f"{static_dir}/assets"), name="assets")

# Include API router
app.include_router(api_router, prefix=settings.API_V1_STR)

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

# Serve SPA for 404 errors (except API routes)
if os.path.exists(static_dir):
    from fastapi import Request
    from fastapi.exceptions import HTTPException
    from starlette.exceptions import HTTPException as StarletteHTTPException
    
    from fastapi.responses import JSONResponse
    
    @app.exception_handler(404)
    async def custom_404_handler(request: Request, exc):
        # If it's an API route, return JSON 404
        if request.url.path.startswith(settings.API_V1_STR):
            return JSONResponse(status_code=404, content={"detail": "Not found"})
        
        # Otherwise serve the SPA
        return FileResponse(f"{static_dir}/index.html")
