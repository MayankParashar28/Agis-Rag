"use client";

import { useEffect, useState } from "react";
import { CheckCircle2, ChevronDown, ListChecks, Play, Plus, Sparkles, Trash2, XCircle } from "lucide-react";
import { api, GoldenQuestion, GoldenRun } from "@/lib/api";
import { errorMessage } from "@/lib/hooks";
import { Alert, Card, CardHeader, EmptyState, Modal, Skeleton, Spinner, StatCard, cx } from "@/components/ui";

const pct = (v: number | null | undefined) => (v == null ? "—" : `${(v * 100).toFixed(0)}%`);

export default function GoldenPanel({ kbId }: { kbId: string }) {
  // Remount per knowledge base so every piece of state starts fresh.
  return <GoldenPanelInner key={kbId} kbId={kbId} />;
}

function GoldenPanelInner({ kbId }: { kbId: string }) {
  const [questions, setQuestions] = useState<GoldenQuestion[] | null>(null);
  const [runs, setRuns] = useState<GoldenRun[] | null>(null);
  const [notice, setNotice] = useState<{ tone: "danger" | "success" | "warning"; text: string } | null>(null);
  const [running, setRunning] = useState(false);
  const [adding, setAdding] = useState(false);
  const [suggesting, setSuggesting] = useState(false);
  const [drafts, setDrafts] = useState<Array<{ question: string; expected_answer: string }>>([]);
  const [form, setForm] = useState({ question: "", expected_answer: "" });
  const [openRun, setOpenRun] = useState<string | null>(null);
  const [openResult, setOpenResult] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [q, r] = await Promise.all([api.listGoldenQuestions(kbId), api.goldenRunHistory(kbId)]);
        if (cancelled) return;
        setQuestions(q);
        setRuns(r);
        setOpenRun(r[0]?.id ?? null);
      } catch (e) {
        if (!cancelled) setNotice({ tone: "danger", text: errorMessage(e, "Could not load golden questions.") });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [kbId]);

  const add = async (q: string, a: string) => {
    const created = await api.addGoldenQuestion(kbId, q, a);
    setQuestions((prev) => [...(prev ?? []), created]);
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.question.trim() || !form.expected_answer.trim()) return;
    try {
      await add(form.question, form.expected_answer);
      setForm({ question: "", expected_answer: "" });
      setAdding(false);
    } catch (err) {
      setNotice({ tone: "danger", text: errorMessage(err, "Could not add the question.") });
    }
  };

  const suggest = async () => {
    setSuggesting(true);
    setNotice(null);
    try {
      const res = await api.suggestGoldenQuestions(kbId, 5);
      setDrafts(res.items);
      if (!res.items.length) setNotice({ tone: "warning", text: "No suggestions could be drafted. Index a document first." });
    } catch (e) {
      setNotice({ tone: "danger", text: errorMessage(e, "Could not draft questions.") });
    } finally {
      setSuggesting(false);
    }
  };

  const run = async () => {
    setRunning(true);
    setNotice(null);
    try {
      const res = await api.runGolden(kbId);
      setRuns((prev) => [res, ...(prev ?? [])]);
      setOpenRun(res.id);
      setNotice({
        tone: res.pass ? "success" : "warning",
        text: `${res.pass ? "Passed" : "Below threshold"}: ${res.passed}/${res.total} questions scored ≥ ${Math.round(res.threshold * 100)}% (average ${pct(res.overall_score)}).`,
      });
    } catch (e) {
      setNotice({ tone: "danger", text: errorMessage(e, "The run failed.") });
    } finally {
      setRunning(false);
    }
  };

  const remove = async (q: GoldenQuestion) => {
    if (!confirm("Remove this golden question?")) return;
    try {
      await api.deleteGoldenQuestion(q.id);
      setQuestions((prev) => (prev ?? []).filter((x) => x.id !== q.id));
    } catch (e) {
      setNotice({ tone: "danger", text: errorMessage(e, "Could not remove the question.") });
    }
  };

  const latest = runs?.[0];
  const trend = (runs ?? []).slice().reverse();

  return (
    <div className="space-y-4">
      {notice && <Alert tone={notice.tone} onClose={() => setNotice(null)}>{notice.text}</Alert>}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Golden questions" value={questions ? questions.length : <Skeleton className="h-7 w-10" />} />
        <StatCard label="Latest score" value={latest ? pct(latest.overall_score) : "—"} hint={latest ? `${latest.passed}/${latest.total} passed · threshold ${Math.round(latest.threshold * 100)}%` : "No runs yet"} />
        <StatCard label="Correctness" value={latest ? pct(latest.correctness) : "—"} hint="Agreement with expected answers" />
        <StatCard label="Faithfulness" value={latest ? pct(latest.faithfulness) : "—"} hint={latest ? `Judged by ${latest.method === "llm" ? "a model" : latest.method === "heuristic" ? "word overlap" : "model + overlap"}` : undefined} />
      </div>

      {trend.length > 1 && (
        <Card className="p-5">
          <p className="mb-3 text-sm font-semibold">Score over runs</p>
          <div className="flex h-24 items-end gap-1.5">
            {trend.map((r) => (
              <div key={r.id} className="group relative flex-1" title={`${new Date(r.created_at).toLocaleString()} · ${pct(r.overall_score)}`}>
                <div className={cx("w-full rounded-t", r.pass ? "bg-success" : "bg-danger")} style={{ height: `${Math.max(4, (r.overall_score ?? 0) * 96)}px` }} />
              </div>
            ))}
          </div>
          <div className="mt-1 flex justify-between text-[11px] text-muted-foreground">
            <span>{new Date(trend[0].created_at).toLocaleDateString()}</span>
            <span>{new Date(trend[trend.length - 1].created_at).toLocaleDateString()}</span>
          </div>
        </Card>
      )}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
        <Card className="overflow-hidden">
          <CardHeader
            title="Question set"
            description="Questions with a known good answer. Run them after every change."
            actions={
              <>
                <button className="btn btn-secondary btn-sm" onClick={suggest} disabled={suggesting}>{suggesting ? <Spinner className="h-3.5 w-3.5" /> : <Sparkles className="h-3.5 w-3.5" />}Draft from documents</button>
                <button className="btn btn-primary btn-sm" onClick={() => setAdding(true)}><Plus className="h-3.5 w-3.5" />Add</button>
              </>
            }
          />
          {drafts.length > 0 && (
            <div className="space-y-2 border-b border-border bg-accent-soft/40 p-4">
              <p className="text-xs font-semibold">Drafted suggestions · review, then add the good ones</p>
              {drafts.map((d, i) => (
                <div key={i} className="rounded-lg border border-border bg-surface p-3 text-sm">
                  <p className="font-medium">{d.question}</p>
                  <p className="mt-1 text-xs text-muted-foreground">{d.expected_answer}</p>
                  <div className="mt-2 flex gap-2">
                    <button className="btn btn-primary btn-sm" onClick={async () => { await add(d.question, d.expected_answer); setDrafts((p) => p.filter((_, j) => j !== i)); }}>Add</button>
                    <button className="btn btn-ghost btn-sm" onClick={() => setDrafts((p) => p.filter((_, j) => j !== i))}>Skip</button>
                  </div>
                </div>
              ))}
            </div>
          )}
          {questions === null ? (
            <div className="space-y-2 p-4">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-12" />)}</div>
          ) : questions.length === 0 ? (
            <EmptyState icon={ListChecks} title="No golden questions yet" description="Add a few questions with the answer you expect, or draft them from the documents." />
          ) : (
            <ul className="divide-y divide-border">
              {questions.map((q) => (
                <li key={q.id} className="flex items-start gap-3 px-4 py-3">
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium">{q.question}</p>
                    <p className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">{q.expected_answer}</p>
                  </div>
                  <button className="icon-btn icon-btn-danger" onClick={() => remove(q)} aria-label="Remove question"><Trash2 className="h-4 w-4" /></button>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card className="overflow-hidden">
          <CardHeader
            title="Runs"
            description="Each run answers every question with the real pipeline and scores it."
            actions={<button className="btn btn-primary btn-sm" onClick={run} disabled={running || !questions?.length}>{running ? <Spinner className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}{running ? "Running…" : "Run now"}</button>}
          />
          {runs === null ? (
            <div className="space-y-2 p-4">{[0, 1].map((i) => <Skeleton key={i} className="h-12" />)}</div>
          ) : runs.length === 0 ? (
            <EmptyState icon={Play} title="No runs yet" description="Runs also happen nightly from GitHub Actions once the secrets are set (see README)." />
          ) : (
            <ul className="divide-y divide-border">
              {runs.map((r) => (
                <li key={r.id}>
                  <button className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-surface-muted/60" onClick={() => setOpenRun(openRun === r.id ? null : r.id)}>
                    {r.pass ? <CheckCircle2 className="h-4 w-4 shrink-0 text-success" /> : <XCircle className="h-4 w-4 shrink-0 text-danger" />}
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium">{pct(r.overall_score)} · {r.passed}/{r.total} passed</p>
                      <p className="text-xs text-muted-foreground">{new Date(r.created_at).toLocaleString()} · {r.method}{r.usage?.cost_usd ? ` · $${r.usage.cost_usd.toFixed(4)}` : ""}</p>
                    </div>
                    <ChevronDown className={cx("h-4 w-4 text-muted-foreground transition-transform", openRun === r.id && "rotate-180")} />
                  </button>
                  {openRun === r.id && (
                    <ul className="divide-y divide-border border-t border-border bg-background">
                      {r.results.map((res) => (
                        <li key={res.question_id} className="px-4 py-2.5">
                          <button className="flex w-full items-start gap-3 text-left" onClick={() => setOpenResult(openResult === res.question_id ? null : res.question_id)}>
                            <span className={cx("badge shrink-0 tabular-nums", res.passed ? "badge-success" : "badge-danger")}>{pct(res.score)}</span>
                            <span className="min-w-0 flex-1 text-sm">{res.question}</span>
                          </button>
                          {openResult === res.question_id && (
                            <div className="ml-14 mt-2 space-y-2 text-xs">
                              <div className="flex flex-wrap gap-2"><span className="badge badge-neutral">correctness {pct(res.correctness)}</span><span className="badge badge-neutral">faithfulness {pct(res.faithfulness)}</span><span className="badge badge-neutral">recall {pct(res.context_recall)}</span></div>
                              <p><span className="font-semibold">Expected:</span> {res.expected_answer}</p>
                              <p className="whitespace-pre-wrap"><span className="font-semibold">Got:</span> {res.answer}</p>
                              {res.reason && <p className="text-muted-foreground">Judge: {res.reason}</p>}
                              {res.sources.length > 0 && <p className="text-muted-foreground">Sources: {res.sources.map((s) => `${s.source_doc}${s.page ? ` p.${s.page}` : ""}`).join("; ")}</p>}
                            </div>
                          )}
                        </li>
                      ))}
                    </ul>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <Modal open={adding} onClose={() => setAdding(false)} title="Add a golden question" description="Write the answer you would accept as correct.">
        <form onSubmit={submit} className="space-y-4">
          <div>
            <label htmlFor="gq" className="label">Question</label>
            <input id="gq" className="input" required value={form.question} onChange={(e) => setForm({ ...form, question: e.target.value })} placeholder="What is the refund window?" />
          </div>
          <div>
            <label htmlFor="ga" className="label">Expected answer</label>
            <textarea id="ga" className="input resize-none" rows={3} required value={form.expected_answer} onChange={(e) => setForm({ ...form, expected_answer: e.target.value })} placeholder="30 days from purchase for unused items." />
          </div>
          <div className="flex justify-end gap-2">
            <button type="button" className="btn btn-secondary" onClick={() => setAdding(false)}>Cancel</button>
            <button className="btn btn-primary">Add question</button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
