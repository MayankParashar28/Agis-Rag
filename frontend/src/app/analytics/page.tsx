"use client";

import { Activity } from "lucide-react";
import { api, ObservabilityLog } from "@/lib/api";
import { useApi, useRequireAuth } from "@/lib/hooks";
import { SVGLineChart } from "@/components/analytics-charts";
import { Alert, Card, CardHeader, EmptyState, PageHeader, Skeleton, cx } from "@/components/ui";
import CostPanel from "@/components/analytics/CostPanel";

export default function AnalyticsPage() {
  const allowed = useRequireAuth({ adminOnly: true });
  const { data, error, loading } = useApi<ObservabilityLog[]>(allowed ? "/analytics/observability" : null, api.getObservabilityLogs);
  const logs = data ?? [];

  if (!allowed) return null;

  const label = (log: ObservabilityLog) => log.timestamp.split(" ")[1] || log.timestamp;
  const series = (fn: (l: ObservabilityLog) => number) => logs.map((l) => ({ label: label(l), value: fn(l) }));

  return (
    <div className="space-y-6 animate-fade-in">
      <PageHeader eyebrow="Admin" title="Analytics" description="Per-query latency, retrieval quality, hallucination rate, and what it all costs." />
      {error && <Alert tone="danger">{error}</Alert>}

      <CostPanel />

      <h2 className="text-base font-semibold">Quality and latency</h2>

      {loading ? (
        <div className="grid gap-4 lg:grid-cols-2">{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-72" />)}</div>
      ) : logs.length === 0 ? (
        <Card>
          <EmptyState icon={Activity} title="No queries logged yet" description="Ask questions in Chat and the telemetry for each answer appears here." />
        </Card>
      ) : (
        <>
          <div className="grid gap-4 lg:grid-cols-2">
            <SVGLineChart title="Query latency" description="End-to-end time per answer" data={series((l) => l.query_latency)} color="#1a1a1a" gradientId="lat" unit="ms" />
            <SVGLineChart title="Retrieval latency" description="Vector + keyword search" data={series((l) => l.retrieval_latency)} color="#2c5d8a" gradientId="ret" unit="ms" />
            <SVGLineChart title="Hallucination rate" description="Lower is better" data={series((l) => l.hallucination_rate * 100)} color="#b42318" gradientId="hal" unit="%" />
            <SVGLineChart title="Retrieval score" description="Average rerank score of used chunks" data={series((l) => l.retrieval_score * 100)} color="#1f7a4d" gradientId="score" unit="%" />
          </div>

          <Card className="overflow-hidden">
            <CardHeader title="Recent queries" description={`Latest ${Math.min(logs.length, 15)} of ${logs.length}`} />
            <div className="overflow-x-auto">
              <table className="table">
                <thead>
                  <tr>
                    <th>Time</th>
                    <th className="text-right">Latency</th>
                    <th className="text-right">Retrieval</th>
                    <th className="text-right">Hallucination</th>
                    <th className="text-right">Score</th>
                  </tr>
                </thead>
                <tbody>
                  {logs.slice(-15).reverse().map((log, idx) => {
                    const hall = log.hallucination_rate * 100;
                    return (
                      <tr key={idx}>
                        <td className="font-mono text-xs text-muted-foreground">{log.timestamp}</td>
                        <td className="text-right tabular-nums">{log.query_latency.toFixed(0)} ms</td>
                        <td className="text-right tabular-nums">{log.retrieval_latency.toFixed(0)} ms</td>
                        <td className="text-right">
                          <span className={cx("badge", hall > 20 ? "badge-danger" : "badge-success")}>{hall.toFixed(1)}%</span>
                        </td>
                        <td className="text-right tabular-nums">{(log.retrieval_score * 100).toFixed(1)}%</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </Card>
        </>
      )}
    </div>
  );
}
