"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Database, Play, TrendingUp } from "lucide-react";
import { api, EvaluationResult, KnowledgeBase } from "@/lib/api";
import { errorMessage, useApi, useRequireAuth } from "@/lib/hooks";
import { SVGLineChart } from "@/components/analytics-charts";
import { Alert, Card, EmptyState, KBSelect, PageHeader, Skeleton, Spinner, StatCard } from "@/components/ui";

type Metric = "faithfulness" | "context_precision" | "context_recall" | "answer_relevancy";

const METRICS: Array<{ key: Metric; name: string; desc: string; color: string }> = [
  { key: "faithfulness", name: "Faithfulness", desc: "Is every claim in the answer supported by the retrieved context?", color: "#1f7a4d" },
  { key: "context_precision", name: "Context precision", desc: "Are the relevant chunks ranked above the irrelevant ones?", color: "#2c5d8a" },
  { key: "context_recall", name: "Context recall", desc: "Did retrieval find everything needed for the reference answer?", color: "#a8801f" },
  { key: "answer_relevancy", name: "Answer relevancy", desc: "Does the answer address the question directly, without tangents?", color: "#1a1a1a" },
];

export default function EvaluationPage() {
  const allowed = useRequireAuth();
  const router = useRouter();
  const kbsQuery = useApi<KnowledgeBase[]>(allowed ? "/knowledge-bases" : null, api.listKBs);
  const kbs = kbsQuery.data ?? [];
  const [pickedKB, setPickedKB] = useState("");
  const selectedKBId = pickedKB || kbs[0]?.id || "";

  const evalsQuery = useApi<EvaluationResult[]>(
    selectedKBId ? `/evaluation/results/${selectedKBId}` : null,
    () => api.getEvaluationHistory(selectedKBId)
  );
  const evals = evalsQuery.data ?? [];
  const [evaluating, setEvaluating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async () => {
    if (!selectedKBId) return;
    setError(null);
    setEvaluating(true);
    try {
      const result = await api.runEvaluation(selectedKBId);
      evalsQuery.setData((prev) => [...(prev ?? []), result]);
    } catch (err) {
      setError(errorMessage(err, "Failed to run the RAGAS audit."));
    } finally {
      setEvaluating(false);
    }
  };

  if (!allowed) return null;

  // A metric the backend could not compute is null: drop it from the series
  // rather than plotting a confident 0% nobody measured.
  const series = (m: Metric) =>
    evals
      .filter((e) => e[m] !== null && e[m] !== undefined)
      .map((e) => {
        const d = new Date(e.created_at);
        return { label: `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`, value: (e[m] as number) * 100 };
      });
  const latest = evals.length ? evals[evals.length - 1] : null;

  return (
    <div className="space-y-6 animate-fade-in">
      <PageHeader
        eyebrow="Quality"
        title="Evaluation"
        description="RAGAS audits score how truthful, relevant and complete the answers in a knowledge base are."
        actions={
          <button className="btn btn-primary" onClick={run} disabled={evaluating || !selectedKBId}>
            {evaluating ? <Spinner /> : <Play className="h-4 w-4" />}
            {evaluating ? "Running audit…" : "Run audit"}
          </button>
        }
      />

      {latest?.method === "heuristic" && (
        <Alert tone="warning" title="Heuristic scores">
          These come from local word-overlap estimates, not RAGAS&apos; model-judged metrics. Set <code className="font-mono">GEMINI_API_KEY</code> or{" "}
          <code className="font-mono">OPENAI_API_KEY</code> with available quota and run the audit again.
        </Alert>
      )}
      {(error || evalsQuery.error) && <Alert tone="danger" onClose={() => setError(null)}>{error || evalsQuery.error}</Alert>}

      {kbsQuery.loading ? (
        <Skeleton className="h-20" />
      ) : kbs.length === 0 ? (
        <Card>
          <EmptyState icon={Database} title="No knowledge bases" description="Create one and chat with it before running an audit."
            action={<button className="btn btn-primary" onClick={() => router.push("/knowledge-bases")}>Go to knowledge bases</button>} />
        </Card>
      ) : (
        <>
          <Card className="p-5"><div className="max-w-md"><KBSelect kbs={kbs} value={selectedKBId} onChange={setPickedKB} label="Knowledge base to audit" /></div></Card>

          {evalsQuery.loading ? (
            <div className="grid gap-4 md:grid-cols-2">{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-72" />)}</div>
          ) : evals.length === 0 ? (
            <Card>
              <EmptyState icon={TrendingUp} title="No audits yet" description="Run an audit to score recent conversations in this knowledge base."
                action={<button className="btn btn-primary" onClick={run} disabled={evaluating}>{evaluating && <Spinner />}Run first audit</button>} />
            </Card>
          ) : (
            <>
              <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
                {METRICS.map((m) => {
                  const v = latest?.[m.key];
                  return <StatCard key={m.key} label={m.name} value={v == null ? "—" : `${((v as number) * 100).toFixed(1)}%`} hint="Latest audit" />;
                })}
              </div>
              <div className="grid gap-4 md:grid-cols-2">
                {METRICS.map((m) => (
                  <SVGLineChart key={m.key} title={m.name} description={m.desc} data={series(m.key)} color={m.color} gradientId={`ev-${m.key}`} unit="%" />
                ))}
              </div>
            </>
          )}
        </>
      )}
    </div>
  );
}
