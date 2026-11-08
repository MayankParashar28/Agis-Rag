"use client";

import { ReactNode, useEffect, useRef } from "react";
import { AlertTriangle, CheckCircle2, Info, Loader2, X, XCircle } from "lucide-react";
import type { IndexingProgress } from "@/lib/api";

export function cx(...parts: Array<string | false | null | undefined>) {
  return parts.filter(Boolean).join(" ");
}

export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow?: string;
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0">
        {eyebrow && <p className="eyebrow mb-2">{eyebrow}</p>}
        <h1 className="page-title">{title}</h1>
        {description && <p className="mt-2 max-w-2xl text-sm text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return <section className={cx("card", className)}>{children}</section>;
}

export function CardHeader({ title, description, actions }: { title: ReactNode; description?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border px-5 py-4">
      <div className="min-w-0">
        <h2 className="text-[15px] font-semibold text-foreground">{title}</h2>
        {description && <p className="mt-0.5 text-xs text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cx("h-4 w-4 animate-spin", className)} aria-hidden />;
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cx("skeleton", className)} aria-hidden />;
}

export function SkeletonRows({ rows = 4 }: { rows?: number }) {
  return (
    <div className="space-y-3 p-5" aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} className="h-10 w-full" />
      ))}
    </div>
  );
}

type Tone = "info" | "success" | "warning" | "danger";
const toneIcon = { info: Info, success: CheckCircle2, warning: AlertTriangle, danger: XCircle };
const toneClass: Record<Tone, string> = {
  info: "bg-info-soft text-info border-[#cfdeed]",
  success: "bg-success-soft text-success border-[#c5e5d3]",
  warning: "bg-warning-soft text-warning border-[#f1dcb8]",
  danger: "bg-danger-soft text-danger border-[#f3c3be]",
};

export function Alert({
  tone = "info",
  title,
  children,
  onClose,
  action,
}: {
  tone?: Tone;
  title?: string;
  children?: ReactNode;
  onClose?: () => void;
  action?: ReactNode;
}) {
  const Icon = toneIcon[tone];
  return (
    <div role={tone === "danger" ? "alert" : "status"} className={cx("flex items-start gap-3 rounded-xl border px-4 py-3 text-sm animate-fade-in", toneClass[tone])}>
      <Icon className="mt-0.5 h-4 w-4 shrink-0" />
      <div className="min-w-0 flex-1">
        {title && <p className="font-semibold">{title}</p>}
        {children && <div className={cx(title && "mt-0.5", "text-[13px] leading-relaxed opacity-90")}>{children}</div>}
      </div>
      {action}
      {onClose && (
        <button onClick={onClose} className="shrink-0 rounded-md p-0.5 opacity-70 hover:opacity-100" aria-label="Dismiss">
          <X className="h-4 w-4" />
        </button>
      )}
    </div>
  );
}

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
}: {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  description?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-14 text-center">
      <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-surface-muted">
        <Icon className="h-5 w-5 text-muted-foreground" />
      </div>
      <h3 className="text-base font-semibold text-foreground">{title}</h3>
      {description && <p className="mt-1 max-w-sm text-sm text-muted-foreground">{description}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

export function StatCard({
  label,
  value,
  hint,
  icon: Icon,
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  icon?: React.ComponentType<{ className?: string }>;
}) {
  return (
    <div className="card p-5">
      <div className="flex items-center justify-between">
        <span className="text-[13px] font-medium text-muted-foreground">{label}</span>
        {Icon && <Icon className="h-4 w-4 text-muted-foreground" />}
      </div>
      <div className="mt-3 text-2xl font-semibold tracking-tight text-foreground tabular-nums">{value}</div>
      {hint && <div className="mt-1 text-xs text-muted-foreground">{hint}</div>}
    </div>
  );
}

const statusMap: Record<string, { cls: string; label: string }> = {
  indexed: { cls: "badge-success", label: "Ready" },
  processing: { cls: "badge-info", label: "Indexing" },
  failed: { cls: "badge-danger", label: "Failed" },
};

export function StatusBadge({ status }: { status: string }) {
  const s = statusMap[status] || { cls: "badge-neutral", label: status };
  return (
    <span className={cx("badge", s.cls)}>
      {status === "processing" ? <Spinner className="h-3 w-3" /> : <span className="h-1.5 w-1.5 rounded-full bg-current" />}
      {s.label}
    </span>
  );
}

/** Live indexing progress bar for one document. */
export function IndexingBar({ progress, compact }: { progress?: IndexingProgress; compact?: boolean }) {
  // No live record (older backend, or Redis unreachable): show that work is
  // happening without inventing a percentage.
  if (!progress) {
    return (
      <div className={cx("w-full", compact ? "min-w-[140px]" : "")}>
        <div className="mb-1 flex items-center gap-1.5 text-[11px] font-medium text-foreground">
          <Spinner className="h-3 w-3 text-accent" /> Indexing…
        </div>
        <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-muted" role="progressbar" aria-label="Indexing in progress">
          <div className="h-full w-1/3 rounded-full bg-accent progress-indeterminate" />
        </div>
      </div>
    );
  }
  const pct = progress.percent ?? 2;
  const failed = progress.stage === "failed";
  const done = progress.stage === "done";
  return (
    <div className={cx("w-full", compact ? "min-w-[140px]" : "")}>
      <div className="mb-1 flex items-center justify-between gap-2 text-[11px]">
        <span className={cx("truncate font-medium", failed ? "text-danger" : "text-foreground")}>
          {progress.label}
        </span>
        <span className="tabular-nums text-muted-foreground">{Math.round(pct)}%</span>
      </div>
      <div
        className="h-1.5 w-full overflow-hidden rounded-full bg-surface-muted"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(pct)}
        aria-label="Indexing progress"
      >
        <div
          className={cx(
            "h-full rounded-full transition-[width] duration-500 ease-out",
            failed ? "bg-danger" : done ? "bg-success" : "bg-accent progress-active"
          )}
          style={{ width: `${Math.max(3, pct)}%` }}
        />
      </div>
      {!compact && progress.message && (
        <p className={cx("mt-1 truncate text-[11px]", failed ? "text-danger" : "text-muted-foreground")} title={progress.message}>
          {progress.message}
        </p>
      )}
    </div>
  );
}

/** Accessible modal: Esc closes, focus moves in and returns on close. */
export function Modal({
  open,
  onClose,
  title,
  description,
  children,
  size = "md",
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: ReactNode;
  children: ReactNode;
  size?: "md" | "lg" | "xl";
}) {
  const panelRef = useRef<HTMLDivElement>(null);
  // Keep the latest onClose without re-running the effect: callers pass an
  // inline arrow, and re-running on every render used to pull focus out of
  // whatever input the user was typing in.
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  });
  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement as HTMLElement | null;
    // Focus the first field if there is one, otherwise the dialog itself.
    const first = panelRef.current?.querySelector<HTMLElement>("input, textarea, select");
    (first ?? panelRef.current)?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onCloseRef.current();
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      previous?.focus?.();
    };
  }, [open]);

  if (!open) return null;
  const width = size === "xl" ? "max-w-5xl" : size === "lg" ? "max-w-3xl" : "max-w-md";
  return (
    <div className="fixed inset-0 z-[100] flex items-end justify-center p-0 sm:items-center sm:p-4" role="dialog" aria-modal="true" aria-label={title}>
      <div className="absolute inset-0 bg-[#1a1a1a]/30" onClick={onClose} />
      <div
        ref={panelRef}
        tabIndex={-1}
        className={cx(
          "relative flex max-h-[90dvh] w-full flex-col rounded-t-2xl border border-border bg-surface shadow-[var(--shadow-lg)] outline-none animate-zoom-in sm:rounded-2xl",
          width
        )}
      >
        <div className="flex items-start justify-between gap-4 border-b border-border px-5 py-4">
          <div className="min-w-0">
            <h2 className="text-base font-semibold text-foreground">{title}</h2>
            {description && <p className="mt-0.5 text-xs text-muted-foreground">{description}</p>}
          </div>
          <button onClick={onClose} className="icon-btn -mr-1" aria-label="Close">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">{children}</div>
      </div>
    </div>
  );
}

export function KBSelect({
  kbs,
  value,
  onChange,
  label = "Knowledge base",
  id = "kb-select",
}: {
  kbs: Array<{ id: string; name: string }>;
  value: string;
  onChange: (id: string) => void;
  label?: string;
  id?: string;
}) {
  return (
    <div className="min-w-0">
      <label htmlFor={id} className="label">
        {label}
      </label>
      <select id={id} value={value} onChange={(e) => onChange(e.target.value)} className="input pr-8">
        {kbs.map((kb) => (
          <option key={kb.id} value={kb.id}>
            {kb.name}
          </option>
        ))}
      </select>
    </div>
  );
}
