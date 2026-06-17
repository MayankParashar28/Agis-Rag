import React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { vscDarkPlus } from "react-syntax-highlighter/dist/cjs/styles/prism";

interface MarkdownRendererProps {
  content: string;
}

export default function MarkdownRenderer({ content }: MarkdownRendererProps) {
  return (
    <div className="prose prose-sm max-w-none w-full text-foreground">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          code({ inline, className, children, ...props }: any) {
            const match = /language-(\w+)/.exec(className || "");
            return !inline && match ? (
              <div className="rounded-xl overflow-hidden my-4 border border-card-border/50 bg-[#1e1e1e]">
                <div className="flex items-center justify-between px-4 py-2 bg-[#2d2d2d] border-b border-card-border/50">
                  <span className="text-xs font-mono text-muted-foreground">{match[1]}</span>
                  <button 
                    onClick={() => navigator.clipboard.writeText(String(children))}
                    className="text-xs text-muted-foreground hover:text-foreground transition-colors"
                  >
                    Copy
                  </button>
                </div>
                <SyntaxHighlighter
                  {...props}
                  style={vscDarkPlus}
                  language={match[1]}
                  PreTag="div"
                  customStyle={{ margin: 0, padding: "1rem", backgroundColor: "transparent" }}
                >
                  {String(children).replace(/\n$/, "")}
                </SyntaxHighlighter>
              </div>
            ) : (
              <code {...props} className="bg-primary/20 text-foreground px-1.5 py-0.5 rounded-md font-mono text-[0.85em]">
                {children}
              </code>
            );
          },
          table({ children, ...props }) {
            return (
              <div className="overflow-x-auto my-4 rounded-xl border border-card-border/50">
                <table {...props} className="min-w-full divide-y divide-card-border/50">
                  {children}
                </table>
              </div>
            );
          },
          thead({ children, ...props }) {
            return <thead {...props} className="bg-card/40">{children}</thead>;
          },
          th({ children, ...props }) {
            return <th {...props} className="px-4 py-3 text-left text-xs font-bold text-muted-foreground uppercase tracking-wider">{children}</th>;
          },
          td({ children, ...props }) {
            return <td {...props} className="px-4 py-3 text-sm text-foreground border-t border-card-border/30">{children}</td>;
          },
          a({ children, ...props }) {
            return <a {...props} className="text-primary hover:text-primary-hover hover:underline transition-colors">{children}</a>;
          },
          blockquote({ children, ...props }) {
            return <blockquote {...props} className="border-l-4 border-primary/50 pl-4 my-4 italic text-muted-foreground bg-primary/5 py-2 pr-4 rounded-r-xl">{children}</blockquote>;
          },
          ul({ children, ...props }) {
            return <ul {...props} className="list-disc pl-5 my-2 space-y-1">{children}</ul>;
          },
          ol({ children, ...props }) {
            return <ol {...props} className="list-decimal pl-5 my-2 space-y-1">{children}</ol>;
          },
          h1({ children, ...props }) {
            return <h1 {...props} className="text-2xl font-bold mt-6 mb-4 text-foreground">{children}</h1>;
          },
          h2({ children, ...props }) {
            return <h2 {...props} className="text-xl font-bold mt-5 mb-3 text-foreground border-b border-card-border/50 pb-2">{children}</h2>;
          },
          h3({ children, ...props }) {
            return <h3 {...props} className="text-lg font-bold mt-4 mb-2 text-foreground">{children}</h3>;
          },
          p({ children, ...props }) {
            return <p {...props} className="my-2 leading-relaxed text-foreground">{children}</p>;
          }
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
