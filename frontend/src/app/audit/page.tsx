"use client";

import { useEffect, useState } from "react";
import { ChevronLeft, ChevronRight, ScrollText, Search } from "lucide-react";
import { api, AuditEntry } from "@/lib/api";
import { errorMessage, useRequireAuth } from "@/lib/hooks";
import { Alert, Card, CardHeader, EmptyState, PageHeader, SkeletonRows, cx } from "@/components/ui";

const PAGE = 50;

const ACTION_LABEL: Record<string, string> = {
  "document.upload": "Uploaded document",
  "document.import_url": "Imported from link",
  "document.delete": "Deleted document",
  "document.reindex": "Re-indexed document",
  "conversation.export": "Exported conversation",
  "kb.create": "Created knowledge base",
  "kb.delete": "Deleted knowledge base",
  "user.update": "Changed user",
  "evaluation.golden_run": "Ran golden set",
};

function describe(e: AuditEntry) {
  const d = e.detail || {};
  const name = (d.filename || d.name || d.kb_name || d.title || d.email) as string | undefined;
  const extras: string[] = [];
  if (d.role) extras.push(`role → ${d.role}`);
  if (typeof d.is_active === "boolean") extras.push(d.is_active ? "active" : "suspended");
  if (d.source_url) extras.push(String(d.source_url));
  if (typeof d.score === "number") extras.push(`score ${(d.score * 100).toFixed(0)}% · ${d.pass ? "pass" : "fail"}`);
  return [name, ...extras].filter(Boolean).join(" · ");
}

export default function AuditPage() {
  const allowed = useRequireAuth({ adminOnly: true });
  const [data, setData] = useState<{ total: number; actions: string[]; items: AuditEntry[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(0);
  const [action, setAction] = useState("");
  const [user, setUser] = useState("");
  const [userDraft, setUserDraft] = useState("");

  useEffect(() => {
    if (!allowed) return;
    let cancelled = false;
    api.getAuditLog({ limit: PAGE, offset: page * PAGE, action: action || undefined, user: user || undefined })
      .then((d) => !cancelled && setData(d))
      .catch((e) => !cancelled && setError(errorMessage(e, "Could not load the audit log.")));
    return () => { cancelled = true; };
  }, [allowed, page, action, user]);

  useEffect(() => {
    const t = setTimeout(() => { setUser(userDraft.trim()); setPage(0); }, 350);
    return () => clearTimeout(t);
  }, [userDraft]);

  if (!allowed) return null;
  const pages = data ? Math.max(1, Math.ceil(data.total / PAGE)) : 1;

  return (
    <div className="space-y-6 animate-fade-in">
      <PageHeader eyebrow="Admin" title="Audit log" description="Who uploaded, deleted, re-indexed or exported what, and when." />
      {error && <Alert tone="danger">{error}</Alert>}
      <Card className="overflow-hidden">
        <CardHeader
          title={data ? `${data.total.toLocaleString()} event${data.total === 1 ? "" : "s"}` : "Events"}
          actions={
            <>
              <select aria-label="Filter by action" value={action} onChange={(e) => { setAction(e.target.value); setPage(0); }} className="input h-8 w-48 text-[13px]">
                <option value="">All actions</option>
                {(data?.actions ?? []).map((a) => <option key={a} value={a}>{ACTION_LABEL[a] ?? a}</option>)}
              </select>
              <div className="relative w-52">
                <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
                <input aria-label="Filter by user" placeholder="Filter by user email…" value={userDraft} onChange={(e) => setUserDraft(e.target.value)} className="input h-8 pl-8 text-[13px]" />
              </div>
            </>
          }
        />
        {!data ? (
          <SkeletonRows rows={8} />
        ) : data.items.length === 0 ? (
          <EmptyState icon={ScrollText} title="No events" description="Actions appear here as people use the app." />
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="table">
                <thead><tr><th>When</th><th>User</th><th>Action</th><th>Details</th></tr></thead>
                <tbody>
                  {data.items.map((e) => (
                    <tr key={e.id}>
                      <td className="whitespace-nowrap text-xs text-muted-foreground">{new Date(e.created_at).toLocaleString()}</td>
                      <td className="text-sm">{e.user_email ?? <span className="text-muted-foreground">system</span>}</td>
                      <td><span className={cx("badge", e.action.includes("delete") ? "badge-danger" : e.action.includes("upload") || e.action.includes("import") || e.action.includes("create") ? "badge-success" : "badge-neutral")}>{ACTION_LABEL[e.action] ?? e.action}</span></td>
                      <td className="max-w-[420px] truncate text-sm" title={describe(e)}>{describe(e) || <span className="text-muted-foreground">{e.target_type} {e.target_id?.slice(0, 8)}</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="flex items-center justify-between border-t border-border px-4 py-2.5 text-xs text-muted-foreground">
              <span>Page {page + 1} of {pages}</span>
              <div className="flex gap-1">
                <button className="icon-btn" onClick={() => setPage((p) => Math.max(0, p - 1))} disabled={page === 0} aria-label="Previous page"><ChevronLeft className="h-4 w-4" /></button>
                <button className="icon-btn" onClick={() => setPage((p) => Math.min(pages - 1, p + 1))} disabled={page >= pages - 1} aria-label="Next page"><ChevronRight className="h-4 w-4" /></button>
              </div>
            </div>
          </>
        )}
      </Card>
    </div>
  );
}
