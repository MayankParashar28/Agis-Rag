"use client";

import { usePathname } from "next/navigation";
import { useState } from "react";
import Sidebar from "./Sidebar";
import { Menu } from "lucide-react";

export default function LayoutWrapper({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  // No app chrome on the landing, login and registration pages.
  const isAuthPage = pathname === "/login" || pathname === "/register" || pathname === "/" || pathname.startsWith("/chat/print/");
  if (isAuthPage) {
    return <div className="min-h-screen bg-background">{children}</div>;
  }

  const isChat = pathname === "/chat";

  return (
    <div className="flex min-h-screen flex-col bg-background md:h-screen md:flex-row md:overflow-hidden">
      {/* Mobile top bar */}
      <div className="sticky top-0 z-40 flex h-14 shrink-0 items-center justify-between border-b border-border bg-surface/95 px-4 backdrop-blur md:hidden">
        <span className="font-serif text-lg tracking-tight text-foreground">
          Agis <span className="italic text-accent">RAG</span>
        </span>
        <button onClick={() => setMobileMenuOpen(true)} className="icon-btn" aria-label="Open menu">
          <Menu className="h-5 w-5" />
        </button>
      </div>

      <Sidebar mobileMenuOpen={mobileMenuOpen} setMobileMenuOpen={setMobileMenuOpen} />

      <main className={isChat ? "min-w-0 flex-1 overflow-hidden p-3 md:p-5" : "min-w-0 flex-1 overflow-y-auto"}>
        {isChat ? children : <div className="mx-auto w-full max-w-7xl px-4 py-6 md:px-8 md:py-10">{children}</div>}
      </main>
    </div>
  );
}
