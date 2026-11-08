"use client";

import { useEffect, useState } from "react";
import { FolderOpen, RefreshCw, Search, Trash2 } from "lucide-react";
import { AdminDocumentInfo, api } from "@/lib/api";
import { errorMessage, formatBytes, useApi, useRequireAuth } from "@/lib/hooks";
import { Alert, Card, CardHeader, EmptyState, PageHeader, SkeletonRows, Spinner, StatusBadge, cx } from "@/components/ui";

export default function AdminDocumentManagementPage() {
  const allowed = useRequireAuth({ adminOnly: true });
  const docsQuery = useApi<AdminDocumentInfo[]>(allowed ? "/documents/admin/all" : null, () => api.listAllDocumentsAdmin({ noCache: true }));
  const documents = docsQuery.data ?? [];
  const { reload } = docsQuery;
  const [search, setSearch] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ tone: "success" | "danger"; text: string } | null>(null);

  const hasProcessing = documents.some((d) => d.status === "processing");
  useEffect(() => {
    if (!hasProcessing) return;
    const id = setInterval(reload, 3000);
    return () => clearInterval(id);
  }, [hasProcessing, reload]);

  const q = search.toLowerCase().trim();
  const filtered = q
    ? documents.filter((d) => d.filename.toLowerCase().includes(q) || d.kb_name.toLowerCase().includes(q) || d.file_type.toLowerCase().includes(q))
    : documents;

  const reindex = async (d: AdminDocumentInfo) => {
    setBusyId(d.id);
    setNotice(null);
    try {
      await api.reindexDocumentAdmin(d.id);
      docsQuery.setData((prev) => (prev ?? []).map((x) => (x.id === d.id ? { ...x, status: "processing" } : x)));
      setNotice({ tone: "success", text: `Re-indexing "${d.filename}".` });
    } catch (e) {
      setNotice({ tone: "danger", text: errorMessage(e, "Re-index failed.") });
    } finally {
      setBusyId(null);
    }
  };

  const remove = async (d: AdminDocumentInfo) => {
    if (!confirm(`Delete "${d.filename}" from "${d.kb_name}"? Its chunks and vectors are removed permanently.`)) return;
    setBusyId(d.id);
    try {
      await api.deleteDocumentAdmin(d.id);
      docsQuery.setData((prev) => (prev ?? []).filter((x) => x.id !== d.id));
      setNotice({ tone: "success", text: `Deleted "${d.filename}".` });
    } catch (e) {
      setNotice({ tone: "danger", text: errorMessage(e, "Delete failed.") });
    } finally {
      setBusyId(null);
    }
  };

  if (!allowed) return null;

  return (
    <div className="space-y-6 animate-fade-in">
      <PageHeader
        eyebrow="Admin"
        title="All Documents"
        description="Every document across every knowledge base."
        actions={
          <button className="btn btn-secondary" onClick={reload} disabled={docsQuery.refreshing}>
            <RefreshCw className={cx("h-4 w-4", docsQuery.refreshing && "animate-spin")} />Refresh
          </button>
        }
      />
      {notice && <Alert tone={notice.tone} onClose={() => setNotice(null)}>{notice.text}</Alert>}
      {docsQuery.error && <Alert tone="danger">{docsQuery.error}</Alert>}

      <Card className="overflow-hidden">
        <CardHeader
          title={`${documents.length} document${documents.length === 1 ? "" : "s"}`}
          description={`${documents.reduce((n, d) => n + d.chunk_count, 0).toLocaleString()} chunks indexed`}
          actions={
            <div className="relative w-64 max-w-full">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
              <input aria-label="Filter documents" placeholder="Filter by name, KB or type…" value={search} onChange={(e) => setSearch(e.target.value)} className="input h-8 pl-8 text-[13px]" />
            </div>
          }
        />
        {docsQuery.loading ? (
          <SkeletonRows rows={6} />
        ) : filtered.length === 0 ? (
          <EmptyState icon={FolderOpen} title="No documents found" />
        ) : (
          <div className="overflow-x-auto">
            <table className="table">
              <thead>
                <tr>
                  <th>Document</th>
                  <th>Knowledge base</th>
                  <th className="text-right">Size</th>
                  <th className="text-right">Chunks</th>
                  <th>Status</th>
                  <th className="text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((d) => (
                  <tr key={d.id}>
                    <td className="max-w-[280px]">
                      <div className="flex items-center gap-2.5">
                        <span className="badge badge-neutral shrink-0">{d.file_type}</span>
                        <span className="truncate font-medium" title={d.filename}>{d.filename}</span>
                      </div>
                    </td>
                    <td className="text-muted-foreground">{d.kb_name}</td>
                    <td className="whitespace-nowrap text-right tabular-nums text-muted-foreground">{formatBytes(d.file_size)}</td>
                    <td className="text-right tabular-nums">{d.chunk_count.toLocaleString()}</td>
                    <td><StatusBadge status={d.status} /></td>
                    <td>
                      <div className="flex items-center justify-end">
                        {busyId === d.id ? (
                          <Spinner className="mr-2 text-muted-foreground" />
                        ) : (
                          <>
                            <button className="icon-btn" onClick={() => reindex(d)} disabled={d.status === "processing"} title="Re-index" aria-label={`Re-index ${d.filename}`}>
                              <RefreshCw className="h-4 w-4" />
                            </button>
                            <button className="icon-btn icon-btn-danger" onClick={() => remove(d)} title="Delete" aria-label={`Delete ${d.filename}`}>
                              <Trash2 className="h-4 w-4" />
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
