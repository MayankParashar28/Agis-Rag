"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  TrendingUp,
  Database,
  Play,
  CheckCircle,
  Clock,
  Sparkles,
  Info,
  AlertTriangle,
  Heart
} from "lucide-react";
import { api, authStorage, KnowledgeBase, EvaluationResult } from "@/lib/api";
import { SVGLineChart } from "@/components/analytics-charts";

export default function EvaluationPage() {
  const router = useRouter();

  const [kbs, setKbs] = useState<KnowledgeBase[]>([]);
  const [selectedKBId, setSelectedKBId] = useState("");
  const [evals, setEvals] = useState<EvaluationResult[]>([]);
  const [loading, setLoading] = useState(true);
  const [evaluating, setEvaluating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const token = authStorage.getToken();
    if (!token) {
      router.push("/login");
      return;
    }

    api.listKBs()
      .then((kbList) => {
        setKbs(kbList);
        if (kbList.length > 0) {
          setSelectedKBId(kbList[0].id);
        } else {
          setLoading(false);
        }
      })
      .catch((err) => {
        setError(err.message || "Failed to load knowledge bases.");
        setLoading(false);
      });
  }, [router]);

  useEffect(() => {
    if (!selectedKBId) return;
    fetchHistory();
  }, [selectedKBId]);

  const fetchHistory = async () => {
    setLoading(true);
    try {
      const history = await api.getEvaluationHistory(selectedKBId);
      setEvals(history);
    } catch (err: any) {
      setError(err.message || "Failed to load evaluation history.");
    } finally {
      setLoading(false);
    }
  };

  const handleRunEvaluation = async () => {
    if (!selectedKBId) return;
    setError(null);
    setEvaluating(true);

    try {
      await api.runEvaluation(selectedKBId);
      await fetchHistory();
    } catch (err: any) {
      setError(err.message || "Failed to run RAGAS evaluation.");
    } finally {
      setEvaluating(false);
    }
  };

  // Format metric history for the line charts.
  //
  // A metric the backend could not compute is null. Plotting that as 0 would
  // show a confident "0%" for a score nobody measured, so those runs are
  // dropped from this metric's series instead - a missing point, not a fake one.
  const formatData = (metric: "faithfulness" | "context_precision" | "context_recall" | "answer_relevancy") => {
    return evals
      .filter((item) => item[metric] !== null && item[metric] !== undefined)
      .map((item) => {
        const date = new Date(item.created_at);
        const label = `${date.getMonth() + 1}/${date.getDate()} ${date.getHours()}:${date.getMinutes()}`;
        return {
          label,
          value: (item[metric] as number) * 100
        };
      });
  };

  const metricCards = [
    {
      name: "Faithfulness",
      desc: "Measures factual consistency of the generated answer against the retrieved context. High score indicates no hallucinations.",
      data: formatData("faithfulness"),
      color: "#6366f1",
      gradId: "faith-grad"
    },
    {
      name: "Context Precision",
      desc: "Measures whether the relevant chunks are ranked higher in the retrieved list. Evaluates the vector and reranking quality.",
      data: formatData("context_precision"),
      color: "#06b6d4",
      gradId: "prec-grad"
    },
    {
      name: "Context Recall",
      desc: "Measures whether all necessary details to formulate the ground truth answer were successfully retrieved in the context.",
      data: formatData("context_recall"),
      color: "#8b5cf6",
      gradId: "recall-grad"
    },
    {
      name: "Answer Relevancy",
      desc: "Measures how directly the generated response addresses the user's question, penalizing redundancy or off-topic tangents.",
      data: formatData("answer_relevancy"),
      color: "#10b981",
      gradId: "relev-grad"
    }
  ];

  // Scores produced by local lexical-overlap proxies are not RAGAS metrics.
  // Say so in the UI rather than letting them read as LLM-judged results.
  const latestMethod = evals.length > 0 ? evals[evals.length - 1].method : null;

  return (
    <div className="space-y-8 animate-fade-in">
      {latestMethod === "heuristic" && (
        <div className="glass p-4 rounded-2xl border border-amber-500/40 text-sm text-amber-700">
          <span className="font-bold">Heuristic scores.</span>{" "}
          These numbers come from local lexical-overlap proxies, not from RAGAS&apos;
          LLM-judged metrics. RAGAS needs a judge model it can reach: check that{" "}
          <code className="font-mono">GEMINI_API_KEY</code> or{" "}
          <code className="font-mono">OPENAI_API_KEY</code> is set and the provider still
          has quota, then run the audit again.
        </div>
      )}
      <div className="flex flex-col gap-4 sm:flex-row sm:justify-between sm:items-center sm:gap-6">
        <div>
          <h1 className="text-3xl font-extrabold text-foreground tracking-tight">Retrieval Evaluation</h1>
          <p className="text-text-muted mt-1">Audit truthfulness, relevance, and precision of RAG answers</p>
        </div>
        <button
          onClick={handleRunEvaluation}
          disabled={evaluating || !selectedKBId}
          className="flex items-center space-x-2 px-5 py-3 bg-secondary hover:bg-cyan-500 text-black rounded-2xl font-bold transition-all duration-200 text-sm cursor-pointer shadow-lg shadow-secondary/25 disabled:opacity-50"
        >
          {evaluating ? (
            <>
              <div className="w-4 h-4 border-2 border-black border-t-transparent rounded-full animate-spin" />
              <span>Analyzing Dataset...</span>
            </>
          ) : (
            <>
              <Play className="w-4 h-4 text-black" fill="currentColor" />
              <span>Run RAGAS Audit</span>
            </>
          )}
        </button>
      </div>

      {/* Select KB Bar */}
      <div className="glass p-6 rounded-3xl border border-card-border flex items-center justify-between">
        <div className="flex items-center space-x-3">
          <div className="bg-primary/20 p-2.5 rounded-xl border border-primary/30 text-primary">
            <Database className="w-5 h-5" />
          </div>
          <div>
            <label className="block text-xs font-semibold text-text-muted uppercase tracking-wider mb-1">
              Select Knowledge Base to Audit
            </label>
            <select
              value={selectedKBId}
              onChange={(e) => setSelectedKBId(e.target.value)}
              className="bg-transparent text-foreground font-bold text-lg focus:outline-none cursor-pointer"
            >
              {kbs.map((kb) => (
                <option key={kb.id} value={kb.id} className="bg-card text-foreground">
                  {kb.name}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {error && (
        <div className="flex items-start space-x-2 p-4 rounded-2xl bg-red-500/10 border border-red-500/20 text-red-400 text-sm">
          <AlertTriangle className="w-5 h-5 shrink-0 mt-0.5" />
          <span>{error}</span>
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center min-h-[40vh] text-foreground">
          <div className="text-center space-y-2">
            <div className="w-8 h-8 border-4 border-primary border-t-transparent rounded-full animate-spin mx-auto" />
            <p className="text-sm text-text-muted">Loading metrics...</p>
          </div>
        </div>
      ) : kbs.length === 0 ? (
        <div className="glass p-12 rounded-3xl border border-card-border text-center">
          <Database className="w-12 h-12 text-text-muted mx-auto mb-4" />
          <h3 className="text-lg font-bold text-foreground mb-2">No Knowledge Bases Found</h3>
          <p className="text-sm text-text-muted max-w-sm mx-auto mb-6">
            You must create a Knowledge Base and upload documents before running RAGAS evaluations.
          </p>
          <button
            onClick={() => router.push("/knowledge-bases")}
            className="px-5 py-3 bg-primary hover:bg-primary-hover text-background rounded-2xl font-semibold transition-all duration-200 text-sm cursor-pointer"
          >
            Go to Knowledge Bases
          </button>
        </div>
      ) : evals.length === 0 ? (
        <div className="glass p-12 rounded-3xl border border-card-border text-center">
          <TrendingUp className="w-12 h-12 text-text-muted mx-auto mb-4" />
          <h3 className="text-lg font-bold text-foreground mb-2">No Evaluations Run Yet</h3>
          <p className="text-sm text-text-muted max-w-sm mx-auto mb-6">
            Execute a RAGAS audit to score faithfulness, recall, and precision across user conversations in this Knowledge Base.
          </p>
          <button
            onClick={handleRunEvaluation}
            disabled={evaluating}
            className="px-5 py-3 bg-primary hover:bg-primary-hover text-background rounded-2xl font-semibold transition-all duration-200 text-sm cursor-pointer"
          >
            Trigger Initial Audit
          </button>
        </div>
      ) : (
        <div className="space-y-8">
          {/* Charts Grid */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {metricCards.map((metric) => (
              <div key={metric.name} className="space-y-4">
                <SVGLineChart
                  title={metric.name}
                  data={metric.data}
                  color={metric.color}
                  gradientId={metric.gradId}
                  unit="%"
                />
                <div className="glass px-6 py-4 rounded-2xl border border-card-border/50 flex items-start space-x-2.5">
                  <Info className="w-4 h-4 text-primary shrink-0 mt-0.5" />
                  <p className="text-xs text-text-muted leading-relaxed">{metric.desc}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
