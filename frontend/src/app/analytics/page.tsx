"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { BarChart3, Clock, Sparkles, Activity, AlertTriangle, ShieldCheck } from "lucide-react";
import { api, authStorage, ObservabilityLog } from "@/lib/api";
import { SVGLineChart } from "@/components/analytics-charts";

export default function AnalyticsPage() {
  const router = useRouter();
  const [logs, setLogs] = useState<ObservabilityLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const token = authStorage.getToken();
    const user = authStorage.getUser();
    if (!token) {
      router.push("/login");
      return;
    }

    if (!user || user.role !== "admin") {
      router.push("/knowledge-bases");
      return;
    }

    const fetchLogs = async () => {
      try {
        const res = await api.getObservabilityLogs();
        setLogs(res);
      } catch (err: any) {
        setError(err.message || "Failed to load observability logs.");
      } finally {
        setLoading(false);
      }
    };

    fetchLogs();
  }, [router]);


  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[50vh] text-foreground">
        <div className="text-center space-y-2">
          <div className="w-8 h-8 border-4 border-primary border-t-transparent rounded-full animate-spin mx-auto" />
          <p className="text-sm text-text-muted">Loading analytics...</p>
        </div>
      </div>
    );
  }

  // Format data for SVGLineCharts
  const latencyData = logs.map((log) => ({
    label: log.timestamp.split(" ")[1] || log.timestamp,
    value: log.query_latency
  }));

  const retrievalData = logs.map((log) => ({
    label: log.timestamp.split(" ")[1] || log.timestamp,
    value: log.retrieval_latency
  }));

  const hallucinationData = logs.map((log) => ({
    label: log.timestamp.split(" ")[1] || log.timestamp,
    value: log.hallucination_rate
  }));

  const scoreData = logs.map((log) => ({
    label: log.timestamp.split(" ")[1] || log.timestamp,
    value: log.retrieval_score * 100
  }));

  return (
    <div className="space-y-8 animate-fade-in">
      <div>
        <h1 className="text-3xl font-extrabold text-foreground tracking-tight">Analytics & Observability</h1>
        <p className="text-text-muted mt-1">Real-time telemetry, model latencies, and hallucination rates</p>
      </div>

      {error && (
        <div className="flex items-start space-x-2 p-4 rounded-2xl bg-red-500/10 border border-red-500/20 text-red-400 text-sm">
          <AlertTriangle className="w-5 h-5 shrink-0 mt-0.5" />
          <span>{error}</span>
        </div>
      )}

      {/* Grid of charts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <SVGLineChart
          title="Overall Query Latency"
          data={latencyData}
          color="#6366f1"
          gradientId="latency-grad"
          unit="ms"
        />
        <SVGLineChart
          title="Qdrant Index Retrieval Latency"
          data={retrievalData}
          color="#06b6d4"
          gradientId="retrieval-grad"
          unit="ms"
        />
        <SVGLineChart
          title="Simulated Hallucination Rate"
          data={hallucinationData}
          color="#f43f5e"
          gradientId="hallucination-grad"
          unit="%"
        />
        <SVGLineChart
          title="Average Vector Retrieval Score"
          data={scoreData}
          color="#10b981"
          gradientId="score-grad"
          unit="%"
        />
      </div>

      {/* Audit Logs table */}
      <div className="glass border border-card-border rounded-3xl p-6 overflow-hidden">
        <div className="flex justify-between items-center mb-4">
          <h3 className="text-lg font-bold text-foreground">Audit Execution Logs</h3>
          <span className="flex items-center space-x-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-emerald-500/10 border border-emerald-500/20 text-emerald-400">
            <ShieldCheck className="w-3.5 h-3.5" />
            <span>Secure Logging Active</span>
          </span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-card-border/50 text-text-muted font-semibold">
                <th className="py-3 pr-4">Timestamp</th>
                <th className="py-3 px-4">Query Latency</th>
                <th className="py-3 px-4">Vector Retrieval</th>
                <th className="py-3 px-4">Hallucination</th>
                <th className="py-3 pl-4 text-right">Cosine Score</th>
              </tr>
            </thead>
            <tbody>
              {logs.slice(-10).reverse().map((log, idx) => (
                <tr key={idx} className="border-b border-card-border/30 text-foreground hover:bg-card-border/10 transition-colors">
                  <td className="py-4 pr-4 font-mono text-xs">{log.timestamp}</td>
                  <td className="py-4 px-4 font-semibold text-violet-400">{log.query_latency.toFixed(0)} ms</td>
                  <td className="py-4 px-4 text-cyan-400 font-medium">{log.retrieval_latency.toFixed(0)} ms</td>
                  <td className="py-4 px-4">
                    <span className={`inline-flex items-center text-xs font-semibold py-0.5 px-2 rounded-full border ${
                      log.hallucination_rate > 20
                        ? "text-red-400 bg-red-500/10 border-red-500/20"
                        : "text-emerald-400 bg-emerald-500/10 border-emerald-500/20"
                    }`}>
                      {log.hallucination_rate.toFixed(1)}%
                    </span>
                  </td>
                  <td className="py-4 pl-4 text-right text-emerald-400 font-bold font-mono">{(log.retrieval_score * 100).toFixed(2)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
