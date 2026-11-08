"use client";

import Link from "next/link";
import {
  AlertTriangle, ArrowRight, Award, Clock, Compass, FileText, HelpCircle, Layers, MessageSquare, ShieldCheck, Target, ThumbsUp, Users,
} from "lucide-react";
import { api, DashboardStats } from "@/lib/api";
import { useApi, useRequireAuth } from "@/lib/hooks";
import { Alert, PageHeader, Skeleton, StatCard } from "@/components/ui";

const pct = (v?: number | null) => (v === undefined || v === null ? "—" : `${(v * 100).toFixed(1)}%`);

export default function DashboardPage() {
  const allowed = useRequireAuth({ adminOnly: true });
  const { data: stats, error, loading } = useApi<DashboardStats>(allowed ? "/analytics/dashboard" : null, api.getDashboardStats);

  if (!allowed) return null;

  const usage = [
    { label: "Users", value: stats?.total_users?.toLocaleString(), icon: Users },
    { label: "Documents", value: stats?.total_documents?.toLocaleString(), icon: FileText },
    { label: "Indexed chunks", value: stats?.total_chunks?.toLocaleString(), icon: Layers },
    { label: "Queries answered", value: stats?.total_queries?.toLocaleString(), icon: MessageSquare },
  ];
  const quality = [
    { label: "Average latency", value: stats ? `${(stats.average_latency || 0).toFixed(2)}s` : undefined, icon: Clock },
    { label: "Retrieval score", value: stats ? pct(stats.average_retrieval_score) : undefined, icon: Award },
    {
      label: "User satisfaction",
      value: stats ? (stats.user_satisfaction_rate != null ? `${stats.user_satisfaction_rate.toFixed(1)}%` : "No ratings") : undefined,
      icon: ThumbsUp,
    },
    { label: "Faithfulness", value: stats ? pct(stats.average_faithfulness) : undefined, icon: ShieldCheck },
    { label: "Context precision", value: stats ? pct(stats.average_context_precision) : undefined, icon: Target },
    { label: "Context recall", value: stats ? pct(stats.average_context_recall) : undefined, icon: Compass },
    { label: "Answer relevance", value: stats ? pct(stats.average_answer_relevancy) : undefined, icon: HelpCircle },
    { label: "Hallucination rate", value: stats ? pct(stats.average_hallucination_rate) : undefined, icon: AlertTriangle },
  ];

  const grid = (items: typeof usage) => (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      {items.map((c) => (
        <StatCard key={c.label} label={c.label} icon={c.icon} value={loading || c.value === undefined ? <Skeleton className="h-7 w-20" /> : c.value} />
      ))}
    </div>
  );

  return (
    <div className="space-y-8 animate-fade-in">
      <PageHeader eyebrow="Admin" title="Dashboard" description="Usage and answer quality across the whole platform." />
      {error && <Alert tone="danger">{error}</Alert>}

      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-foreground">Usage</h2>
        {grid(usage)}
      </section>

      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-foreground">Answer quality</h2>
        {grid(quality)}
      </section>

      <div className="grid gap-4 lg:grid-cols-3">
        {[
          { href: "/knowledge-bases", title: "Knowledge bases", text: "Create collections and manage their documents." },
          { href: "/analytics", title: "Analytics", text: "Latency, retrieval and hallucination trends per query." },
          { href: "/evaluation", title: "Evaluation", text: "Run RAGAS audits to score faithfulness and recall." },
        ].map((l) => (
          <Link key={l.href} href={l.href} className="card card-hover group flex items-center justify-between gap-4 p-5">
            <div>
              <p className="font-semibold text-foreground">{l.title}</p>
              <p className="mt-1 text-sm text-muted-foreground">{l.text}</p>
            </div>
            <ArrowRight className="h-4 w-4 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5 group-hover:text-foreground" />
          </Link>
        ))}
      </div>
    </div>
  );
}
