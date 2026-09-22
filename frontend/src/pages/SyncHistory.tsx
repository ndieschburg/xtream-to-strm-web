import { useState, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { History, CheckCircle, XCircle, Loader2, Filter, Server, Tv, Radio } from 'lucide-react';
import api from '@/lib/api';
import { formatDateTime } from '@/lib/utils';

interface SyncHistoryItem {
    id: string;
    source_type: string;
    source_name: string;
    sync_type: string;
    started_at: string;
    completed_at: string | null;
    duration_seconds: number | null;
    status: string;
    items_added: number;
    items_deleted: number;
    items_total: number;
    files_written: number;
    item_unit: string;
    has_details: boolean;
    error_message: string | null;
}

interface SyncStats {
    total_executions: number;
    successful: number;
    failed: number;
    success_rate: number;
    by_source: {
        xtream: { total: number; success: number; failed: number };
        plex: { total: number; success: number; failed: number };
    };
}

export default function SyncHistory() {
    const [history, setHistory] = useState<SyncHistoryItem[]>([]);
    const [stats, setStats] = useState<SyncStats | null>(null);
    const [loading, setLoading] = useState(true);
    const [sourceFilter, setSourceFilter] = useState<string>('');
    const [typeFilter, setTypeFilter] = useState<string>('');

    useEffect(() => {
        fetchHistory();
        fetchStats();
    }, [sourceFilter, typeFilter]);

    const fetchHistory = async () => {
        try {
            let url = '/sync-history/?limit=100';
            if (sourceFilter) url += `&source_type=${sourceFilter}`;
            if (typeFilter) url += `&sync_type=${typeFilter}`;

            const response = await api.get<SyncHistoryItem[]>(url);
            setHistory(response.data);
        } catch (error) {
            console.error('Error fetching sync history:', error);
        } finally {
            setLoading(false);
        }
    };

    const fetchStats = async () => {
        try {
            const response = await api.get<SyncStats>('/sync-history/stats');
            setStats(response.data);
        } catch (error) {
            console.error('Error fetching sync stats:', error);
        }
    };

    const formatDuration = (seconds: number | null) => {
        if (seconds === null) return '-';
        const minutes = Math.floor(seconds / 60);
        const secs = seconds % 60;
        if (minutes > 0) {
            return `${minutes}m ${secs}s`;
        }
        return `${secs}s`;
    };

    const getStatusBadge = (status: string) => {
        const colors: Record<string, string> = {
            success: 'bg-green-500/10 text-green-500 border-green-500/20',
            failed: 'bg-red-500/10 text-red-500 border-red-500/20',
            running: 'bg-blue-500/10 text-blue-500 border-blue-500/20',
            cancelled: 'bg-gray-500/10 text-gray-500 border-gray-500/20',
        };

        const labels: Record<string, string> = {
            success: 'Success',
            failed: 'Failed',
            running: 'Running',
            cancelled: 'Cancelled',
        };

        const icons: Record<string, JSX.Element> = {
            success: <CheckCircle className="w-4 h-4" />,
            failed: <XCircle className="w-4 h-4" />,
            running: <Loader2 className="w-4 h-4 animate-spin" />,
            cancelled: <XCircle className="w-4 h-4" />,
        };

        return (
            <div className={`inline-flex items-center gap-2 px-2 py-1 rounded-md border ${colors[status] || colors.cancelled}`}>
                {icons[status] || icons.cancelled}
                <span className="text-xs font-medium">{labels[status] || status}</span>
            </div>
        );
    };

    const getSourceIcon = (sourceType: string) => {
        switch (sourceType) {
            case 'xtream':
                return <Tv className="w-4 h-4" />;
            case 'plex':
                return <Server className="w-4 h-4" />;
            case 'm3u':
                return <Radio className="w-4 h-4" />;
            default:
                return null;
        }
    };

    const getSourceBadge = (sourceType: string) => {
        const colors: Record<string, string> = {
            xtream: 'bg-blue-500/10 text-blue-500 border-blue-500/20',
            plex: 'bg-orange-500/10 text-orange-500 border-orange-500/20',
            m3u: 'bg-purple-500/10 text-purple-500 border-purple-500/20',
        };

        return (
            <div className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-md border text-xs ${colors[sourceType] || 'bg-gray-500/10 text-gray-500 border-gray-500/20'}`}>
                {getSourceIcon(sourceType)}
                <span className="font-medium capitalize">{sourceType}</span>
            </div>
        );
    };

    const getTypeBadge = (syncType: string) => {
        const colors: Record<string, string> = {
            movies: 'bg-cyan-500/10 text-cyan-500 border-cyan-500/20',
            series: 'bg-pink-500/10 text-pink-500 border-pink-500/20',
        };

        return (
            <span className={`px-2 py-0.5 rounded-md border text-xs font-medium capitalize ${colors[syncType] || 'bg-gray-500/10'}`}>
                {syncType}
            </span>
        );
    };

    if (loading) {
        return <div className="flex items-center justify-center h-full">Loading...</div>;
    }

    return (
        <div className="space-y-8">
            <div>
                <h2 className="text-3xl font-bold tracking-tight">Sync History</h2>
                <p className="text-muted-foreground">View execution history for all synchronization tasks</p>
            </div>

            {/* Stats Cards */}
            {stats && (
                <div className="grid gap-4 md:grid-cols-4">
                    <Card>
                        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                            <CardTitle className="text-sm font-medium">Total Syncs</CardTitle>
                            <History className="h-4 w-4 text-muted-foreground" />
                        </CardHeader>
                        <CardContent>
                            <div className="text-2xl font-bold">{stats.total_executions}</div>
                        </CardContent>
                    </Card>
                    <Card>
                        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                            <CardTitle className="text-sm font-medium">Successful</CardTitle>
                            <CheckCircle className="h-4 w-4 text-green-500" />
                        </CardHeader>
                        <CardContent>
                            <div className="text-2xl font-bold text-green-500">{stats.successful}</div>
                        </CardContent>
                    </Card>
                    <Card>
                        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                            <CardTitle className="text-sm font-medium">Failed</CardTitle>
                            <XCircle className="h-4 w-4 text-red-500" />
                        </CardHeader>
                        <CardContent>
                            <div className="text-2xl font-bold text-red-500">{stats.failed}</div>
                        </CardContent>
                    </Card>
                    <Card>
                        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                            <CardTitle className="text-sm font-medium">Success Rate</CardTitle>
                        </CardHeader>
                        <CardContent>
                            <div className="text-2xl font-bold">{stats.success_rate}%</div>
                        </CardContent>
                    </Card>
                </div>
            )}

            {/* Filters */}
            <Card>
                <CardHeader>
                    <CardTitle className="flex items-center gap-2">
                        <Filter className="w-5 h-5" />
                        Filters
                    </CardTitle>
                </CardHeader>
                <CardContent>
                    <div className="flex gap-4 flex-wrap">
                        <div className="space-y-2">
                            <label className="text-sm font-medium">Source Type</label>
                            <select
                                value={sourceFilter}
                                onChange={(e) => setSourceFilter(e.target.value)}
                                className="border rounded-md px-3 py-2 text-sm min-w-[150px]"
                            >
                                <option value="">All Sources</option>
                                <option value="xtream">Xtream</option>
                                <option value="plex">Plex</option>
                            </select>
                        </div>
                        <div className="space-y-2">
                            <label className="text-sm font-medium">Sync Type</label>
                            <select
                                value={typeFilter}
                                onChange={(e) => setTypeFilter(e.target.value)}
                                className="border rounded-md px-3 py-2 text-sm min-w-[150px]"
                            >
                                <option value="">All Types</option>
                                <option value="movies">Movies</option>
                                <option value="series">Series</option>
                            </select>
                        </div>
                    </div>
                </CardContent>
            </Card>

            {/* History Table */}
            <Card>
                <CardHeader>
                    <CardTitle>Execution History</CardTitle>
                </CardHeader>
                <CardContent>
                    {history.length === 0 ? (
                        <div className="text-center text-muted-foreground py-8">
                            No sync history yet
                        </div>
                    ) : (
                        <div className="border rounded-md overflow-x-auto">
                            <table className="w-full text-sm">
                                <thead className="bg-muted/50 text-muted-foreground">
                                    <tr>
                                        <th className="p-3 text-left">Source</th>
                                        <th className="p-3 text-left">Type</th>
                                        <th className="p-3 text-left">Started</th>
                                        <th className="p-3 text-left">Completed</th>
                                        <th className="p-3 text-left">Duration</th>
                                        <th className="p-3 text-left">Status</th>
                                        <th className="p-3 text-right">Changes</th>
                                    </tr>
                                </thead>
                                <tbody className="divide-y">
                                    {history.map(item => (
                                        <tr key={item.id} className="hover:bg-muted/50">
                                            <td className="p-3">
                                                <div className="flex flex-col gap-1">
                                                    {getSourceBadge(item.source_type)}
                                                    <span className="text-xs text-muted-foreground">{item.source_name}</span>
                                                </div>
                                            </td>
                                            <td className="p-3">
                                                {getTypeBadge(item.sync_type)}
                                            </td>
                                            <td className="p-3 whitespace-nowrap">
                                                {formatDateTime(item.started_at)}
                                            </td>
                                            <td className="p-3 whitespace-nowrap">
                                                {item.completed_at ? formatDateTime(item.completed_at) : '-'}
                                            </td>
                                            <td className="p-3">
                                                {formatDuration(item.duration_seconds)}
                                            </td>
                                            <td className="p-3">
                                                {getStatusBadge(item.status)}
                                            </td>
                                            <td className="p-3 text-right font-medium">
                                                {item.has_details ? (
                                                    <div
                                                        className="flex flex-col items-end"
                                                        title={`${item.items_added} ${item.item_unit} added or updated, ${item.items_deleted} deleted - ${item.files_written} STRM files written to disk`}
                                                    >
                                                        <span>
                                                            <span className="text-green-600">+{item.items_added}</span>
                                                            <span className="text-muted-foreground"> / </span>
                                                            <span className="text-red-600">-{item.items_deleted}</span>
                                                        </span>
                                                        <span className="text-xs font-normal text-muted-foreground">
                                                            {item.item_unit} - {item.files_written} strm
                                                        </span>
                                                    </div>
                                                ) : item.items_total > 0 ? (
                                                    <span title="Older run: additions and deletions were not stored separately">
                                                        {item.items_total}
                                                    </span>
                                                ) : '-'}
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    )}
                </CardContent>
            </Card>
        </div>
    );
}
