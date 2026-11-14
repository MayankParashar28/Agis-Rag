"use client";

import { useEffect, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, ZoomIn, ZoomOut } from "lucide-react";
import { Alert, Spinner } from "@/components/ui";

interface Props {
  /** Blob/object URL of the PDF (already authenticated). */
  url: string;
  page: number;
  /** The cited passage; matching text on the page is highlighted. */
  highlight?: string | null;
}

type TextItem = { str: string; transform: number[]; width: number; height: number };

const norm = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();

/**
 * Which text items on the page belong to the passage. Works on the
 * normalised concatenation of the items, so hyphenation and spacing
 * differences between the PDF text layer and the stored chunk do not matter.
 */
function findMatches(items: TextItem[], passage: string): Set<number> {
  const hit = new Set<number>();
  const target = norm(passage);
  if (target.length < 12) return hit;
  // Try progressively shorter windows of the passage (start, middle, end)
  const probes = [target.slice(0, 80), target.slice(Math.max(0, target.length / 2 - 40), target.length / 2 + 40), target.slice(-80)]
    .map((p) => p.trim())
    .filter((p) => p.length >= 12);

  const normItems = items.map((it) => norm(it.str));
  // Build concatenation with index map.
  let joined = "";
  const owner: number[] = [];
  normItems.forEach((t, i) => {
    if (!t) return;
    const piece = t + " ";
    for (let k = 0; k < piece.length; k++) owner.push(i);
    joined += piece;
  });
  const anchors: number[] = [];
  for (const probe of probes) {
    const at = joined.indexOf(probe);
    if (at !== -1) anchors.push(at, at + probe.length);
  }
  if (!anchors.length) {
    // Fallback: items that share many words with the passage
    const words = new Set(target.split(" ").filter((w) => w.length > 4));
    normItems.forEach((t, i) => {
      const ws = t.split(" ");
      const common = ws.filter((w) => words.has(w)).length;
      if (ws.length >= 3 && common / ws.length > 0.6) hit.add(i);
    });
    return hit;
  }
  const start = Math.min(...anchors);
  const end = Math.max(...anchors);
  for (let k = start; k < end && k < owner.length; k++) hit.add(owner[k]);
  return hit;
}

export default function PdfPassage({ url, page, highlight }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const overlayRef = useRef<HTMLDivElement>(null);
  // User navigation overrides the requested page until the citation changes.
  const [override, setOverride] = useState<{ forPage: number; forUrl: string; value: number } | null>(null);
  const pageNum = override && override.forPage === page && override.forUrl === url ? override.value : page;
  const setPageNum = (fn: (p: number) => number) => setOverride({ forPage: page, forUrl: url, value: fn(pageNum) });
  const [pages, setPages] = useState(0);
  const [scale, setScale] = useState(1.1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [matched, setMatched] = useState<number | null>(null);
  const docRef = useRef<import("pdfjs-dist").PDFDocumentProxy | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        setLoading(true);
        setError(null);
        const pdfjs = await import("pdfjs-dist");
        pdfjs.GlobalWorkerOptions.workerSrc = "/pdf.worker.min.mjs";
        if (!docRef.current) {
          docRef.current = await pdfjs.getDocument({ url }).promise;
          if (cancelled) return;
          setPages(docRef.current.numPages);
        }
        const doc = docRef.current;
        const n = Math.min(Math.max(1, pageNum), doc.numPages);
        const pdfPage = await doc.getPage(n);
        const dpr = window.devicePixelRatio || 1;
        const viewport = pdfPage.getViewport({ scale });
        const canvas = canvasRef.current!;
        canvas.width = Math.floor(viewport.width * dpr);
        canvas.height = Math.floor(viewport.height * dpr);
        canvas.style.width = `${viewport.width}px`;
        canvas.style.height = `${viewport.height}px`;
        const ctx = canvas.getContext("2d")!;
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        await pdfPage.render({ canvasContext: ctx, viewport }).promise;
        if (cancelled) return;

        // Highlight boxes
        const overlay = overlayRef.current!;
        overlay.innerHTML = "";
        overlay.style.width = `${viewport.width}px`;
        overlay.style.height = `${viewport.height}px`;
        if (highlight) {
          const content = await pdfPage.getTextContent();
          const items = (content.items as unknown[]).filter((it): it is TextItem => typeof it === "object" && it !== null && "str" in it);
          const hits = findMatches(items, highlight);
          setMatched(hits.size);
          let firstTop: number | null = null;
          hits.forEach((i) => {
            const it = items[i];
            const [a, b, c, d, e, f] = it.transform;
            const [x, y] = viewport.convertToViewportPoint(e, f);
            const h = Math.hypot(b, d) * scale || Math.abs(d) * scale || 10;
            const w = it.width * scale;
            const box = document.createElement("div");
            box.style.cssText = `position:absolute;left:${x}px;top:${y - h}px;width:${w}px;height:${h * 1.15}px;background:rgba(168,128,31,.32);border-radius:2px;pointer-events:none;`;
            overlay.appendChild(box);
            if (firstTop === null || y - h < firstTop) firstTop = y - h;
            void a; void c;
          });
          if (firstTop !== null) {
            overlay.parentElement?.parentElement?.scrollTo({ top: Math.max(0, firstTop - 80), behavior: "smooth" });
          }
        } else {
          setMatched(null);
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "Could not render the PDF.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [url, pageNum, scale, highlight]);

  useEffect(() => () => { docRef.current?.destroy(); docRef.current = null; }, [url]);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center justify-between gap-2 border-b border-border px-3 py-1.5 text-xs">
        <div className="flex items-center gap-1">
          <button className="icon-btn h-7 w-7" onClick={() => setPageNum((p) => Math.max(1, p - 1))} disabled={pageNum <= 1} aria-label="Previous page"><ChevronLeft className="h-4 w-4" /></button>
          <span className="tabular-nums">Page {pageNum}{pages ? ` / ${pages}` : ""}</span>
          <button className="icon-btn h-7 w-7" onClick={() => setPageNum((p) => Math.min(pages || p + 1, p + 1))} disabled={pages > 0 && pageNum >= pages} aria-label="Next page"><ChevronRight className="h-4 w-4" /></button>
        </div>
        <div className="flex items-center gap-1">
          {matched !== null && (
            <span className={matched ? "badge badge-accent" : "badge badge-neutral"}>{matched ? "Passage highlighted" : "Passage not found on this page"}</span>
          )}
          <button className="icon-btn h-7 w-7" onClick={() => setScale((s) => Math.max(0.6, s - 0.2))} aria-label="Zoom out"><ZoomOut className="h-4 w-4" /></button>
          <button className="icon-btn h-7 w-7" onClick={() => setScale((s) => Math.min(2.4, s + 0.2))} aria-label="Zoom in"><ZoomIn className="h-4 w-4" /></button>
        </div>
      </div>
      <div className="relative min-h-0 flex-1 overflow-auto bg-surface-muted p-3">
        {error && <Alert tone="danger">{error}</Alert>}
        {loading && <div className="absolute inset-0 z-10 flex items-center justify-center bg-surface-muted/70"><Spinner className="h-5 w-5 text-accent" /></div>}
        <div className="relative mx-auto w-fit shadow-[var(--shadow-md)]">
          <canvas ref={canvasRef} className="block bg-white" />
          <div ref={overlayRef} className="pointer-events-none absolute left-0 top-0" />
        </div>
      </div>
    </div>
  );
}
