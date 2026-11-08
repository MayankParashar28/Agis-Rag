"use client";

import { useState } from "react";
import { ArrowUpRight, Clock, Cpu, FileText, Search, SearchCode, TrendingDown } from "lucide-react";
import { api, KnowledgeBase } from "@/lib/api";
import { errorMessage, useApi, useRequireAuth } from "@/lib/hooks";
import { Alert, Card, CardHeader, EmptyState, KBSelect, PageHeader, Skeleton, Spinner, StatCard } from "@/components/ui";

interface TraceChunk {
  content: string;
  filename: string;
  page_number: number | null;
  chunk_id?: string;
  score?: number;
  rrf_score?: number;
  similarity_score?: number;
  rerank_score?: number;
}

export default function RetrievalPage() {
  const allowed = useRequireAuth();
  const kbsQuery = useApi<KnowledgeBase[]>(allowed ? "/knowledge-bases" : null, api.listKBs);
  const kbs = kbsQuery.data ?? [];
  const [pickedKB, setPickedKB] = useState("");
  const selectedKBId = pickedKB || kbs[0]?.id || "";

  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [preRerank, setPreRerank] = useState<TraceChunk[] | null>(null);
  const [postRerank, setPostRerank] = useState<TraceChunk[]>([]);
  const [latencies, setLatencies] = useState<{ retrieval_ms: number; rerank_ms: number; total_ms: number } | null>(null);

  const run = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim() || !selectedKBId) return;
    setError(null);
    setLoading(true);
    try {
      const res = await api.debugRetrieval(selectedKBId, query.trim());
      setPreRerank(res.pre_rerank || []);
      setPostRerank(res.post_rerank || []);
      setLatencies(res.latencies || null);
    } catch (err) {
      setError(errorMessage(err, "Retrieval trace failed."));
    } finally {
      setLoading(false);
    }
  };

  if (!allowed) return null;

  // Where did each reranked chunk sit before reranking?
  const rankBefore = (c: TraceChunk) => {
    const i = (preRerank ?? []).findIndex((p) => (p.chunk_id && p.chunk_id === c.chunk_id) || p.content === c.content);
    return i === -1 ? null : i + 1;
  };

  return (
    <div className="space-y-6 animate-fade-in">
      <PageHeader
        eyebrow="Diagnostics"
        title="Retrieval Viewer"
        description="See exactly which passages hybrid search finds and how the reranker reorders them before they reach the model."
      />

      <Card className="p-5">
        <form onSubmit={run} className="grid gap-4 md:grid-cols-[minmax(0,1fr)_minmax(0,2fr)_auto] md:items-end">
          {kbsQuery.loading ? <Skeleton className="h-16" /> : <KBSelect kbs={kbs} value={selectedKBId} onChange={setPickedKB} />}
          <div>
            <label htmlFor="trace-q" className="label">Query</label>
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <input id="trace-q" required value={query} onChange={(e) => setQuery(e.target.value)} placeholder="What does the policy say about refunds?" className="input pl-9" />
            </div>
          </div>
          <button className="btn btn-primary" disabled={loading || !selectedKBId || !query.trim()}>
            {loading ? <Spinner /> : <SearchCode className="h-4 w-4" />}Run trace
          </button>
        </form>
      </Card>

      {error && <Alert tone="danger">{error}</Alert>}

      {latencies && (
        <div className="grid gap-4 sm:grid-cols-3">
          <StatCard label="Hybrid retrieval" value={`${latencies.retrieval_ms} ms`} icon={Clock} />
          <StatCard label="Reranking" value={`${latencies.rerank_ms} ms`} icon={TrendingDown} />
          <StatCard label="Total" value={`${latencies.total_ms} ms`} icon={Cpu} />
        </div>
      )}

      {preRerank === null ? (
        <Card>
          <EmptyState icon={SearchCode} title="Run a query to see the trace" description="Results from both stages appear side by side." />
        </Card>
      ) : preRerank.length === 0 ? (
        <Card><EmptyState icon={Search} title="Nothing matched" description="No chunk in this knowledge base matched the query." /></Card>
      ) : (
        <div className="grid gap-6 lg:grid-cols-2">
          <Card className="overflow-hidden">
            <CardHeader title="1 · Hybrid retrieval" description="Dense vectors + keyword search, fused (top 10)" />
            <ol className="divide-y divide-border">
              {preRerank.map((c, i) => (
                <li key={i} className="px-5 py-3.5">
                  <div className="mb-1.5 flex items-center justify-between text-xs">
                    <span className="badge badge-neutral">#{i + 1}</span>
                    <span className="font-mono text-muted-foreground">{(c.score ?? c.rrf_score ?? 0).toFixed(4)}</span>
                  </div>
                  <p className="line-clamp-2 text-sm text-foreground">{c.content}</p>
                  <p className="mt-1.5 flex items-center gap-1.5 text-xs text-muted-foreground">
                    <FileText className="h-3 w-3" /><span className="truncate">{c.filename}</span>{c.page_number != null && <span>· p.{c.page_number}</span>}
                  </p>
                </li>
              ))}
            </ol>
          </Card>

          <Card className="overflow-hidden">
            <CardHeader title="2 · Reranked context" description="What the model actually reads" />
            <ol className="divide-y divide-border">
              {postRerank.map((c, i) => {
                const before = rankBefore(c);
                return (
                  <li key={i} className="px-5 py-3.5">
                    <div className="mb-1.5 flex items-center justify-between gap-2 text-xs">
                      <div className="flex items-center gap-1.5">
                        <span className="badge badge-accent">#{i + 1}</span>
                        {before !== null && before !== i + 1 && (
                          <span className={before > i + 1 ? "badge badge-success" : "badge badge-neutral"}>
                            {before > i + 1 && <ArrowUpRight className="h-3 w-3" />}was #{before}
                          </span>
                        )}
                      </div>
                      <span className="font-mono text-muted-foreground">{((c.similarity_score ?? 0) * 100).toFixed(1)}%</span>
                    </div>
                    <p className="text-sm leading-relaxed text-foreground">{c.content}</p>
                    <p className="mt-1.5 flex items-center gap-1.5 text-xs text-muted-foreground">
                      <FileText className="h-3 w-3" /><span className="truncate">{c.filename}</span>{c.page_number != null && <span>· p.{c.page_number}</span>}
                    </p>
                  </li>
                );
              })}
            </ol>
          </Card>
        </div>
      )}
    </div>
  );
}
