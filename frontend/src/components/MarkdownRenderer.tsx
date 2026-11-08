"use client";

import React, { memo, useMemo } from "react";
import ReactMarkdown, { Components } from "react-markdown";
import remarkGfm from "remark-gfm";
// PrismLight + a handful of registered grammars instead of the full Prism
// build: the full build ships every language (~1 MB) to every chat visitor.
import { PrismLight as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneLight } from "react-syntax-highlighter/dist/esm/styles/prism";
import python from "react-syntax-highlighter/dist/esm/languages/prism/python";
import javascript from "react-syntax-highlighter/dist/esm/languages/prism/javascript";
import typescript from "react-syntax-highlighter/dist/esm/languages/prism/typescript";
import jsx from "react-syntax-highlighter/dist/esm/languages/prism/jsx";
import tsx from "react-syntax-highlighter/dist/esm/languages/prism/tsx";
import json from "react-syntax-highlighter/dist/esm/languages/prism/json";
import bash from "react-syntax-highlighter/dist/esm/languages/prism/bash";
import sql from "react-syntax-highlighter/dist/esm/languages/prism/sql";
import yaml from "react-syntax-highlighter/dist/esm/languages/prism/yaml";
import java from "react-syntax-highlighter/dist/esm/languages/prism/java";
import go from "react-syntax-highlighter/dist/esm/languages/prism/go";
import css from "react-syntax-highlighter/dist/esm/languages/prism/css";

const LANGS: Record<string, unknown> = { python, py: python, javascript, js: javascript, typescript, ts: typescript, jsx, tsx, json, bash, sh: bash, shell: bash, sql, yaml, yml: yaml, java, go, css };
Object.entries(LANGS).forEach(([name, lang]) => SyntaxHighlighter.registerLanguage(name, lang));

interface MarkdownRendererProps {
  content: string;
  /** Called with the 1-based source number when an inline [Source N] marker is clicked. */
  onCite?: (index: number) => void;
}

const CITE_RE = /\[(?:Source|Sources)\s+(\d+(?:\s*(?:,|and|&)\s*(?:Source\s+)?\d+)*)\]/gi;

/** Turn "[Source 2]" / "[Source 1, 3]" into links the renderer shows as citation chips. */
function linkCitations(text: string) {
  return text.replace(CITE_RE, (_m, nums: string) =>
    nums
      .split(/\s*(?:,|and|&)\s*(?:Source\s+)?/i)
      .filter(Boolean)
      .map((n) => `[${n.trim()}](#cite-${n.trim()})`)
      .join("")
  );
}

function MarkdownRendererImpl({ content, onCite }: MarkdownRendererProps) {
  const text = useMemo(() => (onCite ? linkCitations(content) : content), [content, onCite]);

  const components = useMemo<Components>(
    () => ({
      code({ className, children, ...props }) {
        const match = /language-(\w+)/.exec(className || "");
        const raw = String(children ?? "");
        const isBlock = Boolean(match) || raw.includes("\n");
        if (!isBlock) {
          return <code className="rounded-md bg-surface-muted px-1.5 py-0.5 font-mono text-[0.85em]">{children}</code>;
        }
        const lang = match?.[1]?.toLowerCase();
        return (
          <div className="my-3 overflow-hidden rounded-xl border border-border bg-[#fafaf9]">
            <div className="flex items-center justify-between border-b border-border px-3 py-1.5">
              <span className="font-mono text-[11px] text-muted-foreground">{lang || "text"}</span>
              <button onClick={() => navigator.clipboard.writeText(raw)} className="text-[11px] font-medium text-muted-foreground hover:text-foreground">
                Copy
              </button>
            </div>
            {lang && LANGS[lang] ? (
              <SyntaxHighlighter
                {...(props as Record<string, unknown>)}
                style={oneLight}
                language={lang}
                PreTag="div"
                customStyle={{ margin: 0, padding: "0.875rem 1rem", background: "transparent", fontSize: "0.8125rem" }}
              >
                {raw.replace(/\n$/, "")}
              </SyntaxHighlighter>
            ) : (
              <pre className="overflow-x-auto px-4 py-3.5 font-mono text-[0.8125rem]">{raw.replace(/\n$/, "")}</pre>
            )}
          </div>
        );
      },
      table({ children }) {
        return (
          <div className="my-3 overflow-x-auto rounded-xl border border-border">
            <table className="min-w-full text-sm">{children}</table>
          </div>
        );
      },
      thead({ children }) {
        return <thead className="bg-surface-muted">{children}</thead>;
      },
      th({ children }) {
        return <th className="px-3 py-2 text-left text-xs font-semibold text-muted-foreground">{children}</th>;
      },
      td({ children }) {
        return <td className="border-t border-border px-3 py-2 align-top">{children}</td>;
      },
      a({ href, children }) {
        const cite = href?.match(/^#cite-(\d+)$/);
        if (cite && onCite) {
          const n = Number(cite[1]);
          return (
            <button type="button" className="cite-ref" onClick={() => onCite(n)} aria-label={`Open source ${n}`} title={`Open source ${n}`}>
              {n}
            </button>
          );
        }
        return (
          <a href={href} target="_blank" rel="noopener noreferrer" className="font-medium text-accent-hover underline-offset-2 hover:underline">
            {children}
          </a>
        );
      },
      blockquote({ children }) {
        return <blockquote className="my-3 border-l-2 border-accent pl-4 text-muted-foreground">{children}</blockquote>;
      },
      ul({ children }) {
        return <ul className="my-2 list-disc space-y-1 pl-5">{children}</ul>;
      },
      ol({ children }) {
        return <ol className="my-2 list-decimal space-y-1 pl-5">{children}</ol>;
      },
      h1({ children }) {
        return <h1 className="mb-2 mt-4 text-xl font-semibold">{children}</h1>;
      },
      h2({ children }) {
        return <h2 className="mb-2 mt-4 text-lg font-semibold">{children}</h2>;
      },
      h3({ children }) {
        return <h3 className="mb-1.5 mt-3 text-base font-semibold">{children}</h3>;
      },
      p({ children }) {
        return <p className="my-2 leading-relaxed">{children}</p>;
      },
    }),
    [onCite]
  );

  return (
    <div className="w-full max-w-none text-[0.9375rem] text-foreground [&>*:first-child]:mt-0 [&>*:last-child]:mb-0">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {text}
      </ReactMarkdown>
    </div>
  );
}

const MarkdownRenderer = memo(MarkdownRendererImpl);
export default MarkdownRenderer;
