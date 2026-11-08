"use client";

import { useEffect, useState } from "react";
import { ExternalLink, FileText, Globe, X } from "lucide-react";
import { api, ChunkContext, Citation, DocumentInfo } from "@/lib/api";
import { errorMessage } from "@/lib/hooks";
import { Alert, Skeleton, Spinner } from "@/components/ui";

interface Props {
  citation: Citation | null;
  /** Documents of the current KB: used to resolve older citations saved before chunk ids existed. */
  kbDocs: DocumentInfo[];
  onClose: () => void;
}

type Loaded =
  | { kind: "context"; ctx: ChunkContext }
  | { kind: "page"; doc: DocumentInfo; passages: Array<{ id: string; content: string; chunk_index: number | null }> }
  | { kind: "web" }
  | { kind: "missing"; reason: string };

/**
 * Side panel that opens a cited passage: the exact chunk highlighted with the
 * text around it, plus a button to open the original file at that page.
 */
export default function CitationViewer({ citation, kbDocs, onClose }: Props) {
  const [loaded, setLoaded] = useState<{ key: string; data: Loaded } | null>(null);
  const [opening, setOpening] = useState(false);
  const [openError, setOpenError] = useState<string | null>(null);

  const key = citation ? `${citation.chunk_id ?? ""}|${citation.source_doc}|${citation.page}|${citation.url ?? ""}` : "";

  useEffect(() => {
    if (!citation) return;
    let cancelled = false;
    const done = (data: Loaded) => !cancelled && setLoaded({ key, data });

    (async () => {
      if (citation.url && !citation.chunk_id) return done({ kind: "web" });
      if (citation.chunk_id) {
        try {
          return done({ kind: "context", ctx: await api.getChunkContext(citation.chunk_id) });
        } catch {
          /* fall through: the chunk may have been re-indexed; try by page */
        }
      }
      const doc = kbDocs.find((d) => d.id === citation.doc_id) || kbDocs.find((d) => d.filename === citation.source_doc);
      if (!doc) return done({ kind: "missing", reason: "This document is no longer in the knowledge base." });
      try {
        const chunks = await api.listDocChunks(doc.id);
        const onPage = chunks.filter((c) => citation.page == null || c.page_number === citation.page);
        done({ kind: "page", doc, passages: onPage.length ? onPage : chunks.slice(0, 3) });
      } catch (e) {
        done({ kind: "missing", reason: errorMessage(e, "Could not load the passage.") });
      }
    })();

    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    return () => {
      cancelled = true;
      document.removeEventListener("keydown", onKey);
    };
  }, [citation, key, kbDocs, onClose]);

  if (!citation) return null;
  const data = loaded?.key === key ? loaded.data : null;

  const docId = data?.kind === "context" ? data.ctx.document.id : data?.kind === "page" ? data.doc.id : citation.doc_id;
  const fileType = (data?.kind === "context" ? data.ctx.document.file_type : data?.kind === "page" ? data.doc.file_type : "").toUpperCase();
  const sourceUrl = citation.url || (data?.kind === "context" ? data.ctx.document.source_url : null);
  const page = data?.kind === "context" ? data.ctx.chunk.page_number : citation.page;
  const canOpenFile = Boolean(docId) && (data?.kind !== "context" || data.ctx.document.has_file);

  const openOriginal = async () => {
    if (!docId) return;
    setOpenError(null);
    setOpening(true);
    // Open the tab synchronously (inside the click) so popup blockers allow it.
    const win = window.open("about:blank", "_blank");
    try {
      const blobUrl = await api.getDocumentFileUrl(docId);
      const target = fileType === "PDF" && page ? `${blobUrl}#page=${page}` : blobUrl;
      if (win) win.location.href = target;
      else window.location.href = target;
    } catch (e) {
      win?.close();
      setOpenError(errorMessage(e, "Could not open the original file."));
    } finally {
      setOpening(false);
    }
  };

  return (
    <>
      <div className="fixed inset-0 z-[60] bg-[#1a1a1a]/20 lg:hidden" onClick={onClose} />
      <aside
        className="fixed inset-y-0 right-0 z-[70] flex w-full max-w-md flex-col border-l border-border bg-surface shadow-[var(--shadow-lg)] animate-slide-in-right lg:relative lg:inset-auto lg:z-auto lg:w-[380px] lg:max-w-none lg:shrink-0 lg:rounded-[14px] lg:border lg:shadow-none"
        aria-label="Cited source"
      >
        <header className="flex items-start gap-3 border-b border-border px-4 py-3.5">
          <span className="cite-ref mt-0.5 shrink-0 cursor-default">{citation.index ?? "•"}</span>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-semibold text-foreground" title={citation.source_doc}>{citation.source_doc}</p>
            <p className="text-xs text-muted-foreground">
              {page != null ? `Page ${page}` : citation.url ? "Web result" : "Passage"}
              {typeof citation.score === "number" && citation.score > 0 && ` · relevance ${(citation.score * 100).toFixed(0)}%`}
            </p>
          </div>
          <button className="icon-btn -mr-1" onClick={onClose} aria-label="Close source">
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
          {!data ? (
            <div className="space-y-2">
              <Skeleton className="h-4 w-3/4" />
              <Skeleton className="h-24 w-full" />
              <Skeleton className="h-4 w-2/3" />
            </div>
          ) : data.kind === "missing" ? (
            <>
              <Alert tone="warning">{data.reason}</Alert>
              {citation.snippet && <Passage text={citation.snippet} />}
            </>
          ) : data.kind === "web" ? (
            <Passage text={citation.snippet || "No preview available for this web result."} />
          ) : data.kind === "context" ? (
            <div className="space-y-3 text-sm leading-relaxed">
              {data.ctx.before && <p className="line-clamp-4 whitespace-pre-wrap text-muted-foreground">…{data.ctx.before.slice(-400)}</p>}
              <Passage text={data.ctx.chunk.content} />
              {data.ctx.after && <p className="line-clamp-4 whitespace-pre-wrap text-muted-foreground">{data.ctx.after.slice(0, 400)}…</p>}
            </div>
          ) : (
            <div className="space-y-3">
              <p className="text-xs text-muted-foreground">Passages from page {citation.page ?? "?"}:</p>
              {data.passages.map((p) => (
                <Passage key={p.id} text={p.content} />
              ))}
            </div>
          )}
          {openError && <div className="mt-3"><Alert tone="danger" onClose={() => setOpenError(null)}>{openError}</Alert></div>}
        </div>

        <footer className="flex flex-wrap gap-2 border-t border-border px-4 py-3">
          {canOpenFile && data?.kind !== "web" && (
            <button className="btn btn-primary btn-sm" onClick={openOriginal} disabled={opening || !data}>
              {opening ? <Spinner className="h-3.5 w-3.5" /> : <FileText className="h-3.5 w-3.5" />}
              Open original{fileType === "PDF" && page ? ` at page ${page}` : ""}
            </button>
          )}
          {sourceUrl && (
            <a href={sourceUrl} target="_blank" rel="noopener noreferrer" className="btn btn-secondary btn-sm">
              {citation.url ? <Globe className="h-3.5 w-3.5" /> : <ExternalLink className="h-3.5 w-3.5" />}
              Open web page
            </a>
          )}
        </footer>
      </aside>
    </>
  );
}

function Passage({ text }: { text: string }) {
  return (
    <blockquote className="rounded-xl border border-[#ead9ad] bg-accent-soft/60 px-3.5 py-3">
      <p className="whitespace-pre-wrap text-sm leading-relaxed text-foreground">
        <mark className="cite-mark">{text}</mark>
      </p>
    </blockquote>
  );
}
