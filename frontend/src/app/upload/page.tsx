"use client";

import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Eye, FileText, Globe, Link2, RefreshCw, Search, Trash2, UploadCloud } from "lucide-react";
import { api, DocumentChunk, DocumentInfo, IndexingProgress, KnowledgeBase } from "@/lib/api";
import { errorMessage, formatBytes, useApi, useRequireAuth } from "@/lib/hooks";
import {
  Alert, Card, CardHeader, EmptyState, IndexingBar, KBSelect, Modal, PageHeader, Skeleton, SkeletonRows, Spinner, StatusBadge, cx,
} from "@/components/ui";

const ACCEPTED = [".pdf", ".docx", ".txt", ".csv"];
const MAX_MB = 50;

function UploadPageContent() {
  const allowed = useRequireAuth();
  const router = useRouter();
  const searchParams = useSearchParams();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const kbsQuery = useApi<KnowledgeBase[]>(allowed ? "/knowledge-bases" : null, api.listKBs);
  const kbs = useMemo(() => kbsQuery.data ?? [], [kbsQuery.data]);
  const [pickedKB, setPickedKB] = useState<string>("");
  const selectedKBId = pickedKB || searchParams.get("kb_id") || kbs[0]?.id || "";

  const docsQuery = useApi<DocumentInfo[]>(
    selectedKBId ? `/documents/${selectedKBId}` : null,
    () => api.listDocs(selectedKBId, { noCache: true })
  );
  const documents = useMemo(() => docsQuery.data ?? [], [docsQuery.data]);
  const { setData: setDocuments, reload: reloadDocs } = docsQuery;

  const [progress, setProgress] = useState<Record<string, IndexingProgress>>({});
  const [chunkSize, setChunkSize] = useState(1000);
  const [chunkOverlap, setChunkOverlap] = useState(200);
  const [uploads, setUploads] = useState<string[]>([]);
  const [dragging, setDragging] = useState(false);
  const [url, setUrl] = useState("");
  const [importing, setImporting] = useState(false);
  const [notice, setNotice] = useState<{ tone: "danger" | "success" | "warning"; text: string } | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");

  // Chunk inspector
  const [inspectorDoc, setInspectorDoc] = useState<DocumentInfo | null>(null);
  const [chunks, setChunks] = useState<DocumentChunk[] | null>(null);
  const [chunkSearch, setChunkSearch] = useState("");

  const processingIds = useMemo(() => documents.filter((d) => d.status === "processing").map((d) => d.id), [documents]);
  const hasProcessing = processingIds.length > 0;

  // Live progress: poll quickly while anything is indexing, stop when idle.
  // The document list is re-read from the database every few ticks as well,
  // so a finished document flips to "Ready" even when no live progress
  // arrives (older backend, Redis unreachable) - no page refresh needed.
  useEffect(() => {
    if (!selectedKBId || !hasProcessing) return;
    let cancelled = false;
    let ticks = 0;
    const tick = async () => {
      ticks += 1;
      let finished = ticks % 3 === 0;
      try {
        const live = await api.getIndexingProgress(selectedKBId);
        if (cancelled) return;
        setProgress(live);
        if (Object.values(live).some((p) => p.stage === "done" || p.stage === "failed")) finished = true;
      } catch {
        if (!cancelled) setProgress({});
      }
      if (finished && !cancelled) await reloadDocs();
    };
    tick();
    const id = setInterval(tick, 1500);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [selectedKBId, hasProcessing, reloadDocs]);

  const uploadFiles = useCallback(
    async (files: File[]) => {
      if (!selectedKBId || files.length === 0) return;
      setNotice(null);
      const problems: string[] = [];
      for (const file of files) {
        const ext = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
        if (!ACCEPTED.includes(ext)) {
          problems.push(`${file.name}: unsupported type (${ext || "none"}).`);
          continue;
        }
        if (file.size > MAX_MB * 1024 * 1024) {
          problems.push(`${file.name}: larger than ${MAX_MB} MB.`);
          continue;
        }
        setUploads((u) => [...u, file.name]);
        try {
          const doc = await api.uploadDoc(selectedKBId, file, chunkSize, chunkOverlap);
          setDocuments((prev) => [doc, ...(prev ?? []).filter((d) => d.id !== doc.id)]);
        } catch (e) {
          problems.push(`${file.name}: ${errorMessage(e, "upload failed")}`);
        } finally {
          setUploads((u) => u.filter((n) => n !== file.name));
        }
      }
      if (problems.length) setNotice({ tone: "danger", text: problems.join(" ") });
      if (fileInputRef.current) fileInputRef.current.value = "";
    },
    [selectedKBId, chunkSize, chunkOverlap, setDocuments]
  );

  const handleImportUrl = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!url.trim() || !selectedKBId) return;
    // Accept "example.com/page" as well as full links.
    const link = /^[a-z][a-z0-9+.-]*:\/\//i.test(url.trim()) ? url.trim() : `https://${url.trim()}`;
    setImporting(true);
    setNotice(null);
    try {
      const doc = await api.importUrl(selectedKBId, link, chunkSize, chunkOverlap);
      setDocuments((prev) => [doc, ...(prev ?? [])]);
      setUrl("");
      setNotice({ tone: "success", text: `Imported "${doc.filename}". Indexing has started.` });
    } catch (err) {
      setNotice({ tone: "danger", text: errorMessage(err, "Could not import that link.") });
    } finally {
      setImporting(false);
    }
  };

  const handleDelete = async (doc: DocumentInfo) => {
    if (!confirm(`Delete "${doc.filename}"? Its chunks and embeddings will be removed.`)) return;
    try {
      await api.deleteDoc(doc.id);
      setDocuments((prev) => (prev ?? []).filter((d) => d.id !== doc.id));
    } catch (e) {
      setNotice({ tone: "danger", text: errorMessage(e, "Failed to delete document.") });
    }
  };

  const handleReindex = async (doc: DocumentInfo) => {
    try {
      const updated = await api.reindexDoc(doc.id);
      setDocuments((prev) => (prev ?? []).map((d) => (d.id === doc.id ? updated : d)));
    } catch (e) {
      setNotice({ tone: "danger", text: errorMessage(e, "Failed to start re-indexing.") });
    }
  };

  const openInspector = async (doc: DocumentInfo) => {
    setInspectorDoc(doc);
    setChunks(null);
    setChunkSearch("");
    try {
      setChunks(await api.listDocChunks(doc.id));
    } catch (e) {
      setChunks([]);
      setNotice({ tone: "danger", text: errorMessage(e, "Failed to load chunks.") });
    }
  };

  const filteredDocs = documents.filter(
    (d) => d.filename.toLowerCase().includes(searchQuery.toLowerCase()) && (statusFilter === "all" || d.status === statusFilter)
  );
  const filteredChunks = (chunks ?? []).filter((c) => c.content.toLowerCase().includes(chunkSearch.toLowerCase()));
  const counts = {
    indexed: documents.filter((d) => d.status === "indexed").length,
    processing: processingIds.length,
    failed: documents.filter((d) => d.status === "failed").length,
  };

  if (!allowed) return null;

  return (
    <div className="space-y-6 animate-fade-in">
      <PageHeader
        eyebrow="Ingestion"
        title="Documents"
        description="Add files or web pages to a knowledge base. Progress updates live while each one is read, chunked and embedded."
      />

      {kbsQuery.loading ? (
        <Skeleton className="h-24 w-full" />
      ) : kbs.length === 0 ? (
        <Card>
          <EmptyState
            icon={UploadCloud}
            title="Create a knowledge base first"
            description="Documents live inside a knowledge base."
            action={<button className="btn btn-primary" onClick={() => router.push("/knowledge-bases")}>Create knowledge base</button>}
          />
        </Card>
      ) : (
        <>
          <Card className="grid gap-4 p-5 md:grid-cols-[minmax(0,2fr)_repeat(2,minmax(0,1fr))]">
            <KBSelect kbs={kbs} value={selectedKBId} onChange={(id) => { setPickedKB(id); setProgress({}); }} />
            <div>
              <label htmlFor="chunk-size" className="label">Chunk size</label>
              <input id="chunk-size" type="number" min={100} max={8000} value={chunkSize} onChange={(e) => setChunkSize(Number(e.target.value))} className="input" />
            </div>
            <div>
              <label htmlFor="chunk-overlap" className="label">Overlap</label>
              <input id="chunk-overlap" type="number" min={0} max={2000} value={chunkOverlap} onChange={(e) => setChunkOverlap(Number(e.target.value))} className="input" />
            </div>
          </Card>

          {notice && <Alert tone={notice.tone} onClose={() => setNotice(null)}>{notice.text}</Alert>}
          {(kbsQuery.error || docsQuery.error) && <Alert tone="danger">{kbsQuery.error || docsQuery.error}</Alert>}

          <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
            <div className="space-y-6">
              {/* Dropzone */}
              <div
                role="button"
                tabIndex={0}
                aria-label="Upload files"
                onClick={() => fileInputRef.current?.click()}
                onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && fileInputRef.current?.click()}
                onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
                onDragLeave={() => setDragging(false)}
                onDrop={(e) => { e.preventDefault(); setDragging(false); uploadFiles(Array.from(e.dataTransfer.files)); }}
                className={cx(
                  "flex min-h-[220px] cursor-pointer flex-col items-center justify-center rounded-[14px] border-2 border-dashed bg-surface p-6 text-center transition-colors",
                  dragging ? "border-accent bg-accent-soft" : "border-border hover:border-border-strong"
                )}
              >
                <input ref={fileInputRef} type="file" multiple accept={ACCEPTED.join(",")} className="hidden" onChange={(e) => uploadFiles(Array.from(e.target.files ?? []))} />
                <div className="mb-3 flex h-11 w-11 items-center justify-center rounded-full bg-surface-muted">
                  {uploads.length ? <Spinner className="h-5 w-5 text-accent" /> : <UploadCloud className="h-5 w-5 text-foreground" />}
                </div>
                <p className="text-sm font-semibold text-foreground">
                  {uploads.length ? `Uploading ${uploads.length} file${uploads.length > 1 ? "s" : ""}…` : "Drop files here or click to browse"}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">PDF, DOCX, TXT or CSV · up to {MAX_MB} MB each · several at once</p>
              </div>

              {/* URL import */}
              <Card className="p-5">
                <form onSubmit={handleImportUrl} className="space-y-3">
                  <label htmlFor="import-url" className="label flex items-center gap-2"><Globe className="h-4 w-4 text-muted-foreground" />Import from a link</label>
                  <div className="flex flex-col gap-2 sm:flex-row xl:flex-col 2xl:flex-row">
                    <div className="relative min-w-0 flex-1">
                      <Link2 className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                      <input id="import-url" type="text" inputMode="url" autoComplete="url" required placeholder="example.com/handbook" value={url} onChange={(e) => setUrl(e.target.value)} className="input pl-9" />
                    </div>
                    <button className="btn btn-primary" disabled={importing || !url.trim()}>
                      {importing ? <Spinner /> : null}Import
                    </button>
                  </div>
                  <p className="text-xs text-muted-foreground">Web pages are converted to text. Links to PDF, DOCX or CSV files are downloaded as-is.</p>
                </form>
              </Card>

              <div className="grid grid-cols-3 gap-3">
                {(["indexed", "processing", "failed"] as const).map((k) => (
                  <button
                    key={k}
                    onClick={() => setStatusFilter(statusFilter === k ? "all" : k)}
                    className={cx("card px-3 py-3 text-left transition-colors", statusFilter === k && "border-accent")}
                  >
                    <p className="text-xs text-muted-foreground">{k === "indexed" ? "Ready" : k === "processing" ? "Indexing" : "Failed"}</p>
                    <p className="mt-1 text-xl font-semibold tabular-nums">{counts[k]}</p>
                  </button>
                ))}
              </div>
            </div>

            {/* Document list */}
            <Card className="overflow-hidden">
              <CardHeader
                title="Documents in this knowledge base"
                description={docsQuery.refreshing ? "Refreshing…" : `${documents.length} total`}
                actions={
                  <div className="relative w-48 max-w-full">
                    <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
                    <input aria-label="Search documents" placeholder="Search…" value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)} className="input h-8 pl-8 text-[13px]" />
                  </div>
                }
              />
              {docsQuery.loading ? (
                <SkeletonRows rows={5} />
              ) : documents.length === 0 ? (
                <EmptyState icon={FileText} title="No documents yet" description="Upload a file or import a link to start indexing." />
              ) : filteredDocs.length === 0 ? (
                <EmptyState icon={Search} title="No matches" description="Try a different search or status filter." />
              ) : (
                <ul className="divide-y divide-border">
                  {filteredDocs.map((doc) => (
                    <li key={doc.id} className="flex flex-col gap-3 px-5 py-3.5 sm:flex-row sm:items-center">
                      <button
                        className="flex min-w-0 flex-1 items-center gap-3 text-left disabled:cursor-default"
                        onClick={() => openInspector(doc)}
                        disabled={doc.status !== "indexed"}
                        title={doc.status === "indexed" ? "Inspect chunks" : undefined}
                      >
                        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-surface-muted text-[10px] font-bold text-muted-foreground">
                          {doc.meta_info?.source_url ? <Globe className="h-4 w-4" /> : doc.file_type}
                        </div>
                        <div className="min-w-0">
                          <p className="truncate text-sm font-medium text-foreground" title={doc.filename}>{doc.filename}</p>
                          <p className="truncate text-xs text-muted-foreground">
                            {formatBytes(doc.file_size)}
                            {doc.status === "indexed" && doc.meta_info?.total_chunks != null && ` · ${doc.meta_info.total_chunks} chunks`}
                            {doc.status === "failed" && doc.meta_info?.error_msg && ` · ${doc.meta_info.error_msg}`}
                          </p>
                          {doc.meta_info?.summary && (
                            <p className="mt-1 line-clamp-2 text-xs text-muted-foreground/90" title={doc.meta_info.summary}>{doc.meta_info.summary}</p>
                          )}
                          {Array.isArray(doc.meta_info?.keywords) && doc.meta_info.keywords.length > 0 && (
                            <div className="mt-1.5 flex flex-wrap gap-1">
                              {doc.meta_info.keywords.slice(0, 6).map((k: string) => (
                                <span key={k} className="rounded-full bg-surface-muted px-2 py-0.5 text-[11px] text-muted-foreground">{k}</span>
                              ))}
                            </div>
                          )}
                        </div>
                      </button>
                      <div className="flex items-center gap-3 sm:w-[260px] sm:justify-end">
                        {doc.status === "processing" ? (
                          <div className="flex-1"><IndexingBar progress={progress[doc.id]} compact /></div>
                        ) : (
                          <StatusBadge status={doc.status} />
                        )}
                        <div className="flex items-center">
                          <button className="icon-btn" onClick={() => openInspector(doc)} disabled={doc.status !== "indexed"} title="Inspect chunks" aria-label={`Inspect chunks of ${doc.filename}`}>
                            <Eye className="h-4 w-4" />
                          </button>
                          <button className="icon-btn" onClick={() => handleReindex(doc)} disabled={doc.status === "processing"} title="Re-index" aria-label={`Re-index ${doc.filename}`}>
                            <RefreshCw className="h-4 w-4" />
                          </button>
                          <button className="icon-btn icon-btn-danger" onClick={() => handleDelete(doc)} title="Delete" aria-label={`Delete ${doc.filename}`}>
                            <Trash2 className="h-4 w-4" />
                          </button>
                        </div>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </div>
        </>
      )}

      <Modal
        open={Boolean(inspectorDoc)}
        onClose={() => setInspectorDoc(null)}
        title="Chunk inspector"
        description={inspectorDoc ? `${inspectorDoc.filename} · ${chunks?.length ?? "…"} chunks` : undefined}
        size="xl"
      >
        <div className="relative mb-4">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <input aria-label="Filter chunks" placeholder="Filter chunks by keyword…" value={chunkSearch} onChange={(e) => setChunkSearch(e.target.value)} className="input pl-9" />
        </div>
        {chunks === null ? (
          <div className="grid gap-3 md:grid-cols-2">{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-36" />)}</div>
        ) : filteredChunks.length === 0 ? (
          <EmptyState icon={Search} title="No matching chunks" />
        ) : (
          <div className="grid gap-3 md:grid-cols-2">
            {filteredChunks.map((chunk) => (
              <div key={chunk.id} className="rounded-xl border border-border bg-background p-4">
                <div className="mb-2 flex items-center gap-2">
                  <span className="badge badge-accent">#{chunk.chunk_index ?? 0}</span>
                  {chunk.page_number !== null && <span className="badge badge-neutral">Page {chunk.page_number}</span>}
                </div>
                <p className="max-h-48 overflow-y-auto whitespace-pre-wrap text-xs leading-relaxed text-muted-foreground">{chunk.content}</p>
              </div>
            ))}
          </div>
        )}
      </Modal>
    </div>
  );
}

export default function UploadPage() {
  return (
    <Suspense fallback={<SkeletonRows rows={6} />}>
      <UploadPageContent />
    </Suspense>
  );
}
