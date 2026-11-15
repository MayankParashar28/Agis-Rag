"use client";

import { cx } from "@/components/ui";

/** One "used / limit" bar. A limit of 0 means unlimited. */
export function UsageMeter({ label, used, limit, format = (n) => n.toLocaleString() }: {
  label: string;
  used: number;
  limit: number;
  format?: (n: number) => string;
}) {
  const unlimited = !limit;
  const pct = unlimited ? 0 : Math.min(100, Math.round((used / limit) * 100));
  const tone = pct >= 100 ? "bg-danger" : pct >= 80 ? "bg-warning" : "bg-accent";
  return (
    <div>
      <div className="mb-1.5 flex items-baseline justify-between gap-2 text-sm">
        <span className="font-medium text-foreground">{label}</span>
        <span className="tabular-nums text-muted-foreground">
          {format(used)}
          {unlimited ? " · no limit" : ` of ${format(limit)}`}
        </span>
      </div>
      <div
        className="h-2 overflow-hidden rounded-full bg-surface-muted"
        role="progressbar"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={unlimited ? undefined : limit}
        aria-valuenow={used}
      >
        {!unlimited && <div className={cx("h-full rounded-full transition-[width] duration-500", tone)} style={{ width: `${pct}%` }} />}
      </div>
    </div>
  );
}

export function compactNumber(n: number): string {
  return n >= 1_000_000 ? `${(n / 1_000_000).toFixed(1)}M` : n >= 10_000 ? `${Math.round(n / 1000)}k` : n.toLocaleString();
}

export function resetsIn(iso: string): string {
  const ms = new Date(iso).getTime() - Date.now();
  if (!Number.isFinite(ms) || ms <= 0) return "soon";
  const h = Math.floor(ms / 3_600_000);
  const m = Math.floor((ms % 3_600_000) / 60_000);
  return h ? `${h} h ${m} min` : `${m} min`;
}
