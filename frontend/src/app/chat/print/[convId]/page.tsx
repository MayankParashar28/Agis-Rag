"use client";

import { use, useEffect, useState } from "react";
import { api, Conversation, Message } from "@/lib/api";
import { useRequireAuth } from "@/lib/hooks";
import MarkdownRenderer from "@/components/MarkdownRenderer";

/**
 * Printable view of a conversation. "Save as PDF" in the browser's print
 * dialog produces the PDF; citations are listed under each answer.
 */
export default function PrintConversationPage({ params }: { params: Promise<{ convId: string }> }) {
  const { convId } = use(params);
  const allowed = useRequireAuth();
  const [messages, setMessages] = useState<Message[] | null>(null);
  const [conv, setConv] = useState<Conversation | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!allowed) return;
    Promise.all([api.listMessages(convId), api.listConversations()])
      .then(([msgs, convs]) => {
        setMessages(msgs);
        setConv(convs.find((c) => c.id === convId) ?? null);
        setTimeout(() => window.print(), 400);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Could not load the conversation."));
  }, [allowed, convId]);

  if (!allowed) return null;

  return (
    <div className="mx-auto max-w-3xl bg-white px-8 py-10 text-[#1a1a1a] print:px-0 print:py-0">
      <style>{`@media print { @page { margin: 18mm; } aside, nav, header.app { display: none !important; } body { background: #fff !important; } }`}</style>
      <div className="mb-8 flex items-start justify-between gap-4 border-b border-[#e3ddd3] pb-4">
        <div>
          <p className="text-xs uppercase tracking-widest text-[#66625c]">Agis RAG · conversation</p>
          <h1 className="mt-1 font-serif text-2xl">{conv?.title ?? "Conversation"}</h1>
          <p className="mt-1 text-xs text-[#66625c]">Exported {new Date().toLocaleString()}</p>
        </div>
        <button onClick={() => window.print()} className="btn btn-primary btn-sm print:hidden">Print / Save as PDF</button>
      </div>
      {error && <p className="text-sm text-[#b42318]">{error}</p>}
      {messages === null && !error && <p className="text-sm text-[#66625c]">Loading…</p>}
      <div className="space-y-6">
        {messages?.map((m) => (
          <section key={m.id} className="break-inside-avoid">
            <p className="mb-1 text-xs font-semibold uppercase tracking-wider text-[#66625c]">{m.sender === "user" ? "You" : "Assistant"}</p>
            {m.sender === "user" ? (
              <p className="text-[15px] font-medium">{m.content}</p>
            ) : (
              <>
                <MarkdownRenderer content={m.content} />
                {m.citations && m.citations.length > 0 && (
                  <ol className="mt-2 space-y-0.5 text-xs text-[#66625c]">
                    {m.citations.map((c, i) => (
                      <li key={i}>
                        [{c.index ?? i + 1}] {c.source_doc}
                        {c.page != null && `, page ${c.page}`}
                        {c.url && ` — ${c.url}`}
                      </li>
                    ))}
                  </ol>
                )}
              </>
            )}
          </section>
        ))}
      </div>
    </div>
  );
}
