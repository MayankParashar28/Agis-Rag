"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Database, FileText, Layers, MessageSquare, Plus, Trash2, UploadCloud } from "lucide-react";
import { api, KBStats, KnowledgeBase } from "@/lib/api";
import { errorMessage, useApi, useRequireAuth } from "@/lib/hooks";
import { Alert, Card, EmptyState, Modal, PageHeader, Skeleton, Spinner } from "@/components/ui";

export default function KnowledgeBasesPage() {
  const allowed = useRequireAuth();
  const router = useRouter();
  const kbsQuery = useApi<KnowledgeBase[]>(allowed ? "/knowledge-bases" : null, api.listKBs);
  const kbs = kbsQuery.data ?? [];
  const { setData: setKbs } = kbsQuery;
  const [statsMap, setStatsMap] = useState<Record<string, KBStats>>({});

  const [isModalOpen, setIsModalOpen] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Stats load in parallel and fill in per card, so the list never waits on them.
  const kbIds = (kbsQuery.data ?? []).map((k) => k.id).join(",");
  useEffect(() => {
    if (!kbIds) return;
    let cancelled = false;
    kbIds.split(",").forEach((id) => {
      api
        .getKBStats(id)
        .then((stats) => !cancelled && setStatsMap((m) => ({ ...m, [id]: stats })))
        .catch(() => undefined);
    });
    return () => {
      cancelled = true;
    };
  }, [kbIds]);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    setError(null);
    setCreating(true);
    try {
      const kb = await api.createKB({ name: name.trim(), description: description.trim() || null });
      setKbs((prev) => [...(prev ?? []), kb]);
      setIsModalOpen(false);
      setName("");
      setDescription("");
    } catch (err) {
      setError(errorMessage(err, "Failed to create knowledge base."));
    } finally {
      setCreating(false);
    }
  };

  const handleDelete = async (kb: KnowledgeBase) => {
    if (!confirm(`Delete "${kb.name}"? All of its documents and vectors are removed permanently.`)) return;
    try {
      await api.deleteKB(kb.id);
      setKbs((prev) => (prev ?? []).filter((k) => k.id !== kb.id));
    } catch (err) {
      setError(errorMessage(err, "Failed to delete knowledge base."));
    }
  };

  if (!allowed) return null;

  return (
    <div className="space-y-6 animate-fade-in">
      <PageHeader
        eyebrow="Workspace"
        title="Knowledge Bases"
        description="Each knowledge base is an isolated collection of documents with its own search index."
        actions={
          <button className="btn btn-primary" onClick={() => setIsModalOpen(true)}>
            <Plus className="h-4 w-4" /> New knowledge base
          </button>
        }
      />

      {(error || kbsQuery.error) && <Alert tone="danger" onClose={() => setError(null)}>{error || kbsQuery.error}</Alert>}

      {kbsQuery.loading ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-52" />)}
        </div>
      ) : kbs.length === 0 ? (
        <Card>
          <EmptyState
            icon={Database}
            title="No knowledge bases yet"
            description="Create one to hold a set of documents you want to search and chat with."
            action={<button className="btn btn-primary" onClick={() => setIsModalOpen(true)}><Plus className="h-4 w-4" />Create knowledge base</button>}
          />
        </Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {kbs.map((kb) => {
            const stats = statsMap[kb.id];
            return (
              <Card key={kb.id} className="card-hover flex flex-col p-5">
                <div className="flex items-start justify-between gap-3">
                  <div className="flex min-w-0 items-center gap-3">
                    <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-accent-soft text-accent-hover">
                      <Database className="h-5 w-5" />
                    </div>
                    <h2 className="truncate text-base font-semibold text-foreground" title={kb.name}>{kb.name}</h2>
                  </div>
                  <button className="icon-btn icon-btn-danger" onClick={() => handleDelete(kb)} aria-label={`Delete ${kb.name}`} title="Delete">
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
                <p className="mt-3 line-clamp-2 min-h-[2.5rem] text-sm text-muted-foreground">{kb.description || "No description."}</p>

                <dl className="mt-4 grid grid-cols-2 gap-3 rounded-xl bg-background px-4 py-3">
                  <div>
                    <dt className="flex items-center gap-1.5 text-xs text-muted-foreground"><FileText className="h-3.5 w-3.5" />Documents</dt>
                    <dd className="mt-0.5 text-lg font-semibold tabular-nums">{stats ? stats.total_documents : <Skeleton className="mt-1 h-5 w-8" />}</dd>
                  </div>
                  <div>
                    <dt className="flex items-center gap-1.5 text-xs text-muted-foreground"><Layers className="h-3.5 w-3.5" />Chunks</dt>
                    <dd className="mt-0.5 text-lg font-semibold tabular-nums">{stats ? stats.total_chunks.toLocaleString() : <Skeleton className="mt-1 h-5 w-12" />}</dd>
                  </div>
                </dl>

                <div className="mt-4 flex gap-2">
                  <button className="btn btn-secondary flex-1" onClick={() => router.push(`/upload?kb_id=${kb.id}`)}>
                    <UploadCloud className="h-4 w-4" /> Documents
                  </button>
                  <button className="btn btn-primary flex-1" onClick={() => router.push(`/chat?kb_id=${kb.id}`)}>
                    <MessageSquare className="h-4 w-4" /> Chat
                  </button>
                </div>
              </Card>
            );
          })}
        </div>
      )}

      <Modal open={isModalOpen} onClose={() => setIsModalOpen(false)} title="New knowledge base" description="Group related documents so answers stay focused.">
        <form onSubmit={handleCreate} className="space-y-4">
          <div>
            <label htmlFor="kb-name" className="label">Name</label>
            <input id="kb-name" required autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="Q2 financial reports" className="input" />
          </div>
          <div>
            <label htmlFor="kb-desc" className="label">Description <span className="font-normal text-muted-foreground">(optional)</span></label>
            <textarea id="kb-desc" rows={3} value={description} onChange={(e) => setDescription(e.target.value)} placeholder="What these documents are about" className="input resize-none" />
          </div>
          <div className="flex justify-end gap-2 pt-1">
            <button type="button" className="btn btn-secondary" onClick={() => setIsModalOpen(false)}>Cancel</button>
            <button type="submit" className="btn btn-primary" disabled={creating || !name.trim()}>
              {creating && <Spinner />}Create knowledge base
            </button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
