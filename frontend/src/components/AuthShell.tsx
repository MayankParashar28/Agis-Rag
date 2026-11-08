import { ReactNode } from "react";
import { FileSearch, Quote, ShieldCheck, Zap } from "lucide-react";

/** Shared layout for sign-in and sign-up: brand panel + form. No remote images, so it paints instantly. */
export default function AuthShell({ title, subtitle, children, footer }: { title: string; subtitle: string; children: ReactNode; footer: ReactNode }) {
  return (
    <div className="flex min-h-screen bg-background">
      <aside className="relative hidden w-[44%] max-w-[640px] flex-col justify-between overflow-hidden border-r border-border bg-surface-muted p-12 lg:flex">
        <div
          aria-hidden
          className="absolute inset-0 opacity-60"
          style={{
            backgroundImage:
              "radial-gradient(circle at 20% 15%, rgba(168,128,31,0.16), transparent 45%), radial-gradient(circle at 85% 80%, rgba(26,26,26,0.07), transparent 40%)",
          }}
        />
        <span className="relative font-serif text-2xl tracking-tight">
          Agis <span className="italic text-accent">RAG</span>
        </span>
        <div className="relative">
          <h1 className="font-serif text-5xl leading-[1.05] tracking-tight text-foreground">
            Answers you can <span className="italic text-accent">trace</span> back to the page.
          </h1>
          <ul className="mt-10 space-y-4 text-sm text-foreground">
            {[
              { icon: FileSearch, text: "Hybrid search with reranking across your documents" },
              { icon: Quote, text: "Every answer cites the exact passage, one click away" },
              { icon: Zap, text: "Live indexing progress and instant repeat answers" },
              { icon: ShieldCheck, text: "Guarded against instructions hidden in documents" },
            ].map(({ icon: Icon, text }) => (
              <li key={text} className="flex items-center gap-3">
                <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-surface">
                  <Icon className="h-4 w-4 text-accent" />
                </span>
                {text}
              </li>
            ))}
          </ul>
        </div>
        <p className="relative text-xs text-muted-foreground">Retrieval-augmented generation for your knowledge.</p>
      </aside>

      <main className="flex flex-1 items-center justify-center px-6 py-12">
        <div className="w-full max-w-sm animate-fade-in">
          <span className="mb-10 block font-serif text-2xl tracking-tight lg:hidden">
            Agis <span className="italic text-accent">RAG</span>
          </span>
          <h2 className="font-serif text-3xl tracking-tight text-foreground">{title}</h2>
          <p className="mt-2 text-sm text-muted-foreground">{subtitle}</p>
          <div className="mt-8">{children}</div>
          <div className="mt-8 border-t border-border pt-6 text-sm text-muted-foreground">{footer}</div>
        </div>
      </main>
    </div>
  );
}
