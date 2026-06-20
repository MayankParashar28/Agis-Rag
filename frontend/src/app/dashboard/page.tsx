"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Users,
  FileText,
  Layers,
  MessageSquare,
  Clock,
  Award,
  ArrowRight,
  Database,
  Plus,
  Target,
  Compass,
  HelpCircle,
  AlertTriangle,
  ShieldCheck,
  ThumbsUp
} from "lucide-react";
import { api, authStorage, DashboardStats } from "@/lib/api";

export default function DashboardPage() {
  const router = useRouter();
  const [stats, setStats] = useState<DashboardStats | null>(null);
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

    const fetchStats = async () => {
      try {
        const res = await api.getDashboardStats();
        setStats(res);
      } catch (err: any) {
        setError(err.message || "Failed to load dashboard statistics.");
      } finally {
        setLoading(false);
      }
    };

    fetchStats();
  }, [router]);


  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[50vh] text-foreground">
        <div className="text-center space-y-2">
          <div className="w-8 h-8 border-4 border-primary border-t-transparent rounded-full animate-spin mx-auto" />
          <p className="text-sm text-text-muted">Loading metrics...</p>
        </div>
      </div>
    );
  }

  const statCards = [
    { name: "Total Users", value: stats?.total_users, icon: Users, color: "text-blue-400" },
    { name: "Total Documents", value: stats?.total_documents, icon: FileText, color: "text-emerald-400" },
    { name: "Total Index Chunks", value: stats?.total_chunks.toLocaleString(), icon: Layers, color: "text-amber-400" },
    { name: "Total Queries Run", value: stats?.total_queries.toLocaleString(), icon: MessageSquare, color: "text-cyan-400" },
    { name: "Average Latency", value: stats?.average_latency ? `${stats.average_latency.toFixed(2)}s` : "0.00s", icon: Clock, color: "text-violet-400" },
    { name: "Avg Retrieval Score", value: `${((stats?.average_retrieval_score || 0) * 100).toFixed(1)}%`, icon: Award, color: "text-rose-400" },
    { name: "User Satisfaction", value: stats?.user_satisfaction_rate !== undefined ? `${stats.user_satisfaction_rate.toFixed(1)}%` : "100.0%", icon: ThumbsUp, color: "text-pink-400" },
    { name: "Context Precision", value: stats?.average_context_precision !== undefined ? `${(stats.average_context_precision * 100).toFixed(1)}%` : "0.0%", icon: Target, color: "text-indigo-400" },
    { name: "Context Recall", value: stats?.average_context_recall !== undefined ? `${(stats.average_context_recall * 100).toFixed(1)}%` : "0.0%", icon: Compass, color: "text-teal-400" },
    { name: "Answer Relevance", value: stats?.average_answer_relevancy !== undefined ? `${(stats.average_answer_relevancy * 100).toFixed(1)}%` : "0.0%", icon: HelpCircle, color: "text-sky-400" },
    { name: "Hallucination Rate", value: stats?.average_hallucination_rate !== undefined ? `${(stats.average_hallucination_rate * 100).toFixed(1)}%` : "0.0%", icon: AlertTriangle, color: "text-red-400" },
    { name: "Faithfulness", value: stats?.average_faithfulness !== undefined ? `${(stats.average_faithfulness * 100).toFixed(1)}%` : "0.0%", icon: ShieldCheck, color: "text-green-400" },
  ];

  return (
    <div className="space-y-8 animate-fade-in">
      <div>
        <h1 className="text-3xl font-extrabold text-foreground tracking-tight">System Dashboard</h1>
        <p className="text-text-muted mt-1">Overview of your enterprise RAG infrastructure</p>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
        {statCards.map((card) => {
          const Icon = card.icon;
          return (
            <div
              key={card.name}
              className="glass p-6 rounded-3xl border border-card-border accent-glow transition-all duration-300 hover:-translate-y-1 hover:border-card-border/60"
            >
              <div className="flex justify-between items-center">
                <span className="text-sm font-semibold text-text-muted">{card.name}</span>
                <span className={`p-2 rounded-xl bg-card border border-card-border ${card.color}`}>
                  <Icon className="w-5 h-5" />
                </span>
              </div>
              <div className="mt-4">
                <span className="text-3xl font-extrabold text-foreground">{card.value}</span>
              </div>
            </div>
          );
        })}
      </div>

      {/* Actions & Shortcut panels */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Quick Setup Panel */}
        <div className="glass p-8 rounded-3xl border border-card-border flex flex-col justify-between">
          <div>
            <span className="inline-flex items-center px-3 py-1 rounded-full text-xs font-semibold bg-primary/20 border border-primary/30 text-primary mb-4">
              Step-by-Step
            </span>
            <h3 className="text-xl font-bold text-foreground mb-2">Build Your Knowledge Base</h3>
            <p className="text-sm text-text-muted leading-relaxed mb-6">
              Create a isolated database namespace, upload PDF documents, and run semantic indices to enable agentic retrieval.
            </p>
          </div>
          <div className="flex gap-4">
            <button
              onClick={() => router.push("/knowledge-bases")}
              className="flex items-center space-x-2 px-5 py-3 bg-primary hover:bg-primary-hover text-background rounded-2xl font-semibold transition-all duration-200 text-sm cursor-pointer shadow-lg shadow-primary/20"
            >
              <Plus className="w-4 h-4" />
              <span>Create KB</span>
            </button>
            <button
              onClick={() => router.push("/upload")}
              className="flex items-center space-x-2 px-5 py-3 bg-background hover:bg-card-border/20 border border-card-border text-foreground rounded-2xl font-semibold transition-all duration-200 text-sm cursor-pointer"
            >
              <span>Upload Document</span>
              <ArrowRight className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Live Chat Panel */}
        <div className="glass p-8 rounded-3xl border border-card-border flex flex-col justify-between">
          <div>
            <span className="inline-flex items-center px-3 py-1 rounded-full text-xs font-semibold bg-secondary/20 border border-secondary/30 text-secondary mb-4">
              Agentic RAG
            </span>
            <h3 className="text-xl font-bold text-foreground mb-2">Interactive Chat Engine</h3>
            <p className="text-sm text-text-muted leading-relaxed mb-6">
              Ask questions across your uploaded knowledge bases. Agis uses LangGraph workflow loops, hybrid search, and BGE reranking to deliver exact answers.
            </p>
          </div>
          <div>
            <button
              onClick={() => router.push("/chat")}
              className="w-full flex items-center justify-center space-x-2 px-5 py-3 bg-secondary hover:bg-cyan-500 text-black rounded-2xl font-bold transition-all duration-200 text-sm cursor-pointer shadow-lg shadow-secondary/20"
            >
              <span>Launch Chat Console</span>
              <MessageSquare className="w-4 h-4 text-black" />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
