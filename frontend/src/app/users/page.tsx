"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Users,
  UserCheck,
  UserX,
  Shield,
  ShieldAlert,
  Search,
  RefreshCw,
  AlertTriangle,
  Mail,
  Calendar,
  CheckCircle,
  XCircle
} from "lucide-react";
import { api, authStorage, User as UserType } from "@/lib/api";

export default function UserManagementPage() {
  const router = useRouter();
  
  const [users, setUsers] = useState<UserType[]>([]);
  const [filteredUsers, setFilteredUsers] = useState<UserType[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [actionLoadingId, setActionLoadingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const fetchUsers = async () => {
    try {
      setLoading(true);
      setError(null);
      const userList = await api.listUsers();
      setUsers(userList);
      setFilteredUsers(userList);
    } catch (err: any) {
      setError(err.message || "Failed to load user directory.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    const token = authStorage.getToken();
    const user = authStorage.getUser();
    
    if (!token) {
      router.push("/login");
      return;
    }

    if (!user || user.role !== "admin") {
      router.push("/knowledge-bases");
      return;
    }

    fetchUsers();
  }, [router]);

  // Handle local searching
  useEffect(() => {
    const query = searchQuery.toLowerCase().trim();
    if (!query) {
      setFilteredUsers(users);
      return;
    }

    const filtered = users.filter((u) => {
      const name = (u.full_name || "").toLowerCase();
      const email = u.email.toLowerCase();
      return name.includes(query) || email.includes(query);
    });
    setFilteredUsers(filtered);
  }, [searchQuery, users]);

  const handleToggleStatus = async (userId: string, currentStatus: boolean, userEmail: string) => {
    const targetStatus = !currentStatus;
    const msg = `Are you sure you want to ${targetStatus ? "activate" : "deactivate"} the account for "${userEmail}"?`;
    if (!confirm(msg)) return;

    try {
      setActionLoadingId(userId);
      setError(null);
      setSuccess(null);
      
      const updatedUser = await api.updateUser(userId, { is_active: targetStatus });
      
      // Update local state
      setUsers((prev) => prev.map((u) => (u.id === userId ? updatedUser : u)));
      setSuccess(`Account status updated for ${userEmail}`);
      setTimeout(() => setSuccess(null), 3000);
    } catch (err: any) {
      setError(err.message || "Failed to update user status.");
    } finally {
      setActionLoadingId(null);
    }
  };

  const handleToggleRole = async (userId: string, currentRole: string, userEmail: string) => {
    const targetRole = currentRole === "admin" ? "user" : "admin";
    const msg = `Are you sure you want to change the role of "${userEmail}" to ${targetRole === "admin" ? "Administrator" : "Standard User"}?`;
    if (!confirm(msg)) return;

    try {
      setActionLoadingId(userId);
      setError(null);
      setSuccess(null);
      
      const updatedUser = await api.updateUser(userId, { role: targetRole });
      
      // Update local state
      setUsers((prev) => prev.map((u) => (u.id === userId ? updatedUser : u)));
      
      // If updating current logged in user's role (self-demotion)
      const currentUser = authStorage.getUser();
      if (currentUser && currentUser.id === userId) {
        authStorage.setUser(updatedUser);
        if (targetRole !== "admin") {
          // Redirect immediately if no longer admin
          router.push("/knowledge-bases");
          return;
        }
      }
      
      setSuccess(`Role updated to ${targetRole} for ${userEmail}`);
      setTimeout(() => setSuccess(null), 3000);
    } catch (err: any) {
      setError(err.message || "Failed to update user role.");
    } finally {
      setActionLoadingId(null);
    }
  };

  const formatDate = (dateStr: string) => {
    try {
      return new Date(dateStr).toLocaleDateString(undefined, {
        year: "numeric",
        month: "short",
        day: "numeric"
      });
    } catch (_) {
      return dateStr;
    }
  };

  if (loading && users.length === 0) {
    return (
      <div className="flex items-center justify-center min-h-[50vh] text-foreground">
        <div className="text-center space-y-2">
          <div className="w-8 h-8 border-4 border-primary border-t-transparent rounded-full animate-spin mx-auto" />
          <p className="text-sm text-text-muted">Loading user accounts...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-8 animate-fade-in">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-extrabold text-foreground tracking-tight">User Management</h1>
          <p className="text-text-muted mt-1">Audit permissions, promote roles, and manage system access status</p>
        </div>
        <button
          onClick={fetchUsers}
          className="flex items-center space-x-2 px-4 py-2.5 bg-background border border-card-border hover:bg-card-border/20 text-foreground rounded-2xl font-semibold text-sm transition-all duration-200 cursor-pointer shrink-0"
        >
          <RefreshCw className="w-4 h-4" />
          <span>Refresh List</span>
        </button>
      </div>

      {/* Notifications */}
      {success && (
        <div className="flex items-center space-x-2 p-4 rounded-2xl bg-green-500/10 border border-green-500/20 text-green-400 text-sm">
          <CheckCircle className="w-5 h-5 text-green-400 shrink-0" />
          <span>{success}</span>
        </div>
      )}

      {error && (
        <div className="flex items-start space-x-2 p-4 rounded-2xl bg-red-500/10 border border-red-500/20 text-red-400 text-sm">
          <AlertTriangle className="w-5 h-5 shrink-0 mt-0.5" />
          <span>{error}</span>
        </div>
      )}

      {/* Search Bar */}
      <div className="glass p-4 rounded-3xl border border-card-border flex items-center space-x-3">
        <Search className="w-5 h-5 text-text-muted" />
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="Search users by name or email address..."
          className="bg-transparent border-0 text-foreground placeholder-text-muted text-sm w-full focus:outline-none"
        />
      </div>

      {/* User Directory Table */}
      <div className="glass border border-card-border rounded-3xl p-6 overflow-hidden">
        {filteredUsers.length === 0 ? (
          <div className="py-16 text-center text-text-muted">
            <Users className="w-12 h-12 mx-auto mb-2 opacity-30" />
            <p className="text-sm">No user accounts found matching your query.</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm border-collapse">
              <thead>
                <tr className="border-b border-card-border/50 text-text-muted font-semibold">
                  <th className="py-4 pr-4">User Details</th>
                  <th className="py-4 px-4">Contact</th>
                  <th className="py-4 px-4">Role</th>
                  <th className="py-4 px-4">Status</th>
                  <th className="py-4 px-4">Joined Date</th>
                  <th className="py-4 pl-4 text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {filteredUsers.map((user) => {
                  const isLoading = actionLoadingId === user.id;
                  
                  return (
                    <tr
                      key={user.id}
                      className="border-b border-card-border/30 text-foreground hover:bg-card-border/10 transition-colors"
                    >
                      {/* Name Details */}
                      <td className="py-4 pr-4 font-medium">
                        <div className="flex items-center space-x-3">
                          <div className="w-10 h-10 rounded-full bg-primary/10 border border-primary/20 flex items-center justify-center font-bold text-primary">
                            {(user.full_name || user.email).slice(0, 2).toUpperCase()}
                          </div>
                          <div>
                            <span className="block font-bold text-foreground leading-tight">
                              {user.full_name || "No Name Configured"}
                            </span>
                            <span className="text-xs text-text-muted">ID: {user.id.slice(0, 8)}...</span>
                          </div>
                        </div>
                      </td>

                      {/* Email Address */}
                      <td className="py-4 px-4 font-mono text-xs">
                        <div className="flex items-center space-x-2 text-text-muted">
                          <Mail className="w-3.5 h-3.5" />
                          <span>{user.email}</span>
                        </div>
                      </td>

                      {/* Role Badge */}
                      <td className="py-4 px-4">
                        {user.role === "admin" ? (
                          <span className="inline-flex items-center space-x-1 text-xs text-primary font-bold py-1 px-2.5 bg-primary/10 rounded-full border border-primary/20">
                            <ShieldAlert className="w-3.5 h-3.5" />
                            <span>Administrator</span>
                          </span>
                        ) : (
                          <span className="inline-flex items-center space-x-1 text-xs text-text-muted font-semibold py-1 px-2.5 bg-card-border/30 rounded-full border border-card-border/40">
                            <Shield className="w-3.5 h-3.5" />
                            <span>Standard User</span>
                          </span>
                        )}
                      </td>

                      {/* Active Status Badge */}
                      <td className="py-4 px-4">
                        {user.is_active ? (
                          <span className="inline-flex items-center space-x-1 text-xs text-emerald-400 font-semibold py-1 px-2.5 bg-emerald-500/10 rounded-full border border-emerald-500/20">
                            <CheckCircle className="w-3.5 h-3.5" />
                            <span>Active</span>
                          </span>
                        ) : (
                          <span className="inline-flex items-center space-x-1 text-xs text-red-400 font-semibold py-1 px-2.5 bg-red-500/10 rounded-full border border-red-500/20">
                            <XCircle className="w-3.5 h-3.5" />
                            <span>Suspended</span>
                          </span>
                        )}
                      </td>

                      {/* Registration Date */}
                      <td className="py-4 px-4 text-text-muted">
                        <div className="flex items-center space-x-1.5 text-xs">
                          <Calendar className="w-3.5 h-3.5" />
                          <span>{formatDate(user.created_at)}</span>
                        </div>
                      </td>

                      {/* Role and Status Control Actions */}
                      <td className="py-4 pl-4 text-right">
                        <div className="flex justify-end items-center space-x-2">
                          {isLoading ? (
                            <div className="w-5 h-5 border-2 border-primary border-t-transparent rounded-full animate-spin mr-3" />
                          ) : (
                            <>
                              {/* Toggle Role Button */}
                              <button
                                onClick={() => handleToggleRole(user.id, user.role, user.email)}
                                className={`px-3 py-1.5 rounded-xl text-xs font-semibold border transition-all duration-200 cursor-pointer ${
                                  user.role === "admin"
                                    ? "bg-primary/5 border-primary/20 text-primary hover:bg-primary/20"
                                    : "bg-background border-card-border text-text-muted hover:text-foreground hover:border-card-border/60"
                                }`}
                                title={user.role === "admin" ? "Demote to Standard User" : "Promote to Administrator"}
                              >
                                {user.role === "admin" ? "Demote" : "Make Admin"}
                              </button>

                              {/* Toggle Active Status Button */}
                              <button
                                onClick={() => handleToggleStatus(user.id, user.is_active, user.email)}
                                className={`p-1.5 rounded-xl border transition-all duration-200 cursor-pointer ${
                                  user.is_active
                                    ? "border-red-500/20 text-red-400 hover:bg-red-500/15"
                                    : "border-emerald-500/20 text-emerald-400 hover:bg-emerald-500/15"
                                }`}
                                title={user.is_active ? "Suspend User" : "Activate User"}
                              >
                                {user.is_active ? (
                                  <UserX className="w-4 h-4" />
                                ) : (
                                  <UserCheck className="w-4 h-4" />
                                )}
                              </button>
                            </>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
