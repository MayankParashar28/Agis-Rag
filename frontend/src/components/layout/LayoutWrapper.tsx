"use client";

import { usePathname } from "next/navigation";
import { useState } from "react";
import Sidebar from "./Sidebar";
import { Menu } from "lucide-react";

export default function LayoutWrapper({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  
  // Do not show sidebar on landing, login, or registration pages
  const isAuthPage = pathname === "/login" || pathname === "/register" || pathname === "/";

  if (isAuthPage) {
    return <div className="min-h-screen flex flex-col bg-background relative z-10">{children}</div>;
  }

  return (
    <div className="flex flex-col md:flex-row min-h-screen md:h-screen bg-transparent overflow-hidden relative z-10">
      {/* Mobile Top Nav */}
      <div className="md:hidden flex items-center justify-between p-6 border-b border-card-border/10 bg-card shrink-0 relative z-10">
        <div className="flex flex-col space-y-1">
          <span className="font-serif text-xl text-foreground block leading-[0.9] tracking-tight">
            Aegis <span className="italic text-accent">RAG</span>
          </span>
        </div>
        <button 
          onClick={() => setMobileMenuOpen(true)}
          className="text-foreground hover:text-accent transition-colors duration-500"
        >
          <Menu className="w-6 h-6" strokeWidth={1.5} />
        </button>
      </div>

      <Sidebar mobileMenuOpen={mobileMenuOpen} setMobileMenuOpen={setMobileMenuOpen} />
      
      <main className="flex-1 overflow-y-auto p-4 md:p-12 relative z-10">
        {children}
      </main>
    </div>
  );
}
