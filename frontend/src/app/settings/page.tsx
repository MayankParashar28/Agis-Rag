"use client";

import { useState } from "react";
import { Database, Globe, HardDrive, Layers, Search, ServerCog, Sparkles, User as UserIcon } from "lucide-react";
import { api, authStorage, KnowledgeBase } from "@/lib/api";
import { errorMessage, useApi, useCurrentUser, useRequireAuth } from "@/lib/hooks";
import { Alert, Card, CardHeader, PageHeader, Skeleton, Spinner, StatCard, cx } from "@/components/ui";

interface ConfigStatus {
  postgres_connected: boolean;
  redis_connected: boolean;
  redis_pending_documents?: number | null;
  qdrant_connected: boolean;
  qdrant_collections?: number | null;
  openai_configured: boolean;
  llamaparse_configured: boolean;
  tavily_configured: boolean;
  gemini_configured: boolean;
  gemini_model: string | null;
  openai_model?: string | null;
}

function ServiceRow({
  icon: Icon, name, purpose, state, detail,
}: {
  icon: React.ComponentType<{ className?: string }>;
  name: string;
  purpose: string;
  state: "ok" | "off" | "down" | "fallback";
  detail?: string;
}) {
  const badge = {
    ok: { cls: "badge-success", text: "Connected" },
    down: { cls: "badge-danger", text: "Unreachable" },
    off: { cls: "badge-neutral", text: "Not configured" },
    fallback: { cls: "badge-warning", text: "Using fallback" },
  }[state];
  return (
    <li className="flex items-start gap-4 px-5 py-4">
      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-surface-muted">
        <Icon className="h-4 w-4 text-muted-foreground" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-sm font-semibold">{name}</p>
          <span className={cx("badge", badge.cls)}>{badge.text}</span>
        </div>
        <p className="mt-0.5 text-xs text-muted-foreground">{purpose}</p>
        {detail && <p className="mt-1 text-xs text-foreground">{detail}</p>}
      </div>
    </li>
  );
}

export default function SettingsPage() {
  const allowed = useRequireAuth();
  const user = useCurrentUser();
  const isAdmin = user?.role === "admin";

  const statusQuery = useApi<ConfigStatus>(allowed ? "/analytics/config-status" : null, api.getConfigStatus);
  const kbsQuery = useApi<KnowledgeBase[]>(allowed ? "/knowledge-bases" : null, api.listKBs);
  const status = statusQuery.data;

  // Form fields start from the stored profile and only diverge once edited.
  const [nameDraft, setNameDraft] = useState<string | null>(null);
  const [emailDraft, setEmailDraft] = useState<string | null>(null);
  const name = nameDraft ?? user?.full_name ?? "";
  const email = emailDraft ?? user?.email ?? "";
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<{ tone: "success" | "danger"; text: string } | null>(null);

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!user) return;
    setSaving(true);
    setNotice(null);
    try {
      const updated = await api.updateUser(user.id, { full_name: name.trim(), email: email.trim() });
      authStorage.setUser(updated);
      setNameDraft(null);
      setEmailDraft(null);
      setNotice({ tone: "success", text: "Profile saved." });
    } catch (err) {
      setNotice({ tone: "danger", text: errorMessage(err, "Could not save your profile.") });
    } finally {
      setSaving(false);
    }
  };

  if (!allowed) return null;

  const dirty = nameDraft !== null || emailDraft !== null;
  const joined = user?.created_at ? new Date(user.created_at).toLocaleDateString(undefined, { year: "numeric", month: "long", day: "numeric" }) : "—";

  return (
    <div className="max-w-4xl space-y-6 animate-fade-in">
      <PageHeader eyebrow="Account" title="Settings" description="Your profile and, for admins, the health of every backing service." />
      {notice && <Alert tone={notice.tone} onClose={() => setNotice(null)}>{notice.text}</Alert>}

      <div className="grid gap-4 sm:grid-cols-3">
        <StatCard label="Knowledge bases" value={kbsQuery.loading ? <Skeleton className="h-7 w-10" /> : (kbsQuery.data?.length ?? "—")} icon={Database} />
        <StatCard label="Role" value={isAdmin ? "Admin" : "Member"} icon={UserIcon} />
        <StatCard label="Member since" value={<span className="text-base">{joined}</span>} />
      </div>

      <Card>
        <CardHeader title="Profile" description="Shown in the sidebar and on shared notes." />
        <form onSubmit={save} className="grid gap-4 p-5 sm:grid-cols-2">
          <div>
            <label htmlFor="full-name" className="label">Full name</label>
            <input id="full-name" required value={name} onChange={(e) => setNameDraft(e.target.value)} className="input" autoComplete="name" />
          </div>
          <div>
            <label htmlFor="email" className="label">Email</label>
            <input id="email" type="email" required value={email} onChange={(e) => setEmailDraft(e.target.value)} className="input" autoComplete="email" />
          </div>
          <div className="flex justify-end gap-2 sm:col-span-2">
            {dirty && <button type="button" className="btn btn-ghost" onClick={() => { setNameDraft(null); setEmailDraft(null); }}>Discard</button>}
            <button className="btn btn-primary" disabled={saving || !dirty}>{saving && <Spinner />}Save profile</button>
          </div>
        </form>
      </Card>

      {isAdmin && (
        <Card className="overflow-hidden">
          <CardHeader
            title="Services"
            description="Live status from the backend. Configuration lives in the server's environment variables."
            actions={<button className="btn btn-secondary btn-sm" onClick={statusQuery.reload} disabled={statusQuery.refreshing}>{statusQuery.refreshing && <Spinner className="h-3.5 w-3.5" />}Re-check</button>}
          />
          {statusQuery.loading ? (
            <div className="space-y-3 p-5">{Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-12" />)}</div>
          ) : !status ? (
            <div className="p-5"><Alert tone="danger">{statusQuery.error || "Could not reach the backend."}</Alert></div>
          ) : (
            <ul className="divide-y divide-border">
              <ServiceRow icon={Database} name="PostgreSQL" purpose="Users, documents, chunks and chat history." state={status.postgres_connected ? "ok" : "down"} />
              <ServiceRow
                icon={HardDrive} name="Redis" purpose="Chat memory, upload hand-off to the worker, indexing progress and answer cache."
                state={status.redis_connected ? "ok" : "down"}
                detail={status.redis_connected && status.redis_pending_documents != null ? `${status.redis_pending_documents} document(s) waiting for a worker` : undefined}
              />
              <ServiceRow
                icon={Layers} name="Qdrant" purpose="Vector search over document embeddings."
                state={status.qdrant_connected ? "ok" : "down"}
                detail={status.qdrant_connected && status.qdrant_collections != null ? `${status.qdrant_collections} collection(s)` : "Keyword search still works without it."}
              />
              <ServiceRow
                icon={Sparkles} name="Language model" purpose="Writes answers and judges their faithfulness."
                state={status.gemini_configured || status.openai_configured ? "ok" : "fallback"}
                detail={[status.gemini_configured && `Gemini: ${status.gemini_model}`, status.openai_configured && `OpenAI: ${status.openai_model ?? "configured"}`].filter(Boolean).join(" · ") || "No key set; answers use the offline summarizer."}
              />
              <ServiceRow icon={ServerCog} name="LlamaParse" purpose="Layout-aware parsing of PDFs and Word files." state={status.llamaparse_configured ? "ok" : "fallback"} detail={status.llamaparse_configured ? undefined : "Using local pypdf / python-docx parsing."} />
              <ServiceRow icon={Search} name="Tavily web search" purpose="Adds live web results when web search is switched on in Chat." state={status.tavily_configured ? "ok" : "off"} />
              <ServiceRow icon={Globe} name="URL import" purpose="Index web pages and linked files from the Documents page." state="ok" detail="Built in; private network addresses are blocked." />
            </ul>
          )}
        </Card>
      )}
    </div>
  );
}
