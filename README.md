# Xtream to STRM

> **Fork Notice**: This is a fork of [mourabena2-ui/xtream-to-strm-web](https://github.com/mourabena2-ui/xtream-to-strm-web)

<div align="center">

![Xtream to STRM Logo](frontend/public/Xtreamm-app_Full_Logo.jpg)

**A complete media management platform for Xtream Codes and M3U playlists**
Generate `.strm` files, download content, and create dynamic M3U playlists for your media server

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Upstream](https://img.shields.io/badge/upstream-mourabena2--ui-blue.svg)](https://github.com/mourabena2-ui/xtream-to-strm-web)

</div>

---

## 🌟 Overview

Xtream to STRM is a complete, production-ready media management platform that offers **five powerful modules**:

1. **STRM Generator** - Transform Xtream Codes and M3U playlists into Jellyfin/Kodi-compatible `.strm` and `.nfo` files
2. **Download Manager** - Browse and download media directly to your server with intelligent queue management
3. **Live TV Server** - Generate dynamic M3U playlists from your Xtream subscriptions for IPTV players
4. **Auto-Monitoring** - Automatically detect and download new episodes from monitored series
5. **Plex Integration** - Sync Plex.tv libraries to STRM files, including shared server support

Built with modern technologies, it provides an intuitive interface for managing your entire media workflow with advanced features like selective synchronization, parallel processing, intelligent metadata generation, and comprehensive administration tools.

## ✨ Key Features

### 🎬 Multi-Source Support
- **Xtream Codes**: Full support for Xtream API with multi-subscription management
- **M3U Playlists**: Import from URLs or file uploads with group-based selection
- **Live TV**: Dynamic M3U playlist generation for IPTV players (VLC, TiviMate, etc.)

### 🎯 Smart Synchronization
- **Parallel Fetching**: High-performance sync with concurrent metadata fetching (async/await)
- **Selective Sync**: Choose specific categories or groups to synchronize
- **Incremental Updates**: Only sync what's changed since last update
- **Dual Control**: Separate sync for Movies and Series
- **Robustness**: Redirect support and improved error handling for Xtream providers

### 📋 Rich Metadata
- **NFO Generation**: Detailed metadata files in Jellyfin format
- **TMDB Integration**: Automatic movie/series information enrichment
- **Smart Folder Structure**: 
  - Movies: `Movie Name {tmdb-ID}` folder support
  - Series: Optional `Season XX` subfolders
- **Configurable Formatting**: Title prefix cleaning, date formatting, and name normalization

### 🎨 Modern Interface
- **Responsive Design**: Works seamlessly on desktop and mobile
- **Real-Time Updates**: Live sync progress and status monitoring
- **Dark Mode**: Beautiful, comfortable viewing experience
- **Intuitive Navigation**: Clean organization with logical menu structure

### 📥 Download Manager
- **Direct Downloads**: Browse and download movies/series directly to your server
- **Smart Queue**: Intelligent download queue with configurable parallel limits
- **Auto-Monitoring**: Watch for new episodes and download automatically
- **Category Monitoring**: Monitor entire series categories for bulk downloads
- **Progress Tracking**: Real-time download progress with speed and ETA

### 📺 Live TV Architecture v2 (New in v3.7.0)
- **Virtual Bouquets**: Create, rename, and reorder custom bouquets from multiple subscriptions
- **Live Composer**: Powerful drag-and-drop interface for channel organization
- **One-Click Discovery**: Fast category browser for quick channel selection
- **Undo/Redo**: Full history system for all layout and configuration changes
- **Advanced EPG Management**: Manage multiple XMLTV sources with dedicated UI
- **Bulk Operations**: Rapidly add, move, or delete hundreds of channels
- **Smart Filtering**: Real-time filtering by channel name, group, or subscription
- **Dynamic M3U Server**: Single, high-performance URL that updates instantly

### 🟠 Plex.tv Integration (New)
- **Multi-Account Support**: Connect multiple Plex.tv accounts
- **Shared Server Support**: Works with servers you don't own (transcoding URLs)
- **Library Selection**: Choose specific Movie and Show libraries to sync
- **Secure Proxy**: Built-in proxy endpoint that hides Plex tokens from STRM files
- **HLS Proxy Mode**: Transparent proxy for clients that don't follow redirects (e.g., Findroid/ExoPlayer)
- **Metadata Extraction**: TMDB/IMDB IDs, genres, actors, ratings from Plex
- **NFO Generation**: Full metadata files compatible with Jellyfin/Kodi
- **Configurable Output**: Customize output directories per server

### 🛠️ Advanced Administration
- **Database Management**: Easy reset and cleanup operations
- **File Management**: Bulk delete and reorganization tools
- **NFO Settings**: Customize title formatting with regex patterns
- **Statistics Dashboard**: Comprehensive overview of your content
- **Real-Time Logs**: Stream application logs directly in the browser

## 🚀 Quick Start

### Installation from Docker Hub (Recommended)

```bash
docker run -d \
  -p 8000:8000 \
  -v $(pwd)/output:/output \
  -v $(pwd)/db:/db \
  --name xtream-to-strm \
  mourabena2ui/xtream-to-strm-web:latest
```

Access the web interface at **http://localhost:8000**

### Using Docker Compose

```yaml
version: '3.8'

services:
  app:
    image: mourabena2ui/xtream-to-strm-web:latest
    container_name: xtream_app
    environment:
      - TZ=Europe/Paris
    ports:
      - "8000:8000"
    volumes:
      - ./output:/output
      - ./db:/db
    restart: unless-stopped
```

Then start with:
```bash
docker-compose up -d
```

## 📖 Usage

### 1. Add Your Content Source

**For Xtream Codes:**
- Navigate to **XtreamTV** → **Subscriptions**
- Add your subscription details (URL, username, password)
- Configure movie and series output directories

**For M3U Playlists:**
- Navigate to **M3U Import** → **Sources**
- Add source via URL or file upload
- Configure output directory

### 2. Select Content to Sync

**For Xtream:**
- Go to **XtreamTV** → **Bouquet Selection**
- List available categories
- Select categories for movies and/or series

**For M3U:**
- Go to **M3U Import** → **Group Selection**
- Select your source
- Choose groups for movies and/or series

### 3. Synchronize

Click **Sync Movies** or **Sync Series** to generate your files!

### 4. Download Content (Optional)

**Browse and Download:**
- Navigate to **Downloads** → **Media Selection**
- Browse available movies and series
- Add items to download queue
- Monitor downloads in **Download Manager**

**Auto-Monitoring:**
- Go to **Downloads** → **Monitoring**
- Add series or categories to watch
- New episodes download automatically

### 5. Live TV M3U (Optional)

**Generate Your Playlist:**
- Navigate to **Live TV** → **Live Selection**
- Select your subscription
- Click refresh to load bouquets
- Choose categories to include
- Copy or download your M3U URL
- Add URL to your IPTV player

### 6. Plex.tv Integration (Optional)

**Connect Your Plex Account:**
- Navigate to **Plex** → **Accounts**
- Enter your Plex.tv username and password
- Click **Add Account** to authenticate

**Configure Server:**
- Go to **Plex** → **Servers**
- Select your account to view available servers (including shared servers)
- Configure output directories for movies and series

**Sync Libraries:**
- Go to **Plex** → **Selection**
- Click **Sync Libraries** to fetch available libraries from your server
- Select the Movie and Show libraries you want to sync
- Click **Sync Movies** or **Sync Series** to generate STRM/NFO files

**Configure Proxy (Recommended):**
- Go to **Administration** → **Plex Settings**
- Set **Proxy Base URL** to an IP/hostname accessible by Jellyfin (not localhost)
- Optionally set a **Shared Key** to protect the proxy endpoint
- Enable **HLS Proxy Mode** if using clients like Findroid that don't follow HTTP redirects

> **Note:** Plex integration uses a proxy endpoint to hide authentication tokens from STRM files. This is essential for shared servers where direct file access is blocked.

> **HLS Proxy Mode:** Some clients (like Findroid, based on ExoPlayer) don't properly follow HTTP 302 redirects for HLS streams. When enabled, this mode proxies the HLS playlists (.m3u8) through your server while video segments (.ts) still stream directly from Plex, minimizing bandwidth impact on your server.

### 7. Configure Your Media Server

Point Jellyfin to the `/output` directory to scan your new content. The generated files follow Jellyfin's naming conventions for optimal recognition.

## 🎛️ NFO Configuration

Customize how titles are formatted in NFO files:

| Setting | Description | Example |
|---------|-------------|---------|
| **Prefix Regex** | Strip language/country prefixes | `FR - Movie` → `Movie` |
| **Format Date** | Move year to parentheses | `Name_2024` → `Name (2024)` |
| **Clean Name** | Replace underscores with spaces | `My_Movie` → `My Movie` |

Access these settings in **Administration** → **NFO Settings**

## 📁 Generated File Structure

### Xtream Codes / M3U

```
output/
├── movies/
│   └── Movie Name (2024)/
│       ├── Movie Name (2024).strm
│       └── Movie Name (2024).nfo
└── series/
    └── Series Name/
        ├── Season 01/
        │   ├── Series Name S01E01.strm
        │   └── Series Name S01E01.nfo
        └── tvshow.nfo
```

### Plex Integration

```
output/plex/
└── ServerName/
    ├── movies/
    │   └── LibraryName/                    # If library folders enabled
    │       └── Movie Name (2024) {tmdb-123}/
    │           ├── Movie Name (2024) {tmdb-123}.strm
    │           └── Movie Name (2024) {tmdb-123}.nfo
    └── series/
        └── LibraryName/
            └── Series Name (2020) {tmdb-456}/
                ├── tvshow.nfo
                └── Season 01/
                    ├── S01E01 - Episode Title.strm
                    └── S01E01 - Episode Title.nfo
```

## 🔧 Technology Stack

- **Backend**: Python 3.11, FastAPI, SQLAlchemy, Celery
- **Frontend**: React 18, TypeScript, Vite, TailwindCSS
- **Infrastructure**: Redis, SQLite
- **Integrations**: Plex API (python-plexapi), Jellyfin API
- **Containerization**: Docker (multi-stage build)

## 📝 Version History

### v3.8.0 (Current)
- 🟠 **Plex.tv Integration**: Full support for Plex libraries including shared servers
- 🔐 **Secure Proxy**: Built-in proxy endpoint to hide Plex tokens from STRM files
- 📚 **Multi-Account**: Connect multiple Plex.tv accounts with independent server management
- 🎬 **Library Selection**: Choose specific Movie/Show libraries to sync
- 📝 **Plex Metadata**: Extract TMDB/IMDB IDs, genres, actors from Plex server
- ⚙️ **Plex Settings**: Configurable proxy URL and shared key authentication

### v3.7.0
- 🚀 **Live TV v2**: Complete architectural overhaul with high-performance virtual bouquets
- ✍️ **Customization**: Rename and reorder channels with a persistent custom order
- 🔄 **Undo/Redo System**: Integrated history management for all Live TV operations
- 📁 **Bouquet Composer**: Modern split-pane UI for rapid channel organization
- 📡 **Multi-Source EPG**: Support for multiple XMLTV sources with full management UI
- ⚡ **Performance Ops**: 3x faster API synchronization and elimination of redundant redirects
- 🐞 **Stabilization**: Fixed critical 422/500 bulk delete and 404 rename errors

### v3.1.0
- 📺 **Live TV Module**: New dedicated module for managing Live TV channels from Xtream subscriptions
- 🎯 **Bouquet Management**: Select specific bouquets and exclude individual channels
- 📡 **Dynamic M3U Server**: Generate personalized M3U playlists with a single URL
- 🔧 **Pydantic Schemas**: Improved API serialization for better performance and reliability
- 🛠️ **XtreamClient Enhancement**: Added async methods for Live TV categories and streams
- 📱 **Live Selection UI**: New split-pane interface for managing bouquets and channels

### v3.0.4 (Hotfix)
- 💉 **Engine-Level Schema Healing**: Replaced external SQL scripts with native SQLAlchemy inspection. The application now automatically detects and adds missing columns on startup using its internal engine.
- 🩺 **Ultimate Reliability**: Final resolution for the `no such column` errors reported by users upgrading from v2.6.x.

### v3.0.3 (Hotfix)
- 🛡️ **Definitive Migration Fix**: Combined import-based and subprocess-based migration triggers for absolute reliability.
- 🩺 **Schema Verification**: Added a startup check that verifies the existence of critical columns and logs clear error messages if issues persist.
- 📦 **Package Support**: Added `__init__.py` to migrations to fix Python package resolution issues.

### v3.0.2 (Hotfix)
- 🧪 **Migration Stability**: Integrated database migration triggers directly into `main.py` for guaranteed execution across all environments.
- 🔧 **Path Resolution**: Robust database path discovery in migration scripts (supports relative and absolute paths).

### v3.0.1 (Hotfix)
- 🔧 **Database Migration**: Added automated SQL migration system to handle schema updates for existing users (fixing `no such column` errors).
- 🐳 **Docker Startup**: Improved `docker_start.sh` to apply migrations before starting the application.

### v3.0.0
- ✨ **Introduced Download Module**: New system to browse and download media directly to your server.
- ✨ **Auto-Download Monitoring**: Monitor movies, series, and **series categories** for new automatic downloads.
- ✨ **Intelligent Queue**: Optimized download queue with strict `max_parallel_downloads` enforcement and bulk-add performance.
- 🔧 **Enhanced Path Resolution**: Better folder structure (Category/Series/Season) and direct Xtream API fallback for metadata.
- 🔧 **Sanitization**: Improved title cleaning to handle separators and country prefixes.
- 🛠️ **Deep Analysis**: Refined various backend components for better concurrency and data type consistency.

### v2.6.1 (Latest)
- 🌍 **Timezone Support**: Added full support for local server time via `TZ` environment variable (default: `Europe/Paris`).
- 🕒 **Core Engine**: Migrated all backend logic from UTC to local time for accurate task scheduling and logging.
- 🎨 **UI Fix**: Implemented `formatDateTime` to prevent browser timezone shifts, ensuring consistency between server logs and dashboard.
- 🐳 **Docker**: Optimized container startup and environment configuration for timezone persistence.

### v2.6.0
- ✨ **Performance**: Parallel fetching engine with **configurable concurrency settings** via UI.
- ✨ **Logs**: New real-time log streaming interface for live monitoring.
- ✨ **Metadata**: TMDB ID folder support `Movie {tmdb-ID}` for perfect matching.
- ✨ **Series**: Configurable Season folders & Episode filename formatting.
- 🔒 **Security**: Switched to non-root container user (`appuser`) and added protected routes.
- 🛠️ **Admin**: Granular Cache Clearing tools & Smart Database Reset (preserves settings).
- 🐞 Fixed redirect handling for IPTV providers and corrected hardcoded versioning.

### v2.5.0
- ✨ Enhanced NFO title formatting options
- ✨ Configurable regex for prefix stripping
- ✨ Date formatting at end of titles
- ✨ Name cleaning (underscore replacement)
- 🎨 New application logo
- 🐛 Fixed config endpoint routing
- 🐛 Improved M3U sync with NFO generation

### v2.0.0
- ✨ Added M3U playlist support
- ✨ Refactored UI structure
- ✨ Split sync controls for Movies/Series
- 🎨 Enhanced dashboard and navigation

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 💬 Support

- **Issues**: [GitHub Issues](https://github.com/mourabena2-ui/xtream-to-strm-web/issues)
- **Docker Hub**: [mourabena2ui/xtream-to-strm-web](https://hub.docker.com/r/mourabena2ui/xtream-to-strm-web)

## ☕ Support This Project

If you find this project helpful, consider supporting its development!

<a href="https://www.buymeacoffee.com/mourabena" target="_blank"><img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me A Coffee" style="height: 60px !important;width: 217px !important;" ></a>

Your support helps maintain and improve this project. Thank you! 🙏

---

<div align="center">

**Made with ❤️ for the Jellyfin and Kodi community**

[Docker Hub](https://hub.docker.com/r/mourabena2ui/xtream-to-strm-web) • [GitHub](https://github.com/mourabena2-ui/xtream-to-strm-web)

</div>
