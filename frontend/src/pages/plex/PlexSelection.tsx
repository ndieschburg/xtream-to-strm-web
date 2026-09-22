import { useEffect, useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { RefreshCw, Check, Loader2, Play, Film, Tv, Library, Save, StopCircle } from 'lucide-react';
import api from '@/lib/api';

interface PlexAccount {
    id: number;
    name: string;
    username: string;
}

interface PlexServer {
    id: number;
    account_id: number;
    name: string;
    is_selected: boolean;
}

interface PlexLibrary {
    id: number;
    server_id: number;
    library_key: string;
    title: string;
    type: string;
    item_count: number;
    is_selected: boolean;
    last_sync: string | null;
}

interface SyncStatus {
    id: number;
    server_id: number;
    type: string;
    last_sync: string | null;
    status: string;
    items_added: number;
    items_deleted: number;
    files_written: number;
    error_message: string | null;
}

export default function PlexSelection() {
    const [accounts, setAccounts] = useState<PlexAccount[]>([]);
    const [selectedAccountId, setSelectedAccountId] = useState<number | null>(null);
    const [servers, setServers] = useState<PlexServer[]>([]);
    const [selectedServerId, setSelectedServerId] = useState<number | null>(null);
    const [libraries, setLibraries] = useState<PlexLibrary[]>([]);
    const [syncStatuses, setSyncStatuses] = useState<SyncStatus[]>([]);
    const [loading, setLoading] = useState(false);
    const [syncing, setSyncing] = useState(false);
    const [refreshingLibs, setRefreshingLibs] = useState(false);

    const fetchAccounts = async () => {
        try {
            const res = await api.get<PlexAccount[]>('/plex/accounts');
            setAccounts(res.data);
            if (res.data.length > 0 && !selectedAccountId) {
                setSelectedAccountId(res.data[0].id);
            }
        } catch (error) {
            console.error("Failed to fetch Plex accounts", error);
        }
    };

    const fetchServers = async (accountId: number) => {
        try {
            const res = await api.get<PlexServer[]>(`/plex/servers/${accountId}`);
            const selectedServers = res.data.filter(s => s.is_selected);
            setServers(selectedServers);
            if (selectedServers.length > 0 && !selectedServerId) {
                setSelectedServerId(selectedServers[0].id);
            }
        } catch (error) {
            console.error("Failed to fetch Plex servers", error);
        }
    };

    const fetchLibraries = async (serverId: number) => {
        setLoading(true);
        try {
            const res = await api.get<PlexLibrary[]>(`/plex/libraries/${serverId}`);
            setLibraries(res.data);
        } catch (error) {
            console.error("Failed to fetch libraries", error);
        } finally {
            setLoading(false);
        }
    };

    const fetchSyncStatus = async (serverId: number) => {
        try {
            const res = await api.get<SyncStatus[]>(`/plex/sync/status/${serverId}`);
            setSyncStatuses(res.data);
        } catch (error) {
            console.error("Failed to fetch sync status", error);
        }
    };

    useEffect(() => {
        fetchAccounts();
    }, []);

    useEffect(() => {
        if (selectedAccountId) {
            fetchServers(selectedAccountId);
        }
    }, [selectedAccountId]);

    useEffect(() => {
        if (selectedServerId) {
            fetchLibraries(selectedServerId);
            fetchSyncStatus(selectedServerId);
        }
    }, [selectedServerId]);

    // Poll sync status while syncing
    useEffect(() => {
        if (!selectedServerId) return;

        const hasRunning = syncStatuses.some(s => s.status === 'running');
        if (!hasRunning) return;

        const interval = setInterval(() => {
            fetchSyncStatus(selectedServerId);
        }, 3000);

        return () => clearInterval(interval);
    }, [syncStatuses, selectedServerId]);

    const handleSyncLibraries = async () => {
        if (!selectedServerId) return;
        setRefreshingLibs(true);
        try {
            await api.post(`/plex/libraries/${selectedServerId}/sync`);
            await fetchLibraries(selectedServerId);
        } catch (error) {
            console.error("Failed to sync libraries", error);
        } finally {
            setRefreshingLibs(false);
        }
    };

    const toggleLibrarySelection = (library: PlexLibrary) => {
        setLibraries(prev => prev.map(lib =>
            lib.id === library.id ? { ...lib, is_selected: !lib.is_selected } : lib
        ));
    };

    const saveSelection = async () => {
        if (!selectedServerId) return;
        setLoading(true);
        try {
            const selectedIds = libraries.filter(l => l.is_selected).map(l => l.id);
            await api.post(`/plex/libraries/${selectedServerId}/selection`, {
                library_ids: selectedIds
            });
        } catch (error) {
            console.error("Failed to save selection", error);
        } finally {
            setLoading(false);
        }
    };

    const triggerSync = async (type: 'movies' | 'series') => {
        if (!selectedServerId) return;

        // Check if any libraries of this type are selected
        const relevantLibs = libraries.filter(l =>
            type === 'movies' ? l.type === 'movie' : l.type === 'show'
        );
        const selectedLibs = relevantLibs.filter(l => l.is_selected);

        if (selectedLibs.length === 0) {
            alert(`No ${type === 'movies' ? 'movie' : 'TV show'} libraries selected. Please select at least one library and click "Save Selection" first.`);
            return;
        }

        // Auto-save selection before syncing
        try {
            const selectedIds = libraries.filter(l => l.is_selected).map(l => l.id);
            await api.post(`/plex/libraries/${selectedServerId}/selection`, {
                library_ids: selectedIds
            });
        } catch (error) {
            console.error("Failed to save selection before sync", error);
        }

        setSyncing(true);
        try {
            await api.post(`/plex/sync/${type}/${selectedServerId}`);
            await fetchSyncStatus(selectedServerId);
        } catch (error) {
            console.error(`Failed to trigger ${type} sync`, error);
        } finally {
            setSyncing(false);
        }
    };

    const stopSync = async (type: 'movies' | 'series') => {
        if (!selectedServerId) return;
        try {
            await api.post(`/plex/sync/stop/${selectedServerId}/${type}`);
            await fetchSyncStatus(selectedServerId);
        } catch (error) {
            console.error(`Failed to stop ${type} sync`, error);
        }
    };

    const getStatusBadge = (status: string) => {
        switch (status) {
            case 'running':
                return <span className="px-2 py-1 rounded text-xs bg-blue-500/20 text-blue-500 flex items-center gap-1">
                    <Loader2 className="w-3 h-3 animate-spin" /> Running
                </span>;
            case 'success':
                return <span className="px-2 py-1 rounded text-xs bg-green-500/20 text-green-500">Success</span>;
            case 'failed':
                return <span className="px-2 py-1 rounded text-xs bg-red-500/20 text-red-500">Failed</span>;
            default:
                return <span className="px-2 py-1 rounded text-xs bg-gray-500/20 text-gray-500">Idle</span>;
        }
    };

    const movieLibraries = libraries.filter(l => l.type === 'movie');
    const showLibraries = libraries.filter(l => l.type === 'show');
    const moviesStatus = syncStatuses.find(s => s.type === 'movies');
    const seriesStatus = syncStatuses.find(s => s.type === 'series');

    return (
        <div className="space-y-8">
            <div>
                <h2 className="text-3xl font-bold tracking-tight">Plex Library Selection</h2>
                <p className="text-muted-foreground">Select which Plex libraries to sync as STRM files.</p>
            </div>

            {/* Server Selector */}
            {accounts.length > 0 && (
                <Card>
                    <CardHeader>
                        <CardTitle>Select Server</CardTitle>
                    </CardHeader>
                    <CardContent>
                        <div className="flex flex-wrap gap-4 items-center">
                            <select
                                value={selectedAccountId || ''}
                                onChange={(e) => {
                                    setSelectedAccountId(Number(e.target.value));
                                    setSelectedServerId(null);
                                    setLibraries([]);
                                }}
                                className="flex h-10 rounded-md border border-input bg-background px-3 py-2 text-sm"
                            >
                                {accounts.map(account => (
                                    <option key={account.id} value={account.id}>
                                        {account.name}
                                    </option>
                                ))}
                            </select>
                            {servers.length > 0 && (
                                <select
                                    value={selectedServerId || ''}
                                    onChange={(e) => setSelectedServerId(Number(e.target.value))}
                                    className="flex h-10 rounded-md border border-input bg-background px-3 py-2 text-sm"
                                >
                                    {servers.map(server => (
                                        <option key={server.id} value={server.id}>
                                            {server.name}
                                        </option>
                                    ))}
                                </select>
                            )}
                            {selectedServerId && (
                                <Button
                                    onClick={handleSyncLibraries}
                                    disabled={refreshingLibs}
                                    variant="outline"
                                >
                                    {refreshingLibs ? (
                                        <Loader2 className="w-4 h-4 animate-spin mr-2" />
                                    ) : (
                                        <RefreshCw className="w-4 h-4 mr-2" />
                                    )}
                                    Sync Libraries
                                </Button>
                            )}
                        </div>
                        {servers.length === 0 && selectedAccountId && (
                            <p className="text-sm text-muted-foreground mt-2">
                                No selected servers. Go to <strong>Servers</strong> page and select servers to use.
                            </p>
                        )}
                    </CardContent>
                </Card>
            )}

            {/* No Accounts Warning */}
            {accounts.length === 0 && (
                <Card className="border-yellow-500/50 bg-yellow-500/5">
                    <CardContent className="pt-6">
                        <p className="text-yellow-500">
                            No Plex accounts configured. Please add an account first in the <strong>Accounts</strong> page.
                        </p>
                    </CardContent>
                </Card>
            )}

            {/* Library Selection */}
            {selectedServerId && libraries.length > 0 && (
                <>
                    {/* Movie Libraries */}
                    {movieLibraries.length > 0 && (
                        <Card>
                            <CardHeader className="flex flex-row items-center justify-between">
                                <CardTitle className="flex items-center gap-2">
                                    <Film className="w-5 h-5" />
                                    Movie Libraries
                                </CardTitle>
                                <div className="flex items-center gap-2">
                                    {moviesStatus && getStatusBadge(moviesStatus.status)}
                                    {moviesStatus?.status === 'running' ? (
                                        <Button
                                            onClick={() => stopSync('movies')}
                                            variant="destructive"
                                            size="sm"
                                        >
                                            <StopCircle className="w-4 h-4 mr-2" />
                                            Stop Sync
                                        </Button>
                                    ) : (
                                        <Button
                                            onClick={() => triggerSync('movies')}
                                            disabled={syncing}
                                            size="sm"
                                        >
                                            <Play className="w-4 h-4 mr-2" />
                                            Sync Movies
                                        </Button>
                                    )}
                                </div>
                            </CardHeader>
                            <CardContent>
                                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                                    {movieLibraries.map(library => (
                                        <div
                                            key={library.id}
                                            onClick={() => toggleLibrarySelection(library)}
                                            className={`p-4 border rounded-lg cursor-pointer transition-colors ${
                                                library.is_selected
                                                    ? 'border-green-500 bg-green-500/10'
                                                    : 'border-border hover:border-gray-400'
                                            }`}
                                        >
                                            <div className="flex items-center justify-between">
                                                <div className="flex items-center gap-2">
                                                    <Library className="w-5 h-5 text-muted-foreground" />
                                                    <span className="font-medium">{library.title}</span>
                                                </div>
                                                <div className={`w-5 h-5 rounded flex items-center justify-center border-2 ${
                                                    library.is_selected
                                                        ? 'bg-green-500 border-green-500 text-white'
                                                        : 'border-gray-300'
                                                }`}>
                                                    {library.is_selected && <Check className="w-3 h-3" />}
                                                </div>
                                            </div>
                                            <div className="text-sm text-muted-foreground mt-1">
                                                {library.item_count} items
                                            </div>
                                        </div>
                                    ))}
                                </div>
                                {moviesStatus && (moviesStatus.items_added > 0 || moviesStatus.items_deleted > 0) && (
                                    <div
                                        className="mt-4 text-sm text-muted-foreground"
                                        title="STRM files actually written to disk, an unchanged file is left untouched"
                                    >
                                        Last sync: +{moviesStatus.items_added} movies added, -{moviesStatus.items_deleted} removed, 
                                        {moviesStatus.files_written || 0} STRM written
                                    </div>
                                )}
                            </CardContent>
                        </Card>
                    )}

                    {/* TV Libraries */}
                    {showLibraries.length > 0 && (
                        <Card>
                            <CardHeader className="flex flex-row items-center justify-between">
                                <CardTitle className="flex items-center gap-2">
                                    <Tv className="w-5 h-5" />
                                    TV Show Libraries
                                </CardTitle>
                                <div className="flex items-center gap-2">
                                    {seriesStatus && getStatusBadge(seriesStatus.status)}
                                    {seriesStatus?.status === 'running' ? (
                                        <Button
                                            onClick={() => stopSync('series')}
                                            variant="destructive"
                                            size="sm"
                                        >
                                            <StopCircle className="w-4 h-4 mr-2" />
                                            Stop Sync
                                        </Button>
                                    ) : (
                                        <Button
                                            onClick={() => triggerSync('series')}
                                            disabled={syncing}
                                            size="sm"
                                        >
                                            <Play className="w-4 h-4 mr-2" />
                                            Sync Series
                                        </Button>
                                    )}
                                </div>
                            </CardHeader>
                            <CardContent>
                                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                                    {showLibraries.map(library => (
                                        <div
                                            key={library.id}
                                            onClick={() => toggleLibrarySelection(library)}
                                            className={`p-4 border rounded-lg cursor-pointer transition-colors ${
                                                library.is_selected
                                                    ? 'border-green-500 bg-green-500/10'
                                                    : 'border-border hover:border-gray-400'
                                            }`}
                                        >
                                            <div className="flex items-center justify-between">
                                                <div className="flex items-center gap-2">
                                                    <Library className="w-5 h-5 text-muted-foreground" />
                                                    <span className="font-medium">{library.title}</span>
                                                </div>
                                                <div className={`w-5 h-5 rounded flex items-center justify-center border-2 ${
                                                    library.is_selected
                                                        ? 'bg-green-500 border-green-500 text-white'
                                                        : 'border-gray-300'
                                                }`}>
                                                    {library.is_selected && <Check className="w-3 h-3" />}
                                                </div>
                                            </div>
                                            <div className="text-sm text-muted-foreground mt-1">
                                                {library.item_count} items
                                            </div>
                                        </div>
                                    ))}
                                </div>
                                {seriesStatus && (seriesStatus.items_added > 0 || seriesStatus.items_deleted > 0) && (
                                    <div
                                        className="mt-4 text-sm text-muted-foreground"
                                        title="STRM files actually written to disk, an unchanged file is left untouched"
                                    >
                                        Last sync: +{seriesStatus.items_added} episodes added, -{seriesStatus.items_deleted} removed, 
                                        {seriesStatus.files_written || 0} STRM written
                                    </div>
                                )}
                            </CardContent>
                        </Card>
                    )}

                    {/* Save Selection Button */}
                    <div className="flex justify-end">
                        <Button onClick={saveSelection} disabled={loading}>
                            <Save className="w-4 h-4 mr-2" />
                            Save Selection
                        </Button>
                    </div>
                </>
            )}

            {/* Empty State */}
            {selectedServerId && libraries.length === 0 && !loading && (
                <Card>
                    <CardContent className="pt-6">
                        <div className="text-center text-muted-foreground">
                            <Library className="w-12 h-12 mx-auto mb-4 opacity-50" />
                            <p>No libraries found. Click "Sync Libraries" to fetch from your Plex server.</p>
                        </div>
                    </CardContent>
                </Card>
            )}
        </div>
    );
}
