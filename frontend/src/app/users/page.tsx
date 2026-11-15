"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Gauge, RefreshCw, Search, UserCheck, Users, UserX } from "lucide-react";
import { api, authStorage, UsageOverview, User as UserType } from "@/lib/api";
import { compactNumber } from "@/components/UsageMeter";
import { errorMessage, useApi, useRequireAuth } from "@/lib/hooks";
import { Alert, Card, CardHeader, EmptyState, Modal, PageHeader, SkeletonRows, Spinner, cx } from "@/components/ui";

export default function UserManagementPage() {
  const allowed = useRequireAuth({ adminOnly: true });
  const router = useRouter();
  const usersQuery = useApi<UserType[]>(allowed ? "/auth/users" : null, api.listUsers);
  const users = usersQuery.data ?? [];
  const usageQuery = useApi<UsageOverview>(allowed ? "/auth/usage/today" : null, api.getUsageOverview);
  const [limitsFor, setLimitsFor] = useState<UserType | null>(null);
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
            <table className="table table-stack">
              <thead>
                <tr>
                  <th>User</th>
                  <th>Role</th>
                  <th>Status</th>
                  <th>Today</th>
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
                    <td data-label="Role"><span className={cx("badge", u.role === "admin" ? "badge-accent" : "badge-neutral")}>{u.role === "admin" ? "Admin" : "Member"}</span></td>
                    <td data-label="Status"><span className={cx("badge", u.is_active ? "badge-success" : "badge-danger")}>{u.is_active ? "Active" : "Suspended"}</span></td>
                    <td data-label="Today" className="whitespace-nowrap">
                      <TodayCell usage={usageQuery.data?.users[u.id]} />
                    </td>
                    <td data-label="Joined" className="whitespace-nowrap text-muted-foreground">{new Date(u.created_at).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" })}</td>
                    <td data-label="Actions">
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
                              className="icon-btn"
                              title="Daily limits"
                              aria-label={`Daily limits for ${u.email}`}
                              onClick={() => setLimitsFor(u)}
                            >
                              <Gauge className="h-4 w-4" />
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
      <LimitsModal
        user={limitsFor}
        defaults={usageQuery.data?.defaults}
        onClose={() => setLimitsFor(null)}
        onSaved={(updated) => {
          usersQuery.setData((prev) => (prev ?? []).map((x) => (x.id === updated.id ? updated : x)));
          usageQuery.reload();
          setLimitsFor(null);
          setNotice({ tone: "success", text: `Daily limits saved for ${updated.email}.` });
        }}
      />
    </div>
  );
}

function TodayCell({ usage }: { usage?: UsageOverview["users"][string] }) {
  if (!usage) return <span className="text-muted-foreground">—</span>;
  const over = (usage.question_limit && usage.questions >= usage.question_limit) || (usage.token_limit && usage.tokens >= usage.token_limit);
  return (
    <span className={cx("text-sm tabular-nums", over ? "font-semibold text-danger" : "text-foreground")} title={`${usage.tokens.toLocaleString()} tokens today`}>
      {usage.questions}
      <span className="text-muted-foreground">{usage.question_limit ? ` / ${usage.question_limit}` : " · no limit"}</span>
      <span className="block text-xs text-muted-foreground">{compactNumber(usage.tokens)} tokens</span>
    </span>
  );
}

type LimitMode = "default" | "unlimited" | "custom";

function modeOf(v: number | null | undefined): LimitMode {
  return v == null ? "default" : v === 0 ? "unlimited" : "custom";
}

function LimitsModal({ user, defaults, onClose, onSaved }: {
  user: UserType | null;
  defaults?: UsageOverview["defaults"];
  onClose: () => void;
  onSaved: (u: UserType) => void;
}) {
  return (
    <Modal open={!!user} onClose={onClose} title="Daily limits" description={user?.email}>
      {/* Keyed by user so the form starts from that user's saved values. */}
      {user && <LimitsForm key={user.id} user={user} defaults={defaults} onClose={onClose} onSaved={onSaved} />}
    </Modal>
  );
}

function LimitsForm({ user, defaults, onClose, onSaved }: {
  user: UserType;
  defaults?: UsageOverview["defaults"];
  onClose: () => void;
  onSaved: (u: UserType) => void;
}) {
  const [qMode, setQMode] = useState<LimitMode>(modeOf(user.daily_question_limit));
  const [tMode, setTMode] = useState<LimitMode>(modeOf(user.daily_token_limit));
  const [q, setQ] = useState(String(user.daily_question_limit || defaults?.question_limit || 100));
  const [t, setT] = useState(String(user.daily_token_limit || defaults?.token_limit || 300000));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const value = (mode: LimitMode, raw: string) => (mode === "default" ? null : mode === "unlimited" ? 0 : Math.max(1, Math.floor(Number(raw) || 0)));
  const invalid = (qMode === "custom" && !(Number(q) >= 1)) || (tMode === "custom" && !(Number(t) >= 1));

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    if (invalid) return;
    setSaving(true);
    setError(null);
    try {
      onSaved(await api.updateUser(user.id, { daily_question_limit: value(qMode, q), daily_token_limit: value(tMode, t) }));
    } catch (err) {
      setError(errorMessage(err, "Could not save the limits."));
    } finally {
      setSaving(false);
    }
  };

  const adminDefault = user.role === "admin" && defaults?.admins_unlimited;
  const row = (label: string, mode: LimitMode, setMode: (m: LimitMode) => void, raw: string, setRaw: (v: string) => void, def?: number, unit = "") => (
    <fieldset className="space-y-2">
      <legend className="label">{label}</legend>
      <div className="flex flex-wrap gap-x-4 gap-y-1.5 text-sm">
        {(["default", "custom", "unlimited"] as LimitMode[]).map((m) => (
          <label key={m} className="flex cursor-pointer items-center gap-1.5">
            <input type="radio" name={label} checked={mode === m} onChange={() => setMode(m)} className="accent-[#a8801f]" />
            {m === "default" ? `Default (${adminDefault ? "no limit for admins" : def ? def.toLocaleString() + unit : "no limit"})` : m === "custom" ? "Custom" : "No limit"}
          </label>
        ))}
      </div>
      {mode === "custom" && (
        <input
          type="number"
          min={1}
          inputMode="numeric"
          aria-label={`${label} per day`}
          value={raw}
          onChange={(e) => setRaw(e.target.value)}
          className="input w-40"
        />
      )}
    </fieldset>
  );

  return (
    <form onSubmit={save} className="space-y-5">
      {error && <Alert tone="danger">{error}</Alert>}
      {row("Questions per day", qMode, setQMode, q, setQ, defaults?.question_limit)}
      {row("AI tokens per day", tMode, setTMode, t, setT, defaults?.token_limit)}
      <p className="text-xs text-muted-foreground">Limits reset at midnight UTC. A question that is already running always finishes.</p>
      <div className="flex justify-end gap-2">
        <button type="button" className="btn btn-ghost" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary" disabled={saving || invalid}>{saving && <Spinner />}Save limits</button>
      </div>
    </form>
  );
}

