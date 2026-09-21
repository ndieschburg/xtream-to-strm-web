import { useEffect, useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Plus, Trash2, Save, X, Server, Loader2, KeyRound } from 'lucide-react';
import { useToast } from "@/components/ui/toast";
import api from '@/lib/api';

interface PlexAccount {
    id: number;
    name: string;
    username: string;
    output_base_dir: string;
    is_active: boolean;
}

interface PlexAccountForm {
    name: string;
    username: string;
    password: string;
    output_base_dir: string;
}

interface TokenRefreshResponse {
    success: boolean;
    message: string;
    servers_refreshed: number;
    unreachable: string[];
}

export default function PlexAccounts() {
    const [accounts, setAccounts] = useState<PlexAccount[]>([]);
    const [loading, setLoading] = useState(false);
    const [isAdding, setIsAdding] = useState(false);
    const [accountToDelete, setAccountToDelete] = useState<number | null>(null);
    const [loginError, setLoginError] = useState<string | null>(null);
    const [tokenAccount, setTokenAccount] = useState<PlexAccount | null>(null);
    const [tokenForm, setTokenForm] = useState({ password: '', code: '' });
    const [tokenError, setTokenError] = useState<string | null>(null);
    const [tokenLoading, setTokenLoading] = useState(false);
    const { toast } = useToast();
    const [formData, setFormData] = useState<PlexAccountForm>({
        name: '',
        username: '',
        password: '',
        output_base_dir: '/output/plex'
    });

    const fetchData = async () => {
        try {
            const res = await api.get<PlexAccount[]>('/plex/accounts');
            setAccounts(res.data);
        } catch (error) {
            console.error("Failed to fetch Plex accounts", error);
        }
    };

    useEffect(() => {
        fetchData();
    }, []);

    const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        const { name, value } = e.target;
        setFormData(prev => ({
            ...prev,
            [name]: value
        }));
        setLoginError(null);
    };

    const startAdd = () => {
        setFormData({
            name: '',
            username: '',
            password: '',
            output_base_dir: '/output/plex'
        });
        setIsAdding(true);
        setLoginError(null);
    };

    const cancelAdd = () => {
        setIsAdding(false);
        setLoginError(null);
        setFormData({
            name: '',
            username: '',
            password: '',
            output_base_dir: '/output/plex'
        });
    };

    const handleSave = async () => {
        setLoading(true);
        setLoginError(null);
        try {
            await api.post('/plex/accounts', formData);
            await fetchData();
            cancelAdd();
        } catch (error: any) {
            console.error("Failed to create Plex account", error);
            const message = error.response?.data?.detail || "Failed to login to Plex.tv";
            setLoginError(message);
        } finally {
            setLoading(false);
        }
    };

    const startTokenRefresh = (account: PlexAccount) => {
        setTokenAccount(account);
        setTokenForm({ password: '', code: '' });
        setTokenError(null);
    };

    const closeTokenRefresh = () => {
        setTokenAccount(null);
        setTokenForm({ password: '', code: '' });
        setTokenError(null);
    };

    /**
     * Renew the stored Plex.tv token of an existing account
     *
     * @description Plex.tv revokes tokens on a password change or when the
     * device is removed from the authorized list. Renewing in place keeps the
     * servers, libraries, caches and schedules that deleting the account would
     * destroy. The backend also re-syncs the server URIs, since a stale token
     * is exactly what blocks that refresh.
     */
    const handleTokenRefresh = async () => {
        if (!tokenAccount) return;

        setTokenLoading(true);
        setTokenError(null);
        try {
            const res = await api.put<TokenRefreshResponse>(
                `/plex/accounts/${tokenAccount.id}/token`,
                { password: tokenForm.password, code: tokenForm.code || null }
            );

            if (res.data.unreachable?.length) {
                toast.warning(res.data.message);
            } else {
                toast.success(res.data.message);
            }
            closeTokenRefresh();
            await fetchData();
        } catch (error: any) {
            console.error("Failed to renew Plex token", error);
            const message = error.response?.data?.detail || "Failed to renew the Plex.tv token";
            setTokenError(message);
        } finally {
            setTokenLoading(false);
        }
    };

    const confirmDelete = (id: number) => {
        setAccountToDelete(id);
    };

    const handleDelete = async () => {
        if (!accountToDelete) return;

        setLoading(true);
        try {
            await api.delete(`/plex/accounts/${accountToDelete}`);
            await fetchData();
            setAccountToDelete(null);
        } catch (error) {
            console.error("Failed to delete Plex account", error);
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="space-y-8">
            <div>
                <h2 className="text-3xl font-bold tracking-tight">Plex Accounts</h2>
                <p className="text-muted-foreground">Connect your Plex.tv account to sync media libraries.</p>
            </div>

            {/* Account Management */}
            <Card>
                <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-4">
                    <CardTitle className="flex items-center gap-2">
                        <Server className="w-5 h-5" />
                        Plex.tv Accounts
                    </CardTitle>
                    <Button onClick={startAdd} disabled={isAdding || loading} size="sm">
                        <Plus className="w-4 h-4 mr-2" />
                        Add Account
                    </Button>
                </CardHeader>
                <CardContent>
                    <div className="border rounded-md">
                        <table className="w-full text-sm">
                            <thead className="bg-muted/50 text-muted-foreground">
                                <tr>
                                    <th className="p-3 text-left">Account Name</th>
                                    <th className="p-3 text-left">Plex Username</th>
                                    <th className="p-3 text-left">Output Directory</th>
                                    <th className="p-3 text-right">Actions</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y">
                                {isAdding && (
                                    <tr className="bg-accent/50">
                                        <td className="p-2">
                                            <Input
                                                name="name"
                                                value={formData.name}
                                                onChange={handleInputChange}
                                                placeholder="Account name"
                                                className="h-8"
                                            />
                                        </td>
                                        <td className="p-2 space-y-1">
                                            <Input
                                                name="username"
                                                value={formData.username}
                                                onChange={handleInputChange}
                                                placeholder="Plex email/username"
                                                className="h-8"
                                            />
                                            <Input
                                                name="password"
                                                type="password"
                                                value={formData.password}
                                                onChange={handleInputChange}
                                                placeholder="Plex password"
                                                className="h-8"
                                            />
                                            {loginError && (
                                                <p className="text-xs text-red-500">{loginError}</p>
                                            )}
                                        </td>
                                        <td className="p-2">
                                            <Input
                                                name="output_base_dir"
                                                value={formData.output_base_dir}
                                                onChange={handleInputChange}
                                                placeholder="/output/plex"
                                                className="h-8"
                                            />
                                        </td>
                                        <td className="p-2">
                                            <div className="flex gap-2 justify-end">
                                                <Button onClick={handleSave} disabled={loading} size="sm" variant="default">
                                                    {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
                                                </Button>
                                                <Button onClick={cancelAdd} disabled={loading} size="sm" variant="outline">
                                                    <X className="w-4 h-4" />
                                                </Button>
                                            </div>
                                        </td>
                                    </tr>
                                )}
                                {accounts.map(account => (
                                    <tr key={account.id} className="hover:bg-muted/50 transition-colors">
                                        <td className="p-3">
                                            <div className="font-bold">{account.name}</div>
                                        </td>
                                        <td className="p-3 text-muted-foreground">
                                            {account.username}
                                        </td>
                                        <td className="p-3 text-xs text-muted-foreground">
                                            {account.output_base_dir}
                                        </td>
                                        <td className="p-3">
                                            <div className="flex gap-2 justify-end">
                                                <Button
                                                    onClick={() => startTokenRefresh(account)}
                                                    disabled={loading || isAdding}
                                                    size="sm"
                                                    variant="outline"
                                                    title="Renew Plex.tv token"
                                                >
                                                    <KeyRound className="w-4 h-4" />
                                                </Button>
                                                <Button
                                                    onClick={() => confirmDelete(account.id)}
                                                    disabled={loading || isAdding}
                                                    size="sm"
                                                    variant="destructive"
                                                >
                                                    <Trash2 className="w-4 h-4" />
                                                </Button>
                                            </div>
                                        </td>
                                    </tr>
                                ))}
                                {accounts.length === 0 && !isAdding && (
                                    <tr>
                                        <td colSpan={4} className="p-8 text-center text-muted-foreground">
                                            No Plex accounts configured. Click "Add Account" to connect your Plex.tv account.
                                        </td>
                                    </tr>
                                )}
                            </tbody>
                        </table>
                    </div>
                </CardContent>
            </Card>

            {/* Info Card */}
            <Card className="border-blue-500/50 bg-blue-500/5">
                <CardContent className="pt-6">
                    <div className="flex items-start gap-4">
                        <Server className="w-8 h-8 text-blue-500 flex-shrink-0" />
                        <div>
                            <h3 className="font-semibold text-blue-500">How it works</h3>
                            <p className="text-sm text-muted-foreground mt-1">
                                1. Add your Plex.tv account credentials above.<br/>
                                2. Go to <strong>Servers</strong> to view and select your Plex servers.<br/>
                                3. Go to <strong>Library Selection</strong> to choose which libraries to sync.<br/>
                                4. STRM and NFO files will be generated in the output directory.
                            </p>
                        </div>
                    </div>
                </CardContent>
            </Card>

            {/* Token Renewal Dialog */}
            <Dialog
                isOpen={!!tokenAccount}
                onClose={closeTokenRefresh}
                title="Renew Plex.tv Token"
            >
                <div className="space-y-4">
                    <p className="text-sm text-muted-foreground">
                        Re-authenticate <strong>{tokenAccount?.username}</strong> to store a fresh
                        token. Your servers, libraries and schedules are kept.
                    </p>
                    <div className="space-y-2">
                        <Input
                            name="password"
                            type="password"
                            value={tokenForm.password}
                            onChange={(e) => {
                                setTokenForm(prev => ({ ...prev, password: e.target.value }));
                                setTokenError(null);
                            }}
                            placeholder="Plex.tv password"
                            autoFocus
                        />
                        <Input
                            name="code"
                            value={tokenForm.code}
                            onChange={(e) => {
                                setTokenForm(prev => ({ ...prev, code: e.target.value }));
                                setTokenError(null);
                            }}
                            placeholder="Two-factor code (leave empty if unused)"
                        />
                    </div>
                    {tokenError && (
                        <p className="text-xs text-red-500">{tokenError}</p>
                    )}
                    <div className="flex justify-end gap-2">
                        <Button variant="outline" onClick={closeTokenRefresh} disabled={tokenLoading}>
                            Cancel
                        </Button>
                        <Button
                            onClick={handleTokenRefresh}
                            disabled={tokenLoading || !tokenForm.password}
                        >
                            {tokenLoading ? (
                                <Loader2 className="w-4 h-4 animate-spin mr-2" />
                            ) : (
                                <KeyRound className="w-4 h-4 mr-2" />
                            )}
                            Renew Token
                        </Button>
                    </div>
                </div>
            </Dialog>

            {/* Delete Confirmation Dialog */}
            <Dialog
                isOpen={!!accountToDelete}
                onClose={() => setAccountToDelete(null)}
                title="Delete Plex Account"
            >
                <div className="space-y-4">
                    <p>Are you sure you want to delete this Plex account? This will also remove all associated servers and libraries.</p>
                    <div className="flex justify-end gap-2">
                        <Button variant="outline" onClick={() => setAccountToDelete(null)}>
                            Cancel
                        </Button>
                        <Button variant="destructive" onClick={handleDelete} disabled={loading}>
                            Delete
                        </Button>
                    </div>
                </div>
            </Dialog>
        </div>
    );
}
