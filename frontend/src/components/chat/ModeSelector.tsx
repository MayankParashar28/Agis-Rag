"use client";

import { Columns3, ListChecks, Zap } from "lucide-react";
import type { AnswerMode } from "@/lib/api";
import { cx } from "@/components/ui";

const MODES: Array<{ id: AnswerMode; label: string; hint: string; icon: React.ComponentType<{ className?: string }> }> = [
  { id: "quick", label: "Quick", hint: "Two or three sentences", icon: Zap },
  { id: "detailed", label: "Detailed", hint: "Complete answer with structure", icon: ListChecks },
  { id: "compare", label: "Compare", hint: "Side-by-side across the selected documents (pick at least two)", icon: Columns3 },
];

export function ModeSelector({ value, onChange, selectedDocs }: { value: AnswerMode; onChange: (m: AnswerMode) => void; selectedDocs: number }) {
  return (
    <div role="radiogroup" aria-label="Answer mode" className="flex rounded-full border border-border bg-surface p-0.5">
      {MODES.map((m) => {
        const Icon = m.icon;
        const active = value === m.id;
        const needsDocs = m.id === "compare" && selectedDocs < 2;
        return (
          <button
            key={m.id}
            role="radio"
            aria-checked={active}
            onClick={() => onChange(m.id)}
            title={needsDocs ? `${m.hint}. Select ${2 - selectedDocs} more document${2 - selectedDocs > 1 ? "s" : ""}.` : m.hint}
            className={cx(
              "flex h-7 items-center gap-1.5 rounded-full px-2.5 text-xs font-semibold transition-colors",
              active ? "bg-foreground text-background" : "text-muted-foreground hover:text-foreground",
              needsDocs && !active && "opacity-60"
            )}
          >
            <Icon className="h-3.5 w-3.5" />
            <span className="hidden md:inline">{m.label}</span>
          </button>
        );
      })}
    </div>
  );
}
