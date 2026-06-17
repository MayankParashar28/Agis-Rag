"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  SearchCode,
  Database,
  Search,
  ChevronRight,
  TrendingDown,
  Cpu,
  Clock,
  Sparkles,
  FileText,
  AlertTriangle
} from "lucide-react";
import { api, authStorage, KnowledgeBase } from "@/lib/api";

export default function RetrievalPage() {
  const router = useRouter();
  
  const [kbs, setKbs] = useState<KnowledgeBase[]>([]);
  const [selectedKBId, setSelectedKBId] = useState("");
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Search Results
  const [preRerank, setPreRerank] = useState<any[]>([]);
  const [postRerank, setPostRerank] = useState<any[]>([]);
  const [latencies, setLatencies] = useState<any>(null);

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
        }
      })
      .catch((err) => setError(err.message || "Failed to load knowledge bases."));
  }, [router]);

  const handleDebugSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim() || !selectedKBId) return;

    setError(null);
    setLoading(true);
    
    try {
      const res = await api.debugRetrieval(selectedKBId, query);
      setPreRerank(res.pre_rerank || []);
      setPostRerank(res.post_rerank || []);
      setLatencies(res.latencies || null);
    } catch (err: any) {
      setError(err.message || "Failed to query retrieval debugger.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-extrabold text-foreground tracking-tight">Retrieval Viewer</h1>
        <p className="text-text-muted mt-1">Visualize and debug the search and BGE reranking pipeline</p>
      </div>

      {/* Query Bar */}
      <div className="glass p-6 rounded-3xl border border-card-border">
        <form onSubmit={handleDebugSearch} className="grid grid-cols-1 md:grid-cols-4 gap-4 items-end">
          <div className="md:col-span-1">
            <label className="block text-[10px] font-bold text-text-muted uppercase tracking-wider mb-2">
              Knowledge Base
            </label>
            <select
              value={selectedKBId}
              onChange={(e) => setSelectedKBId(e.target.value)}
              className="w-full bg-background border border-card-border rounded-2xl py-3 px-4 text-xs text-foreground focus:outline-none focus:border-primary"
            >
              {kbs.map((kb) => (
                <option key={kb.id} value={kb.id}>
                  {kb.name}
                </option>
              ))}
            </select>
          </div>

          <div className="md:col-span-2">
            <label className="block text-[10px] font-bold text-text-muted uppercase tracking-wider mb-2">
              Search Query
            </label>
            <div className="relative">
              <input
                type="text"
                required
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Type your search query..."
                className="w-full pl-11 pr-4 py-3 bg-background border border-card-border rounded-2xl text-foreground placeholder-text-muted focus:outline-none focus:border-primary text-sm"
              />
              <span className="absolute inset-y-0 left-0 pl-4 flex items-center text-text-muted">
                <Search className="w-4 h-4" />
              </span>
            </div>
          </div>

          <div className="md:col-span-1">
            <button
              type="submit"
              disabled={loading || !selectedKBId || !query.trim()}
              className="w-full py-3 bg-primary hover:bg-primary-hover text-background rounded-2xl font-semibold text-sm transition-all duration-200 cursor-pointer disabled:opacity-50 flex justify-center items-center gap-2"
            >
              {loading ? (
                <>
                  <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                  <span>Searching...</span>
                </>
              ) : (
                <>
                  <SearchCode className="w-4 h-4" />
                  <span>Execute Trace</span>
                </>
              )}
            </button>
          </div>
        </form>
      </div>

      {error && (
        <div className="flex items-start space-x-2 p-4 rounded-2xl bg-red-500/10 border border-red-500/20 text-red-400 text-sm">
          <AlertTriangle className="w-5 h-5 shrink-0 mt-0.5" />
          <span>{error}</span>
        </div>
      )}

      {/* Latency Stats Banner */}
      {latencies && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 bg-card/20 border border-card-border p-6 rounded-3xl">
          <div className="flex items-center space-x-3">
            <Clock className="w-5 h-5 text-violet-400" />
            <div>
              <span className="text-[10px] uppercase font-bold text-text-muted block">Retrieval Latency</span>
              <span className="text-lg font-bold text-foreground mt-0.5">{latencies.retrieval_ms} ms</span>
            </div>
          </div>
          <div className="flex items-center space-x-3">
            <TrendingDown className="w-5 h-5 text-cyan-400" />
            <div>
              <span className="text-[10px] uppercase font-bold text-text-muted block">BGE Reranking</span>
              <span className="text-lg font-bold text-foreground mt-0.5">{latencies.rerank_ms} ms</span>
            </div>
          </div>
          <div className="flex items-center space-x-3">
            <Cpu className="w-5 h-5 text-primary" />
            <div>
              <span className="text-[10px] uppercase font-bold text-text-muted block">Total RAG Pipeline</span>
              <span className="text-lg font-bold text-foreground mt-0.5">{latencies.total_ms} ms</span>
            </div>
          </div>
        </div>
      )}

      {preRerank.length > 0 && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
          {/* List 1: Pre Reranking */}
          <div className="glass border border-card-border rounded-3xl p-6 space-y-4">
            <div className="pb-3 border-b border-card-border/50">
              <h3 className="text-base font-bold text-foreground">Hybrid Retrieval (Dense + Sparse)</h3>
              <p className="text-xs text-text-muted mt-0.5">Top 10 retrieved chunks before reranking</p>
            </div>

            <div className="space-y-4">
              {preRerank.map((chunk, idx) => (
                <div key={idx} className="p-4 bg-background/50 border border-card-border/50 rounded-2xl space-y-2">
                  <div className="flex justify-between items-center text-xs">
                    <span className="bg-card px-2.5 py-1 rounded-lg border border-card-border text-text-muted font-bold font-mono">
                      Rank #{idx + 1}
                    </span>
                    <span className="text-primary font-semibold font-mono">
                      Score: {chunk.score ? chunk.score.toFixed(4) : chunk.rrf_score?.toFixed(4)}
                    </span>
                  </div>
                  <p className="text-xs text-foreground line-clamp-2 leading-relaxed bg-card/10 p-2 rounded-xl italic">
                    &ldquo;{chunk.content}&rdquo;
                  </p>
                  <div className="flex items-center space-x-2 text-[10px] text-text-muted">
                    <FileText className="w-3 h-3" />
                    <span className="truncate max-w-[150px]">{chunk.filename}</span>
                    <span className="font-bold">Page {chunk.page_number}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* List 2: Post Reranking */}
          <div className="glass border border-card-border rounded-3xl p-6 space-y-4">
            <div className="pb-3 border-b border-card-border/50">
              <h3 className="text-base font-bold text-foreground">BGE Reranking Filtration</h3>
              <p className="text-xs text-text-muted mt-0.5">Top 5 reranked chunks pushed to LLM Context Window</p>
            </div>

            <div className="space-y-4">
              {postRerank.map((chunk, idx) => (
                <div key={idx} className="p-4 bg-primary/5 border border-primary/20 rounded-2xl space-y-3">
                  <div className="flex justify-between items-center text-xs">
                    <div className="flex items-center space-x-2">
                      <span className="bg-primary/20 px-2.5 py-1 rounded-lg border border-primary/30 text-primary font-bold font-mono">
                        Rank #{idx + 1}
                      </span>
                      {/* Show rank boost comparison if it was lower in pre-rerank */}
                      <span className="text-[10px] text-emerald-400 bg-emerald-500/10 border border-emerald-500/20 px-2 py-0.5 rounded-full font-bold">
                        BGE Boosted
                      </span>
                    </div>
                    <span className="text-emerald-400 font-bold font-mono flex items-center gap-1">
                      <Sparkles className="w-3.5 h-3.5" />
                      <span>Similarity: {(chunk.similarity_score * 100).toFixed(0)}%</span>
                    </span>
                  </div>
                  <p className="text-xs text-foreground leading-relaxed bg-card/25 p-3 rounded-xl border border-card-border/50">
                    {chunk.content}
                  </p>
                  <div className="flex justify-between items-center text-[10px] text-text-muted">
                    <div className="flex items-center space-x-2">
                      <FileText className="w-3 h-3" />
                      <span className="truncate max-w-[150px]">{chunk.filename}</span>
                      <span className="font-bold">Page {chunk.page_number}</span>
                    </div>
                    <span className="font-mono text-card-border/80">Rerank Score: {chunk.rerank_score?.toFixed(2)}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
