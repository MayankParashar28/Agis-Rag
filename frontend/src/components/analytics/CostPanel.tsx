"use client";

import { useState } from "react";
import { Coins } from "lucide-react";
import { api, CostReport } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { SVGLineChart } from "@/components/analytics-charts";
import { Alert, Card, CardHeader, EmptyState, Skeleton, StatCard, cx } from "@/components/ui";

const usd = (v: number) => (v >= 1 ? `$${v.toFixed(2)}` : v > 0 ? `$${v.toFixed(4)}` : "$0");
const k = (n: number) => (n >= 1_000_000 ? `${(n / 1_000_000).toFixed(1)}M` : n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n));

export default function CostPanel() {
  const [days, setDays] = useState(30);
  const { data, error, loading } = useApi<CostReport>(`/analytics/costs?days=${days}`, () => api.getCosts(days));

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold">Tokens and cost</h2>
          <p className="text-xs text-muted-foreground">Estimated from the pricing table; override with <code className="font-mono">LLM_PRICING_JSON</code>.</p>
        </div>
        <div className="flex rounded-lg border border-border bg-surface p-0.5 text-xs">
          {[7, 30, 90].map((d) => (
            <button key={d} onClick={() => setDays(d)} className={cx("rounded-md px-2.5 py-1 font-semibold", days === d ? "bg-foreground text-background" : "text-muted-foreground hover:text-foreground")}>{d} days</button>
          ))}
        </div>
      </div>
      {error && <Alert tone="danger">{error}</Alert>}
      {loading || !data ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-24" />)}</div>
      ) : data.totals.queries === 0 ? (
        <Card><EmptyState icon={Coins} title="No usage yet" description="Costs appear here once questions have been answered." /></Card>
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <StatCard label="Total cost" value={usd(data.totals.cost_usd)} hint={`${usd(data.totals.avg_cost_per_query_usd)} per query`} />
            <StatCard label="Queries" value={data.totals.queries.toLocaleString()} hint={`${data.totals.cached} served from cache (free)`} />
            <StatCard label="Input tokens" value={k(data.totals.prompt_tokens)} />
            <StatCard label="Output tokens" value={k(data.totals.completion_tokens)} />
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            <SVGLineChart title="Cost per day" data={data.per_day.map((d) => ({ label: d.day.slice(5), value: d.cost_usd }))} color="#a8801f" gradientId="cost" unit="$" />
            <SVGLineChart title="Queries per day" data={data.per_day.map((d) => ({ label: d.day.slice(5), value: d.queries }))} color="#1a1a1a" gradientId="qpd" unit="" />
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            <Card className="overflow-hidden">
              <CardHeader title="By knowledge base" />
              <table className="table">
                <thead><tr><th>Knowledge base</th><th className="text-right">Queries</th><th className="text-right">Tokens</th><th className="text-right">Cost</th></tr></thead>
                <tbody>
                  {data.per_kb.map((r) => (
                    <tr key={r.kb_id ?? r.kb_name}><td className="font-medium">{r.kb_name}</td><td className="text-right tabular-nums">{r.queries}</td><td className="text-right tabular-nums">{k(r.prompt_tokens + r.completion_tokens)}</td><td className="text-right tabular-nums">{usd(r.cost_usd)}</td></tr>
                  ))}
                </tbody>
              </table>
            </Card>
            <Card className="overflow-hidden">
              <CardHeader title="By model" />
              <table className="table">
                <thead><tr><th>Model</th><th className="text-right">Queries</th><th className="text-right">Tokens</th><th className="text-right">Cost</th></tr></thead>
                <tbody>
                  {data.per_model.map((r) => (
                    <tr key={r.model}><td className="font-mono text-xs">{r.model}</td><td className="text-right tabular-nums">{r.queries}</td><td className="text-right tabular-nums">{k(r.prompt_tokens + r.completion_tokens)}</td><td className="text-right tabular-nums">{usd(r.cost_usd)}</td></tr>
                  ))}
                </tbody>
              </table>
            </Card>
          </div>
        </>
      )}
    </section>
  );
}
