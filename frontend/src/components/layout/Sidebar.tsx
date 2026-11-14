"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
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
  Files,
  ScrollText,
  X,
} from "lucide-react";
import { api } from "@/lib/api";
import { prefetchRouteData, useCurrentUser } from "@/lib/hooks";
import { cx } from "@/components/ui";

const sections = [
  {
    title: "Workspace",
    items: [
      { name: "Chat", href: "/chat", icon: MessageSquare },
      { name: "Knowledge Bases", href: "/knowledge-bases", icon: Database },
      { name: "Documents", href: "/upload", icon: UploadCloud },
      { name: "Retrieval Viewer", href: "/retrieval", icon: SearchCode },
      { name: "Evaluation", href: "/evaluation", icon: TrendingUp },
    ],
  },
  {
    title: "Admin",
    adminOnly: true,
    items: [
      { name: "Dashboard", href: "/dashboard", icon: LayoutDashboard },
      { name: "Analytics", href: "/analytics", icon: BarChart3 },
      { name: "Users", href: "/users", icon: Users },
      { name: "All Documents", href: "/admin/documents", icon: Files },
      { name: "Audit Log", href: "/audit", icon: ScrollText },
    ],
  },
];

export default function Sidebar({
  mobileMenuOpen,
  setMobileMenuOpen,
}: {
  mobileMenuOpen?: boolean;
  setMobileMenuOpen?: (v: boolean) => void;
}) {
  const pathname = usePathname();
  const currentUser = useCurrentUser();
  const close = () => setMobileMenuOpen?.(false);

  const handleLogout = async () => {
    try {
      // Loaded only when signing out: the auth client is large and is not
      // needed to render any page.
      const { authClient } = await import("@/lib/auth");
      await authClient.signOut();
    } catch (err) {
      console.warn("Neon auth signOut skipped or unavailable:", err);
    }
    api.logout();
    window.location.href = "/login";
  };

  const initials =
    (currentUser?.full_name || currentUser?.email || "U")
      .split(/\s+/)
      .map((p) => p[0])
      .join("")
      .slice(0, 2)
      .toUpperCase() || "U";

  const navLink = (item: { name: string; href: string; icon: React.ComponentType<{ className?: string }> }) => {
    const active = pathname === item.href || (item.href !== "/" && pathname.startsWith(item.href + "/"));
    const Icon = item.icon;
    return (
      <Link
        key={item.href}
        href={item.href}
        onClick={close}
        onMouseEnter={() => prefetchRouteData(item.href)}
        onFocus={() => prefetchRouteData(item.href)}
        aria-current={active ? "page" : undefined}
        className={cx(
          "group flex h-9 items-center gap-3 rounded-lg px-3 text-sm transition-colors",
          active ? "bg-surface-muted font-semibold text-foreground" : "text-muted-foreground hover:bg-surface-muted/70 hover:text-foreground"
        )}
      >
        <Icon className={cx("h-4 w-4 shrink-0", active ? "text-accent" : "text-muted-foreground group-hover:text-foreground")} />
        <span className="truncate">{item.name}</span>
      </Link>
    );
  };

  return (
    <>
      {mobileMenuOpen && <div className="fixed inset-0 z-[80] bg-[#1a1a1a]/30 md:hidden" onClick={close} />}

      <aside
        className={cx(
          "fixed inset-y-0 left-0 z-[90] flex w-64 flex-col border-r border-border bg-surface transition-transform duration-300 ease-out md:sticky md:top-0 md:h-screen md:translate-x-0",
          mobileMenuOpen ? "translate-x-0" : "-translate-x-full"
        )}
        aria-label="Main navigation"
      >
        <div className="flex h-16 items-center justify-between px-5">
          <Link href="/chat" onClick={close} className="flex items-baseline gap-1.5">
            <span className="font-serif text-xl tracking-tight text-foreground">
              Agis <span className="italic text-accent">RAG</span>
            </span>
          </Link>
          <button onClick={close} className="icon-btn md:hidden" aria-label="Close menu">
            <X className="h-4 w-4" />
          </button>
        </div>

        <nav className="flex-1 space-y-6 overflow-y-auto px-3 pb-4 pt-2">
          {sections
            .filter((s) => !s.adminOnly || currentUser?.role === "admin")
            .map((section) => (
              <div key={section.title}>
                <p className="eyebrow mb-2 px-3 text-[10px]">{section.title}</p>
                <div className="space-y-0.5">{section.items.map(navLink)}</div>
              </div>
            ))}
        </nav>

        <div className="border-t border-border p-3">
          {navLink({ name: "Settings", href: "/settings", icon: Settings })}
          {currentUser && (
            <div className="mt-2 flex items-center gap-3 rounded-lg px-3 py-2">
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent-soft text-xs font-semibold text-accent-hover">
                {initials}
              </div>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-foreground">{currentUser.full_name || "Account"}</p>
                <p className="truncate text-xs text-muted-foreground">{currentUser.email}</p>
              </div>
              <button onClick={handleLogout} className="icon-btn" title="Sign out" aria-label="Sign out">
                <LogOut className="h-4 w-4" />
              </button>
            </div>
          )}
        </div>
      </aside>
    </>
  );
}
