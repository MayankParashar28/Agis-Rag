"use client";

import { useEffect, useRef, useState } from "react";
import { Check, ChevronDown, Database, FileText, Globe, Search } from "lucide-react";
import type { DocumentInfo, KnowledgeBase } from "@/lib/api";
import { Spinner, cx } from "@/components/ui";

/** Small popover that closes on outside click and Escape. */
function usePopover() {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);
  return { open, setOpen, ref };
}

export function KBPicker({
  kbs,
  value,
  onChange,
}: {
  kbs: KnowledgeBase[];
  value: string;
  onChange: (id: string) => void;
}) {
  const { open, setOpen, ref } = usePopover();
  const current = kbs.find((k) => k.id === value);
  return (
    <div ref={ref} className="relative min-w-0">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-haspopup="listbox"
        aria-expanded={open}
        className="flex h-9 max-w-[240px] items-center gap-2 rounded-lg border border-border bg-surface px-3 text-sm font-semibold text-foreground transition-colors hover:border-border-strong"
      >
        <Database className="h-4 w-4 shrink-0 text-accent" />
        <span className="truncate">{current?.name ?? "Choose a knowledge base"}</span>
        <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
      </button>
      {open && (
        <div role="listbox" aria-label="Knowledge bases" className="absolute left-0 top-11 z-50 w-72 max-w-[85vw] overflow-hidden rounded-xl border border-border bg-surface shadow-[var(--shadow-lg)] animate-zoom-in">
          <p className="eyebrow px-3 pb-1 pt-3 text-[10px]">Knowledge base</p>
          <ul className="max-h-72 overflow-y-auto p-1.5">
            {kbs.map((kb) => (
              <li key={kb.id}>
                <button
                  type="button"
                  role="option"
                  aria-selected={kb.id === value}
                  onClick={() => {
                    setOpen(false);
                    if (kb.id !== value) onChange(kb.id);
                  }}
                  className={cx("flex w-full items-start gap-2.5 rounded-lg px-2.5 py-2 text-left hover:bg-surface-muted", kb.id === value && "bg-surface-muted")}
                >
                  <Check className={cx("mt-0.5 h-4 w-4 shrink-0", kb.id === value ? "text-accent" : "invisible")} />
                  <span className="min-w-0">
                    <span className="block truncate text-sm font-medium text-foreground">{kb.name}</span>
                    {kb.description && <span className="block truncate text-xs text-muted-foreground">{kb.description}</span>}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export function DocumentPicker({
  docs,
  loading,
  selected,
  onChange,
}: {
  docs: DocumentInfo[];
  loading: boolean;
  selected: string[];
  onChange: (ids: string[]) => void;
}) {
  const { open, setOpen, ref } = usePopover();
  const [filter, setFilter] = useState("");
  const ready = docs.filter((d) => d.status === "indexed");
  const shown = docs.filter((d) => d.filename.toLowerCase().includes(filter.toLowerCase()));
  const label = loading
    ? "Loading documents…"
    : ready.length === 0
      ? "No documents"
      : selected.length === 0
        ? `All documents (${ready.length})`
        : selected.length === 1
          ? docs.find((d) => d.id === selected[0])?.filename ?? "1 document"
          : `${selected.length} of ${ready.length} documents`;

  const toggle = (id: string) => onChange(selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id]);

  return (
    <div ref={ref} className="relative min-w-0">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        disabled={loading}
        aria-haspopup="dialog"
        aria-expanded={open}
        className={cx(
          "flex h-9 max-w-[260px] items-center gap-2 rounded-lg border px-3 text-sm transition-colors",
          selected.length ? "border-accent bg-accent-soft text-foreground" : "border-border bg-surface text-foreground hover:border-border-strong"
        )}
      >
        {loading ? <Spinner className="h-3.5 w-3.5" /> : <FileText className="h-4 w-4 shrink-0 text-muted-foreground" />}
        <span className="truncate">{label}</span>
        <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
      </button>
      {open && (
        <div role="dialog" aria-label="Choose documents" className="absolute left-0 top-11 z-50 w-80 max-w-[90vw] overflow-hidden rounded-xl border border-border bg-surface shadow-[var(--shadow-lg)] animate-zoom-in">
          <div className="border-b border-border p-3">
            <p className="text-sm font-semibold text-foreground">Answer from</p>
            <p className="text-xs text-muted-foreground">Pick documents to limit the search, or use all of them.</p>
            <div className="relative mt-2.5">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
              <input
                autoFocus
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                placeholder="Search documents…"
                aria-label="Search documents"
                className="input h-8 pl-8 text-[13px]"
              />
            </div>
          </div>
          <ul className="max-h-72 overflow-y-auto p-1.5">
            {shown.length === 0 ? (
              <li className="px-3 py-6 text-center text-xs text-muted-foreground">{docs.length ? "No matches" : "This knowledge base has no documents yet."}</li>
            ) : (
              shown.map((d) => {
                const usable = d.status === "indexed";
                const checked = selected.includes(d.id);
                return (
                  <li key={d.id}>
                    <label
                      className={cx(
                        "flex items-center gap-2.5 rounded-lg px-2.5 py-2",
                        usable ? "cursor-pointer hover:bg-surface-muted" : "cursor-not-allowed opacity-55"
                      )}
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        disabled={!usable}
                        onChange={() => toggle(d.id)}
                        className="h-4 w-4 shrink-0 accent-[#a8801f]"
                      />
                      {d.meta_info?.source_url ? <Globe className="h-3.5 w-3.5 shrink-0 text-muted-foreground" /> : <FileText className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />}
                      <span className="min-w-0 flex-1 truncate text-sm text-foreground" title={d.filename}>{d.filename}</span>
                      {!usable && <span className={cx("badge", d.status === "failed" ? "badge-danger" : "badge-info")}>{d.status === "failed" ? "Failed" : "Indexing"}</span>}
                    </label>
                  </li>
                );
              })
            )}
          </ul>
          <div className="flex items-center justify-between gap-2 border-t border-border px-3 py-2.5">
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => onChange(ready.map((d) => d.id))} disabled={!ready.length}>
              Select all
            </button>
            <div className="flex gap-2">
              <button type="button" className="btn btn-secondary btn-sm" onClick={() => onChange([])} disabled={!selected.length}>
                Use all documents
              </button>
              <button type="button" className="btn btn-primary btn-sm" onClick={() => setOpen(false)}>
                Done
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
