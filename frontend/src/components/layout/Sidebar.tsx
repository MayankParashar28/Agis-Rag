"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import {
  LayoutDashboard,
  Database,
  UploadCloud,
  MessageSquare,
  SearchCode,
  TrendingUp,
  BarChart3,
  Settings,
  LogOut,
  Users,
  Files
} from "lucide-react";
import { api, authStorage, User as UserType } from "@/lib/api";
import { authClient } from "@/lib/auth";

const menuItems = [
  { name: "Dashboard", href: "/dashboard", icon: LayoutDashboard, adminOnly: true },
  { name: "Knowledge Bases", href: "/knowledge-bases", icon: Database, adminOnly: false },
  { name: "Upload Documents", href: "/upload", icon: UploadCloud, adminOnly: false },
  { name: "Chat Engine", href: "/chat", icon: MessageSquare, adminOnly: false },
  { name: "Retrieval Viewer", href: "/retrieval", icon: SearchCode, adminOnly: false },
  { name: "Analytics Dashboard", href: "/analytics", icon: BarChart3, adminOnly: true },
  { name: "User Management", href: "/users", icon: Users, adminOnly: true },
  { name: "Doc Management", href: "/admin/documents", icon: Files, adminOnly: true },
  { name: "RAGAS Evaluation", href: "/evaluation", icon: TrendingUp, adminOnly: false },
  { name: "Settings", href: "/settings", icon: Settings, adminOnly: false },
];

export default function Sidebar({ mobileMenuOpen, setMobileMenuOpen }: { mobileMenuOpen?: boolean, setMobileMenuOpen?: (v: boolean) => void }) {
  const pathname = usePathname();
  const router = useRouter();
  const [currentUser, setCurrentUser] = useState<UserType | null>(null);

  useEffect(() => {
    setCurrentUser(authStorage.getUser());
  }, [pathname]);

  const handleLogout = async () => {
    await authClient.signOut();
    api.logout();
    router.push("/login");
  };

  return (
    <>
      {/* Mobile Overlay */}
      {mobileMenuOpen && (
        <div 
          className="fixed inset-0 bg-foreground/20 backdrop-blur-md z-[80] md:hidden"
          onClick={() => setMobileMenuOpen && setMobileMenuOpen(false)}
        />
      )}
      
      <aside className={`w-72 bg-card border-r border-card-border/10 flex flex-col justify-between h-screen fixed md:sticky top-0 z-[90] transition-transform duration-700 ease-[cubic-bezier(0.16,1,0.3,1)] md:translate-x-0 ${mobileMenuOpen ? 'translate-x-0' : '-translate-x-full'}`}>
        <div>
        {/* Logo */}
        <div className="p-8 border-b border-card-border/10 flex flex-col space-y-4 relative overflow-hidden">
          <div className="w-8 h-px bg-foreground z-10" />
          <div className="relative z-10">
            <span className="font-serif text-2xl text-foreground block leading-[0.9] tracking-tight">
              Agis <span className="italic text-accent">RAG</span>
            </span>
            <span className="text-[10px] tracking-[0.2em] uppercase text-muted-foreground mt-2 block">Enterprise Platform</span>
          </div>
          {/* Logo Watermark behind branding */}
          <div className="absolute left-8 top-1/2 -translate-y-1/2 w-32 h-32 opacity-[0.05] pointer-events-none select-none z-0">
            <img 
              src="/logo.png" 
              alt="AGIS Logo Watermark" 
              className="w-full h-full object-contain" 
            />
          </div>
        </div>

        {/* Navigation Menu */}
        <nav className="p-6 space-y-1">
          <div className="text-[10px] tracking-[0.2em] uppercase text-muted-foreground mb-6">Menu</div>
          {menuItems
            .filter((item) => !item.adminOnly || currentUser?.role === "admin")
            .map((item) => {
              const isActive = pathname === item.href;
              const Icon = item.icon;
              return (
                <Link
                  key={item.name}
                  href={item.href}
                  onClick={() => setMobileMenuOpen && setMobileMenuOpen(false)}
                  className={`group flex items-center justify-between px-0 py-3 transition-all duration-500 border-b ${
                    isActive
                      ? "border-accent text-foreground"
                      : "border-transparent text-muted-foreground hover:border-foreground/30 hover:text-foreground"
                  }`}
                >
                  <div className="flex items-center space-x-4">
                    <Icon className={`w-4 h-4 transition-colors duration-500 ${isActive ? "text-accent" : "text-muted-foreground group-hover:text-foreground"}`} strokeWidth={1.5} />
                    <span className="text-sm font-sans tracking-wide">{item.name}</span>
                  </div>
                  {isActive && <div className="w-1.5 h-1.5 rounded-full bg-accent" />}
                </Link>
              );
            })}
        </nav>

      </div>

      {/* User profile & Logout */}
      {currentUser && (
        <div className="p-6 border-t border-card-border/10 bg-muted-background/30">
          <div className="flex items-center space-x-4 mb-6">
            <div className="w-10 h-10 border border-foreground/20 flex items-center justify-center bg-background">
              <span className="font-serif text-foreground">{currentUser.full_name?.charAt(0) || "U"}</span>
            </div>
            <div className="truncate flex-1">
              <span className="text-[10px] tracking-[0.2em] uppercase text-muted-foreground block mb-0.5">
                Welcome back,
              </span>
              <span className="text-sm font-serif italic text-accent block truncate">
                {currentUser.full_name?.split(' ')[0] || "User"}
              </span>
            </div>
          </div>
          <button
            onClick={handleLogout}
            className="w-full flex items-center justify-center space-x-2 py-3 border border-foreground/20 text-foreground hover:bg-foreground hover:text-background transition-all duration-500 text-[10px] uppercase tracking-[0.2em]"
          >
            <LogOut className="w-3 h-3" strokeWidth={1.5} />
            <span>Sign Out</span>
          </button>
        </div>
      )}
    </aside>
    </>
  );
}
