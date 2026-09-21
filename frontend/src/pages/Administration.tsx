import { useState, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog } from "@/components/ui/dialog";
import { Trash2, AlertTriangle, Database, Settings, Clock, Zap, Server } from 'lucide-react';
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { useToast } from "@/components/ui/toast";
import api from '@/lib/api';

export default function Administration() {
    const { toast } = useToast();
    const [loading, setLoading] = useState(false);
    const [prefixRegex, setPrefixRegex] = useState('');
    const [formatDate, setFormatDate] = useState(false);
    const [cleanName, setCleanName] = useState(false);
    const [useSeasonFolders, setUseSeasonFolders] = useState(true);
    const [includeSeriesName, setIncludeSeriesName] = useState(false);
    const [parallelismMovies, setParallelismMovies] = useState(5);
    const [parallelismSeries, setParallelismSeries] = useState(5);
    const [rateLimitRps, setRateLimitRps] = useState(5);
    const [useCategoryFolders, setUseCategoryFolders] = useState(true);
    const [useMovieCategoryFolders, setUseMovieCategoryFolders] = useState(true);
    const [regexLoading, setRegexLoading] = useState(false);

    // Download Orchestration State
    const [downloadMode, setDownloadMode] = useState('parallel');
    const [globalSpeedLimit, setGlobalSpeedLimit] = useState(0);
    const [quietHoursEnabled, setQuietHoursEnabled] = useState(true);
    const [quietHoursStart, setQuietHoursStart] = useState('00:00');
    const [quietHoursEnd, setQuietHoursEnd] = useState('08:00');
    const [maxRedirects, setMaxRedirects] = useState(10);
    const [connectionTimeout, setConnectionTimeout] = useState(30);
    const [downloadSettingsLoading, setDownloadSettingsLoading] = useState(false);

    // Plex Settings State
    const [plexProxyBaseUrl, setPlexProxyBaseUrl] = useState('http://localhost:8000');
    const [plexSharedKey, setPlexSharedKey] = useState('');
    const [plexHlsProxyMode, setPlexHlsProxyMode] = useState(false);
    const [plexSettingsLoading, setPlexSettingsLoading] = useState(false);

    // Jellyfin Settings State
    const [jellyfinUrl, setJellyfinUrl] = useState('');
    const [jellyfinToken, setJellyfinToken] = useState('');
    const [jellyfinLoading, setJellyfinLoading] = useState(false);
    const [jellyfinTestResult, setJellyfinTestResult] = useState<{ success: boolean; message: string; server_name?: string; version?: string } | null>(null);
    const [jellyfinConfigured, setJellyfinConfigured] = useState(false);

    // Dialog state
    const [dialogState, setDialogState] = useState<{
        type: 'deleteFiles' | 'resetDb' | 'resetAll' | 'clearMovieCache' | 'clearSeriesCache' | 'clearPlexCache' | null;
        step: number;
    }>({ type: null, step: 0 });
    const [confirmationInput, setConfirmationInput] = useState('');

    // Load current settings on mount
    useEffect(() => {
        const loadSettings = async () => {
            try {
                const response = await api.get('/config');
                setPrefixRegex(response.data.PREFIX_REGEX || '^(?:[A-Za-z0-9.-]+_|[A-Za-z]{2,}\\s*-\\s*)');
                setFormatDate(response.data.FORMAT_DATE_IN_TITLE === true);
                setCleanName(response.data.CLEAN_NAME === true);
                setUseSeasonFolders(response.data.SERIES_USE_SEASON_FOLDERS !== false);
                setIncludeSeriesName(response.data.SERIES_INCLUDE_NAME_IN_FILENAME === true);
                setParallelismMovies(parseInt(response.data.SYNC_PARALLELISM_MOVIES) || 5);
                setParallelismSeries(parseInt(response.data.SYNC_PARALLELISM_SERIES) || 5);
                setRateLimitRps(parseFloat(response.data.SYNC_RATE_LIMIT_RPS) || 5);
                setUseCategoryFolders(response.data.SERIES_USE_CATEGORY_FOLDERS !== false);
                setUseMovieCategoryFolders(response.data.MOVIE_USE_CATEGORY_FOLDERS !== false);
                setPlexProxyBaseUrl(response.data.PLEX_PROXY_BASE_URL || 'http://localhost:8000');
                setPlexSharedKey(response.data.PLEX_SHARED_KEY || '');
                setPlexHlsProxyMode(response.data.PLEX_HLS_PROXY_MODE === true);

                // Load Jellyfin Settings
                try {
                    const jellyfinRes = await api.get('/jellyfin/config');
                    if (jellyfinRes.data.url) setJellyfinUrl(jellyfinRes.data.url);
                    setJellyfinConfigured(jellyfinRes.data.is_configured || false);
                } catch (err) {
                    console.error('Failed to load Jellyfin config', err);
                }

                // Load Download Settings
                const dlRes = await api.get('/config/downloads');
                setDownloadMode(dlRes.data.download_mode || 'parallel');
                setGlobalSpeedLimit(dlRes.data.global_speed_limit_kbps || 0);
                setQuietHoursEnabled(dlRes.data.quiet_hours_enabled);
                setQuietHoursStart(dlRes.data.quiet_hours_start || '00:00');
                setQuietHoursEnd(dlRes.data.quiet_hours_end || '08:00');
                setMaxRedirects(dlRes.data.max_redirects || 10);
                setConnectionTimeout(dlRes.data.connection_timeout_seconds || 30);
            } catch (error) {
                console.error('Failed to load settings', error);
            }
        };
        loadSettings();
    }, []);

    const saveNfoSettings = async () => {
        setRegexLoading(true);
        try {
            await api.post('/config', {
                PREFIX_REGEX: prefixRegex,
                FORMAT_DATE_IN_TITLE: formatDate,
                CLEAN_NAME: cleanName,
                SERIES_USE_SEASON_FOLDERS: useSeasonFolders,
                SERIES_INCLUDE_NAME_IN_FILENAME: includeSeriesName,
                SERIES_USE_CATEGORY_FOLDERS: useCategoryFolders,
                MOVIE_USE_CATEGORY_FOLDERS: useMovieCategoryFolders,
                SYNC_PARALLELISM_MOVIES: parallelismMovies,
                SYNC_PARALLELISM_SERIES: parallelismSeries,
                SYNC_RATE_LIMIT_RPS: rateLimitRps
            });
            toast.success('Settings saved successfully!');
        } catch (error) {
            console.error('Failed to save settings', error);
            toast.error('Failed to save settings. Please check the logs.');
        } finally {
            setRegexLoading(false);
        }
    };

    const savePlexSettings = async () => {
        setPlexSettingsLoading(true);
        try {
            await api.post('/config', {
                PLEX_PROXY_BASE_URL: plexProxyBaseUrl,
                PLEX_SHARED_KEY: plexSharedKey,
                PLEX_HLS_PROXY_MODE: plexHlsProxyMode
            });
            toast.success('Plex settings saved successfully!');
        } catch (error) {
            console.error('Failed to save Plex settings', error);
            toast.error('Failed to save Plex settings.');
        } finally {
            setPlexSettingsLoading(false);
        }
    };

    const testJellyfinConnection = async () => {
        setJellyfinLoading(true);
        setJellyfinTestResult(null);
        try {
            // Save URL and token first
            await api.post('/jellyfin/config', { url: jellyfinUrl, api_token: jellyfinToken || undefined });
            // Then test
            const res = await api.post<{ success: boolean; message: string; server_name?: string; version?: string }>('/jellyfin/test');
            setJellyfinTestResult(res.data);
            if (res.data.success) {
                toast.success(res.data.message);
                setJellyfinConfigured(true);
            } else {
                toast.error(res.data.message);
            }
        } catch (error: unknown) {
            const message = error instanceof Error ? error.message : 'Connection failed';
            setJellyfinTestResult({ success: false, message });
            toast.error(message);
        } finally {
            setJellyfinLoading(false);
        }
    };

    const saveDownloadSettings = async () => {
        setDownloadSettingsLoading(true);
        try {
            await api.post('/config/downloads', {
                download_mode: downloadMode,
                global_speed_limit_kbps: globalSpeedLimit,
                quiet_hours_enabled: quietHoursEnabled,
                quiet_hours_start: quietHoursStart,
                quiet_hours_end: quietHoursEnd,
                max_redirects: maxRedirects,
                connection_timeout_seconds: connectionTimeout
            });
            toast.success('Download settings saved successfully!');
        } catch (error) {
            console.error('Failed to save download settings', error);
            toast.error('Failed to save download settings.');
        } finally {
            setDownloadSettingsLoading(false);
        }
    };

    return (
        <div className="space-y-8">
            <div>
                <h2 className="text-3xl font-bold tracking-tight">Administration</h2>
                <p className="text-muted-foreground">Manage system settings and data.</p>
            </div>

            {/* Management Features */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                {/* Delete Generated Files */}
                <Card className="border-orange-200 dark:border-orange-900">
                    <CardHeader>
                        <CardTitle className="flex items-center gap-2 text-orange-700 dark:text-orange-400">
                            <Trash2 className="w-5 h-5" />
                            Delete Generated Files
                        </CardTitle>
                    </CardHeader>
                    <CardContent className="space-y-4">
                        <p className="text-sm text-muted-foreground">
                            Remove all .strm and .nfo files from movies and series directories.
                        </p>
                        <Button
                            variant="outline"
                            className="w-full border-orange-300 text-orange-700 hover:bg-orange-50 dark:border-orange-800 dark:text-orange-400 dark:hover:bg-orange-950"
                            onClick={() => setDialogState({ type: 'deleteFiles', step: 1 })}
                            disabled={loading}
                        >
                            <Trash2 className="w-4 h-4 mr-2" />
                            Delete All Files
                        </Button>
                    </CardContent>
                </Card>

                {/* Reset Database */}
                <Card className="border-red-200 dark:border-red-900">
                    <CardHeader>
                        <CardTitle className="flex items-center gap-2 text-red-700 dark:text-red-400">
                            <Database className="w-5 h-5" />
                            Reset Database
                        </CardTitle>
                    </CardHeader>
                    <CardContent className="space-y-4">
                        <p className="text-sm text-muted-foreground">
                            Clear all data from the database (subscriptions, sync states, selections, etc.).
                        </p>
                        <Button
                            variant="destructive"
                            className="w-full"
                            onClick={() => setDialogState({ type: 'resetDb', step: 1 })}
                            disabled={loading}
                        >
                            <Database className="w-4 h-4 mr-2" />
                            Reset Database
                        </Button>
                    </CardContent>
                </Card>

                {/* Reset All Data */}
                <Card className="border-red-300 dark:border-red-800 bg-red-50/50 dark:bg-red-950/20">
                    <CardHeader>
                        <CardTitle className="flex items-center gap-2 text-red-800 dark:text-red-300">
                            <AlertTriangle className="w-5 h-5" />
                            Reset All Data
                        </CardTitle>
                    </CardHeader>
                    <CardContent className="space-y-4">
                        <p className="text-sm text-muted-foreground">
                            Delete all files AND reset the database. Complete system reset.
                        </p>
                        <Button
                            variant="destructive"
                            className="w-full bg-red-700 hover:bg-red-800"
                            onClick={() => setDialogState({ type: 'resetAll', step: 1 })}
                            disabled={loading}
                        >
                            <AlertTriangle className="w-4 h-4 mr-2" />
                            Reset Everything
                        </Button>
                    </CardContent>
                </Card>
            </div>

            {/* Download Orchestration */}
            <Card className="border-indigo-200 dark:border-indigo-900">
                <CardHeader>
                    <CardTitle className="flex items-center gap-2 text-indigo-700 dark:text-indigo-400">
                        <Zap className="w-5 h-5" />
                        Download Orchestration
                    </CardTitle>
                </CardHeader>
                <CardContent className="space-y-6">
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                        {/* Mode & Limits */}
                        <div className="space-y-4">
                            <div className="space-y-2">
                                <Label>Download Mode</Label>
                                <select
                                    value={downloadMode}
                                    onChange={(e) => setDownloadMode(e.target.value)}
                                    className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
                                >
                                    <option value="parallel">Parallel (Recommended)</option>
                                    <option value="sequential">Sequential (One by one)</option>
                                </select>
                                <p className="text-xs text-muted-foreground">
                                    Parallel downloads multiple files at once based on subscription limits. Sequential forces one global download at a time.
                                </p>
                            </div>

                            <div className="space-y-2">
                                <Label>Global Speed Limit (KB/s)</Label>
                                <Input
                                    type="number"
                                    value={globalSpeedLimit}
                                    onChange={(e) => setGlobalSpeedLimit(parseInt(e.target.value) || 0)}
                                    placeholder="0 (Unlimited)"
                                />
                                <p className="text-xs text-muted-foreground">
                                    Set to 0 for unlimited speed. 1024 KB/s = 1 MB/s.
                                </p>
                            </div>
                        </div>

                        {/* Quiet Hours */}
                        <div className="space-y-4 border-l pl-6">
                            <div className="flex items-center space-x-2">
                                <Switch
                                    id="quiet-mode"
                                    checked={quietHoursEnabled}
                                    onCheckedChange={setQuietHoursEnabled}
                                />
                                <Label htmlFor="quiet-mode" className="flex items-center gap-2">
                                    <Clock className="w-4 h-4" /> Quiet Hours (Pause/Slow)
                                </Label>
                            </div>

                            <div className="grid grid-cols-2 gap-4">
                                <div className="space-y-2">
                                    <Label>Start Time</Label>
                                    <Input
                                        type="time"
                                        value={quietHoursStart}
                                        onChange={(e) => setQuietHoursStart(e.target.value)}
                                        disabled={!quietHoursEnabled}
                                    />
                                </div>
                                <div className="space-y-2">
                                    <Label>End Time</Label>
                                    <Input
                                        type="time"
                                        value={quietHoursEnd}
                                        onChange={(e) => setQuietHoursEnd(e.target.value)}
                                        disabled={!quietHoursEnabled}
                                    />
                                </div>
                            </div>
                            <p className="text-xs text-muted-foreground">
                                During these hours, downloads will respect the global speed limit or pause if configured.
                            </p>
                        </div>
                    </div>

                    {/* Connection Settings */}
                    <div className="border-t pt-6 mt-6">
                        <h3 className="text-sm font-semibold mb-4">Connection Settings</h3>
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                            <div className="space-y-2">
                                <Label>Max Redirects</Label>
                                <Input
                                    type="number"
                                    value={maxRedirects}
                                    onChange={(e) => setMaxRedirects(parseInt(e.target.value) || 10)}
                                    placeholder="10"
                                    min="1"
                                    max="50"
                                />
                                <p className="text-xs text-muted-foreground">
                                    Maximum HTTP redirects to follow (prevents infinite loops).
                                </p>
                            </div>

                            <div className="space-y-2">
                                <Label>Connection Timeout (seconds)</Label>
                                <Input
                                    type="number"
                                    value={connectionTimeout}
                                    onChange={(e) => setConnectionTimeout(parseInt(e.target.value) || 30)}
                                    placeholder="30"
                                    min="5"
                                    max="300"
                                />
                                <p className="text-xs text-muted-foreground">
                                    Timeout for establishing connections to download servers.
                                </p>
                            </div>
                        </div>
                    </div>

                    <Button
                        onClick={saveDownloadSettings}
                        disabled={downloadSettingsLoading}
                        className="w-full bg-indigo-600 hover:bg-indigo-700"
                    >
                        <Zap className="w-4 h-4 mr-2" />
                        Save Orchestration Settings
                    </Button>
                </CardContent>
            </Card>

            {/* NFO Settings */}
            <div>
                <h3 className="text-xl font-semibold mb-4">NFO Settings</h3>
                <Card className="border-blue-200 dark:border-blue-900">
                    <CardHeader>
                        <CardTitle className="flex items-center gap-2 text-blue-700 dark:text-blue-400">
                            <Settings className="w-5 h-5" />
                            Title Formatting
                        </CardTitle>
                    </CardHeader>
                    <CardContent className="space-y-6">
                        <div className="space-y-2">
                            <label className="text-sm font-medium">Title Prefix Regex</label>
                            <p className="text-sm text-muted-foreground">
                                Pattern to strip language/country prefixes. Default: <code className="bg-muted px-1 py-0.5 rounded">^(?:[A-Za-z0-9.-]+_|[A-Za-z]{"{2,}"}\\s*-\\s*)</code>
                            </p>
                            <Input
                                type="text"
                                value={prefixRegex}
                                onChange={(e) => setPrefixRegex(e.target.value)}
                                placeholder="^(?:[A-Za-z0-9.-]+_|[A-Za-z]{2,}\s*-\s*)"
                                className="font-mono"
                            />
                            <p className="text-xs text-muted-foreground">
                                Examples: "FR - Movie Name" → "Movie Name"
                            </p>
                        </div>

                        <div className="space-y-4 pt-4 border-t">
                            <div className="flex items-start space-x-3">
                                <input
                                    type="checkbox"
                                    id="formatDate"
                                    checked={formatDate}
                                    onChange={(e) => setFormatDate(e.target.checked)}
                                    className="h-4 w-4 mt-1 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                                />
                                <div>
                                    <label htmlFor="formatDate" className="text-sm font-medium leading-none cursor-pointer">
                                        Format date at end of name
                                    </label>
                                    <p className="text-xs text-muted-foreground mt-1">
                                        If name ends with year (e.g. "Name_2024"), format as "Name (2024)"
                                    </p>
                                </div>
                            </div>

                            <div className="flex items-start space-x-3">
                                <input
                                    type="checkbox"
                                    id="cleanName"
                                    checked={cleanName}
                                    onChange={(e) => setCleanName(e.target.checked)}
                                    className="h-4 w-4 mt-1 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                                />
                                <div>
                                    <label htmlFor="cleanName" className="text-sm font-medium leading-none cursor-pointer">
                                        Clean name
                                    </label>
                                    <p className="text-xs text-muted-foreground mt-1">
                                        Replace all remaining underscores "_" with spaces
                                    </p>
                                </div>
                            </div>
                        </div>

                        <Button
                            variant="default"
                            className="w-full"
                            onClick={saveNfoSettings}
                            disabled={regexLoading}
                        >
                            <Settings className="w-4 h-4 mr-2" />
                            Save Settings
                        </Button>
                    </CardContent>
                </Card>

                {/* Movies Formatting Settings */}
                <Card className="border-orange-200 dark:border-orange-900">
                    <CardHeader>
                        <CardTitle className="flex items-center gap-2 text-orange-700 dark:text-orange-400">
                            <Settings className="w-5 h-5" />
                            Movies Formatting
                        </CardTitle>
                    </CardHeader>
                    <CardContent className="space-y-6">
                        <div className="flex items-start space-x-3">
                            <input
                                type="checkbox"
                                id="useMovieCategoryFolders"
                                checked={useMovieCategoryFolders}
                                onChange={(e) => setUseMovieCategoryFolders(e.target.checked)}
                                className="h-4 w-4 mt-1 rounded border-gray-300 text-orange-600 focus:ring-orange-500"
                            />
                            <div>
                                <label htmlFor="useMovieCategoryFolders" className="text-sm font-medium leading-none cursor-pointer">
                                    Use Category Folders
                                </label>
                                <p className="text-xs text-muted-foreground mt-1">
                                    Organize movies into folders by category (e.g. /movies/Action/Name). Disable for direct structure.
                                </p>
                            </div>
                        </div>

                        <Button
                            variant="default"
                            className="w-full bg-orange-600 hover:bg-orange-700"
                            onClick={saveNfoSettings}
                            disabled={regexLoading}
                        >
                            <Settings className="w-4 h-4 mr-2" />
                            Save Movies Settings
                        </Button>
                    </CardContent>
                </Card>

                {/* Series Formatting Settings */}
                <Card className="border-purple-200 dark:border-purple-900">
                    <CardHeader>
                        <CardTitle className="flex items-center gap-2 text-purple-700 dark:text-purple-400">
                            <Settings className="w-5 h-5" />
                            Series Formatting
                        </CardTitle>
                    </CardHeader>
                    <CardContent className="space-y-6">
                        <div className="flex items-start space-x-3">
                            <input
                                type="checkbox"
                                id="useSeasonFolders"
                                checked={useSeasonFolders}
                                onChange={(e) => setUseSeasonFolders(e.target.checked)}
                                className="h-4 w-4 mt-1 rounded border-gray-300 text-purple-600 focus:ring-purple-500"
                            />
                            <div>
                                <label htmlFor="useSeasonFolders" className="text-sm font-medium leading-none cursor-pointer">
                                    Use Season Folders
                                </label>
                                <p className="text-xs text-muted-foreground mt-1">
                                    Organize episodes into "Season XX" subfolders (Default: Enabled)
                                </p>
                            </div>
                        </div>

                        <div className="flex items-start space-x-3">
                            <input
                                type="checkbox"
                                id="useCategoryFolders"
                                checked={useCategoryFolders}
                                onChange={(e) => setUseCategoryFolders(e.target.checked)}
                                className="h-4 w-4 mt-1 rounded border-gray-300 text-purple-600 focus:ring-purple-500"
                            />
                            <div>
                                <label htmlFor="useCategoryFolders" className="text-sm font-medium leading-none cursor-pointer">
                                    Use Category Folders
                                </label>
                                <p className="text-xs text-muted-foreground mt-1">
                                    Organize series into folders by category (e.g. /series/Action/Name). Disable for direct structure (Jellyfin friendly).
                                </p>
                            </div>
                        </div>

                        <div className="flex items-start space-x-3">
                            <input
                                type="checkbox"
                                id="includeSeriesName"
                                checked={includeSeriesName}
                                onChange={(e) => setIncludeSeriesName(e.target.checked)}
                                className="h-4 w-4 mt-1 rounded border-gray-300 text-purple-600 focus:ring-purple-500"
                            />
                            <div>
                                <label htmlFor="includeSeriesName" className="text-sm font-medium leading-none cursor-pointer">
                                    Include Series Name in Filename
                                </label>
                                <p className="text-xs text-muted-foreground mt-1">
                                    Prefix filenames with series name (e.g. "Series - S01E01 - Title.strm")
                                </p>
                            </div>
                        </div>

                        <Button
                            variant="default"
                            className="w-full bg-purple-600 hover:bg-purple-700"
                            onClick={saveNfoSettings}
                            disabled={regexLoading}
                        >
                            <Settings className="w-4 h-4 mr-2" />
                            Save Series Settings
                        </Button>
                    </CardContent>
                </Card>


                {/* Performance Settings */}
                <Card className="border-cyan-200 dark:border-cyan-900">
                    <CardHeader>
                        <CardTitle className="flex items-center gap-2 text-cyan-700 dark:text-cyan-400">
                            <Settings className="w-5 h-5" />
                            Performance Settings
                        </CardTitle>
                    </CardHeader>
                    <CardContent className="space-y-6">
                        <div className="space-y-2">
                            <label className="text-sm font-medium">Movies Parallel Config (Simultaneous Downloads)</label>
                            <Input
                                type="number"
                                min="1"
                                max="50"
                                value={parallelismMovies}
                                onChange={(e) => setParallelismMovies(parseInt(e.target.value) || 5)}
                            />
                            <p className="text-xs text-muted-foreground">Default: 5. Higher values need more RAM/CPU.</p>
                        </div>

                        <div className="space-y-2">
                            <label className="text-sm font-medium">Series Parallel Config</label>
                            <Input
                                type="number"
                                min="1"
                                max="20"
                                value={parallelismSeries}
                                onChange={(e) => setParallelismSeries(parseInt(e.target.value) || 5)}
                            />
                            <p className="text-xs text-muted-foreground">Default: 5. Series sync is intensive.</p>
                        </div>

                        <div className="space-y-2">
                            <label className="text-sm font-medium">Xtream Rate Limit (requests / second)</label>
                            <Input
                                type="number"
                                min="0.5"
                                max="50"
                                step="0.5"
                                value={rateLimitRps}
                                onChange={(e) => setRateLimitRps(parseFloat(e.target.value) || 5)}
                            />
                            <p className="text-xs text-muted-foreground">
                                Default: 5. Caps how fast the provider's API is called. The sync slows down
                                automatically when the provider answers 429/503, then speeds back up.
                            </p>
                        </div>

                        <Button
                            variant="default"
                            className="w-full bg-cyan-600 hover:bg-cyan-700"
                            onClick={saveNfoSettings}
                            disabled={regexLoading}
                        >
                            <Settings className="w-4 h-4 mr-2" />
                            Save Performance
                        </Button>
                    </CardContent>
                </Card>

                {/* Plex Settings */}
                <Card className="border-green-200 dark:border-green-900">
                    <CardHeader>
                        <CardTitle className="flex items-center gap-2 text-green-700 dark:text-green-400">
                            <Server className="w-5 h-5" />
                            Plex Settings
                        </CardTitle>
                    </CardHeader>
                    <CardContent className="space-y-6">
                        <div className="space-y-2">
                            <label className="text-sm font-medium">Proxy Base URL</label>
                            <Input
                                type="text"
                                value={plexProxyBaseUrl}
                                onChange={(e) => setPlexProxyBaseUrl(e.target.value)}
                                placeholder="http://192.168.1.100:8000"
                            />
                            <p className="text-xs text-muted-foreground">
                                Base URL for Plex proxy streaming. Use the IP/hostname accessible by your media server (Jellyfin).
                                Example: <code className="bg-muted px-1 py-0.5 rounded">http://192.168.1.100</code>
                            </p>
                        </div>

                        <div className="space-y-2">
                            <label className="text-sm font-medium">Shared Key (Authentication)</label>
                            <Input
                                type="password"
                                value={plexSharedKey}
                                onChange={(e) => setPlexSharedKey(e.target.value)}
                                placeholder="Enter a secret key to protect the proxy"
                            />
                            <p className="text-xs text-muted-foreground">
                                Optional secret key to protect the Plex proxy endpoint. Leave empty to disable authentication.
                            </p>
                            <div className="bg-yellow-50 dark:bg-yellow-950/30 border border-yellow-200 dark:border-yellow-800 rounded p-3 mt-2">
                                <p className="text-xs text-yellow-700 dark:text-yellow-400">
                                    <AlertTriangle className="w-3 h-3 inline mr-1" />
                                    <strong>Warning:</strong> If you change this key, you must re-run the Plex sync to update all STRM files with the new key.
                                    Use the <a href="/plex/selection" className="underline hover:text-yellow-900 dark:hover:text-yellow-300">Plex Selection page</a> to trigger a new sync.
                                </p>
                            </div>
                        </div>

                        <div className="flex items-center justify-between pt-4 border-t">
                            <div className="space-y-0.5">
                                <Label>HLS Proxy Mode</Label>
                                <p className="text-sm text-muted-foreground">
                                    Enable for clients that don't follow redirects (e.g., Findroid).
                                    Proxies HLS playlists through this server instead of redirecting.
                                </p>
                            </div>
                            <Switch
                                checked={plexHlsProxyMode}
                                onCheckedChange={setPlexHlsProxyMode}
                            />
                        </div>

                        <Button
                            variant="default"
                            className="w-full bg-green-600 hover:bg-green-700"
                            onClick={savePlexSettings}
                            disabled={plexSettingsLoading}
                        >
                            <Server className="w-4 h-4 mr-2" />
                            Save Plex Settings
                        </Button>
                    </CardContent>
                </Card>

                {/* Jellyfin Settings */}
                <Card className="border-blue-200 dark:border-blue-900">
                    <CardHeader>
                        <CardTitle className="flex items-center gap-2 text-blue-700 dark:text-blue-400">
                            <Server className="w-5 h-5" />
                            Jellyfin Settings
                        </CardTitle>
                    </CardHeader>
                    <CardContent className="space-y-6">
                        <div className="space-y-2">
                            <label className="text-sm font-medium">Jellyfin Server URL</label>
                            <Input
                                type="text"
                                value={jellyfinUrl}
                                onChange={(e) => setJellyfinUrl(e.target.value)}
                                placeholder="http://jellyfin:8096"
                            />
                            <p className="text-xs text-muted-foreground">
                                URL of your Jellyfin server (e.g. <code className="bg-muted px-1 py-0.5 rounded">http://192.168.1.100:8096</code>)
                            </p>
                        </div>

                        <div className="space-y-2">
                            <label className="text-sm font-medium">API Token</label>
                            <Input
                                type="password"
                                value={jellyfinToken}
                                onChange={(e) => setJellyfinToken(e.target.value)}
                                placeholder="Enter Jellyfin API token"
                            />
                            <p className="text-xs text-muted-foreground">
                                Create an API token in Jellyfin: Dashboard &gt; API Keys &gt; New API Key
                            </p>
                        </div>

                        {/* Test Result */}
                        {jellyfinTestResult && (
                            <div className={`p-3 rounded-md text-sm ${jellyfinTestResult.success ? 'bg-green-500/10 text-green-600 border border-green-500/20' : 'bg-red-500/10 text-red-600 border border-red-500/20'}`}>
                                {jellyfinTestResult.message}
                                {jellyfinTestResult.server_name && (
                                    <div className="mt-1 text-xs">
                                        Server: {jellyfinTestResult.server_name} (v{jellyfinTestResult.version})
                                    </div>
                                )}
                            </div>
                        )}

                        {jellyfinConfigured && (
                            <div className="p-3 rounded-md bg-green-500/10 text-green-600 border border-green-500/20 text-sm">
                                Jellyfin is configured. You can now select libraries in Scheduler pages.
                            </div>
                        )}

                        <Button
                            variant="default"
                            className="w-full bg-blue-600 hover:bg-blue-700"
                            onClick={testJellyfinConnection}
                            disabled={jellyfinLoading || !jellyfinUrl}
                        >
                            <Server className="w-4 h-4 mr-2" />
                            {jellyfinLoading ? 'Testing...' : 'Save & Test Connection'}
                        </Button>
                    </CardContent>
                </Card>
            </div>

            {/* Cache Management */}
            <div>
                <h3 className="text-xl font-semibold mb-4 text-gray-700 dark:text-gray-200">Cache Management</h3>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                    <Card className="border-yellow-200 dark:border-yellow-900">
                        <CardHeader>
                            <CardTitle className="flex items-center gap-2 text-yellow-700 dark:text-yellow-400">
                                <Database className="w-5 h-5" />
                                Clear Movie Cache
                            </CardTitle>
                        </CardHeader>
                        <CardContent>
                            <p className="text-sm text-muted-foreground mb-4">
                                Force metadata refresh for all movies on next sync. Does not delete files.
                            </p>
                            <Button
                                variant="outline"
                                className="w-full border-yellow-300 text-yellow-700 hover:bg-yellow-50 dark:border-yellow-800 dark:text-yellow-400 dark:hover:bg-yellow-950"
                                onClick={() => setDialogState({ type: 'clearMovieCache', step: 1 })}
                                disabled={loading}
                            >
                                Clear Movie Cache
                            </Button>
                        </CardContent>
                    </Card>

                    <Card className="border-yellow-200 dark:border-yellow-900">
                        <CardHeader>
                            <CardTitle className="flex items-center gap-2 text-yellow-700 dark:text-yellow-400">
                                <Database className="w-5 h-5" />
                                Clear Series Cache
                            </CardTitle>
                        </CardHeader>
                        <CardContent>
                            <p className="text-sm text-muted-foreground mb-4">
                                Force metadata refresh for all series/episodes on next sync. Does not delete files.
                            </p>
                            <Button
                                variant="outline"
                                className="w-full border-yellow-300 text-yellow-700 hover:bg-yellow-50 dark:border-yellow-800 dark:text-yellow-400 dark:hover:bg-yellow-950"
                                onClick={() => setDialogState({ type: 'clearSeriesCache', step: 1 })}
                                disabled={loading}
                            >
                                Clear Series Cache
                            </Button>
                        </CardContent>
                    </Card>

                    <Card className="border-orange-200 dark:border-orange-900">
                        <CardHeader>
                            <CardTitle className="flex items-center gap-2 text-orange-700 dark:text-orange-400">
                                <Server className="w-5 h-5" />
                                Clear Plex Cache
                            </CardTitle>
                        </CardHeader>
                        <CardContent>
                            <p className="text-sm text-muted-foreground mb-4">
                                Force metadata refresh for all Plex movies/series on next sync. Use this if files are missing after sync.
                            </p>
                            <Button
                                variant="outline"
                                className="w-full border-orange-300 text-orange-700 hover:bg-orange-50 dark:border-orange-800 dark:text-orange-400 dark:hover:bg-orange-950"
                                onClick={() => setDialogState({ type: 'clearPlexCache', step: 1 })}
                                disabled={loading}
                            >
                                Clear Plex Cache
                            </Button>
                        </CardContent>
                    </Card>
                </div>
            </div>

            {/* Confirmation Dialogs */}
            <Dialog
                isOpen={!!dialogState.type}
                onClose={() => {
                    setDialogState({ type: null, step: 0 });
                    setConfirmationInput('');
                }}
                title={
                    dialogState.type === 'deleteFiles' ? 'Delete Generated Files' :
                        dialogState.type === 'resetDb' ? 'Reset Database' :
                            dialogState.type === 'resetAll' ? 'Reset Everything' :
                                dialogState.type === 'clearMovieCache' ? 'Clear Movie Cache' :
                                    dialogState.type === 'clearSeriesCache' ? 'Clear Series Cache' :
                                        'Clear Plex Cache'
                }
            >
                <div className="space-y-4">
                    {/* Content based on type */}
                    {dialogState.type === 'deleteFiles' && (
                        <p>Are you sure you want to delete all generated .strm and .nfo files? This cannot be undone.</p>
                    )}
                    {dialogState.type === 'resetDb' && (
                        <p className="text-red-600 font-bold">⚠️ WARNING: This will delete ALL data from the database! Subscriptions, settings, and monitoring state will be lost.</p>
                    )}
                    {dialogState.type === 'resetAll' && (
                        <div className="space-y-4">
                            <p className="text-red-600 font-extrabold">🚨 CRITICAL WARNING 🚨</p>
                            <p>This will DELETE ALL generated files AND RESET the database. Your entire system will be wiped clean.</p>
                            <div className="bg-red-50 p-3 rounded border border-red-200">
                                <label className="block text-sm font-medium text-red-800 mb-2">
                                    Type <span className="font-mono bg-white px-1 rounded">YES</span> to confirm:
                                </label>
                                <Input
                                    value={confirmationInput}
                                    onChange={(e) => setConfirmationInput(e.target.value)}
                                    placeholder="YES"
                                    className="border-red-300"
                                />
                            </div>
                        </div>
                    )}
                    {dialogState.type === 'clearMovieCache' && (
                        <p>This will force metadata to be re-fetched for all movies on the next sync. Files are not deleted.</p>
                    )}
                    {dialogState.type === 'clearSeriesCache' && (
                        <p>This will force metadata to be re-fetched for all series/episodes on the next sync. Files are not deleted.</p>
                    )}
                    {dialogState.type === 'clearPlexCache' && (
                        <p>This will force all Plex movies and series to be re-synced on the next sync. Use this if STRM files are missing after a sync (e.g., volume mount issue). Files are not deleted.</p>
                    )}

                    {/* Actions */}
                    <div className="flex justify-end gap-2 mt-4">
                        <Button
                            variant="outline"
                            onClick={() => {
                                setDialogState({ type: null, step: 0 });
                                setConfirmationInput('');
                            }}
                        >
                            Cancel
                        </Button>
                        <Button
                            variant="destructive"
                            disabled={dialogState.type === 'resetAll' && confirmationInput !== 'YES'}
                            onClick={async () => {
                                setLoading(true);
                                try {
                                    if (dialogState.type === 'deleteFiles') {
                                        await api.post('/admin/delete-files');
                                        toast.success('All generated files have been deleted successfully.');
                                    } else if (dialogState.type === 'resetDb') {
                                        await api.post('/admin/reset-database');
                                        toast.success('Database has been reset successfully.');
                                    } else if (dialogState.type === 'resetAll') {
                                        await api.post('/admin/reset-all');
                                        toast.success('All data has been reset successfully.');
                                    } else if (dialogState.type === 'clearMovieCache') {
                                        await api.post('/admin/clear-movie-cache');
                                        toast.success('Movie cache cleared successfully.');
                                    } else if (dialogState.type === 'clearSeriesCache') {
                                        await api.post('/admin/clear-series-cache');
                                        toast.success('Series cache cleared successfully.');
                                    } else if (dialogState.type === 'clearPlexCache') {
                                        await api.post('/admin/clear-plex-cache');
                                        toast.success('Plex cache cleared successfully. Run a Plex sync to regenerate files.');
                                    }
                                } catch (error) {
                                    console.error(`Failed to execute ${dialogState.type}`, error);
                                    toast.error('Operation failed. Please check the logs.');
                                } finally {
                                    setLoading(false);
                                    setDialogState({ type: null, step: 0 });
                                    setConfirmationInput('');
                                }
                            }}
                        >
                            {dialogState.type?.startsWith('reset') || dialogState.type === 'deleteFiles' ? 'Configrm Delete' : 'Confirm'}
                        </Button>
                    </div>
                </div>
            </Dialog>
        </div>
    );
}
