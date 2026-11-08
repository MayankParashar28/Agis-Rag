"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { RefreshCw, Search, UserCheck, Users, UserX } from "lucide-react";
import { api, authStorage, User as UserType } from "@/lib/api";
import { errorMessage, useApi, useRequireAuth } from "@/lib/hooks";
import { Alert, Card, CardHeader, EmptyState, PageHeader, SkeletonRows, Spinner, cx } from "@/components/ui";

export default function UserManagementPage() {
  const allowed = useRequireAuth({ adminOnly: true });
  const router = useRouter();
  const usersQuery = useApi<UserType[]>(allowed ? "/auth/users" : null, api.listUsers);
  const users = usersQuery.data ?? [];
  const [search, setSearch] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ tone: "success" | "danger"; text: string } | null>(null);

  const q = search.toLowerCase().trim();
  const filtered = q ? users.filter((u) => (u.full_name || "").toLowerCase().includes(q) || u.email.toLowerCase().includes(q)) : users;

  const update = async (user: UserType, patch: { role?: string; is_active?: boolean }, confirmText: string, doneText: string) => {
    if (!confirm(confirmText)) return;
    setBusyId(user.id);
    setNotice(null);
    try {
      const updated = await api.updateUser(user.id, patch);
      usersQuery.setData((prev) => (prev ?? []).map((u) => (u.id === user.id ? updated : u)));
      const me = authStorage.getUser();
      if (me && me.id === user.id) {
        authStorage.setUser(updated);
        if (updated.role !== "admin") {
          router.push("/knowledge-bases");
          return;
        }
      }
      setNotice({ tone: "success", text: doneText });
    } catch (e) {
      setNotice({ tone: "danger", text: errorMessage(e, "Update failed.") });
    } finally {
      setBusyId(null);
    }
  };

  if (!allowed) return null;

  return (
    <div className="space-y-6 animate-fade-in">
      <PageHeader
        eyebrow="Admin"
        title="Users"
        description="Manage roles and access."
        actions={
          <button className="btn btn-secondary" onClick={usersQuery.reload} disabled={usersQuery.refreshing}>
            <RefreshCw className={cx("h-4 w-4", usersQuery.refreshing && "animate-spin")} />Refresh
          </button>
        }
      />
      {notice && <Alert tone={notice.tone} onClose={() => setNotice(null)}>{notice.text}</Alert>}
      {usersQuery.error && <Alert tone="danger">{usersQuery.error}</Alert>}

      <Card className="overflow-hidden">
        <CardHeader
          title={`${users.length} account${users.length === 1 ? "" : "s"}`}
          actions={
            <div className="relative w-64 max-w-full">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
              <input aria-label="Search users" placeholder="Search name or email…" value={search} onChange={(e) => setSearch(e.target.value)} className="input h-8 pl-8 text-[13px]" />
            </div>
          }
        />
        {usersQuery.loading ? (
          <SkeletonRows rows={5} />
        ) : filtered.length === 0 ? (
          <EmptyState icon={Users} title="No users found" />
        ) : (
          <div className="overflow-x-auto">
            <table className="table">
              <thead>
                <tr>
                  <th>User</th>
                  <th>Role</th>
                  <th>Status</th>
                  <th>Joined</th>
                  <th className="text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((u) => (
                  <tr key={u.id}>
                    <td>
                      <div className="flex items-center gap-3">
                        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent-soft text-xs font-semibold text-accent-hover">
                          {(u.full_name || u.email).slice(0, 2).toUpperCase()}
                        </div>
                        <div className="min-w-0">
                          <p className="truncate font-medium">{u.full_name || "—"}</p>
                          <p className="truncate text-xs text-muted-foreground">{u.email}</p>
                        </div>
                      </div>
                    </td>
                    <td><span className={cx("badge", u.role === "admin" ? "badge-accent" : "badge-neutral")}>{u.role === "admin" ? "Admin" : "Member"}</span></td>
                    <td><span className={cx("badge", u.is_active ? "badge-success" : "badge-danger")}>{u.is_active ? "Active" : "Suspended"}</span></td>
                    <td className="whitespace-nowrap text-muted-foreground">{new Date(u.created_at).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" })}</td>
                    <td>
                      <div className="flex items-center justify-end gap-1.5">
                        {busyId === u.id ? (
                          <Spinner className="mr-2 text-muted-foreground" />
                        ) : (
                          <>
                            <button
                              className="btn btn-secondary btn-sm"
                              onClick={() =>
                                update(u, { role: u.role === "admin" ? "user" : "admin" },
                                  `Change ${u.email} to ${u.role === "admin" ? "member" : "admin"}?`,
                                  `${u.email} is now ${u.role === "admin" ? "a member" : "an admin"}.`)
                              }
                            >
                              {u.role === "admin" ? "Make member" : "Make admin"}
                            </button>
                            <button
                              className={cx("icon-btn", u.is_active && "icon-btn-danger")}
                              title={u.is_active ? "Suspend" : "Activate"}
                              aria-label={`${u.is_active ? "Suspend" : "Activate"} ${u.email}`}
                              onClick={() =>
                                update(u, { is_active: !u.is_active },
                                  `${u.is_active ? "Suspend" : "Activate"} ${u.email}?`,
                                  `${u.email} ${u.is_active ? "suspended" : "activated"}.`)
                              }
                            >
                              {u.is_active ? <UserX className="h-4 w-4" /> : <UserCheck className="h-4 w-4" />}
                            </button>
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
