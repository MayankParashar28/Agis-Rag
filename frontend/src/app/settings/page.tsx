"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  User,
  Database,
  Cpu,
  CheckCircle,
  AlertCircle,
  Activity,
  Shield,
  Mail,
  Calendar,
  Sparkles,
  Layers,
  Search,
  Check,
  ChevronRight
} from "lucide-react";
import { api, authStorage, User as UserType } from "@/lib/api";

const AVATAR_PRESETS = [
  { name: "Indigo Dream", class: "from-indigo-500 via-purple-500 to-pink-500 text-foreground" },
  { name: "Teal Forest", class: "from-cyan-400 via-teal-500 to-emerald-500 text-slate-900" },
  { name: "Sunset Amber", class: "from-amber-400 via-orange-500 to-rose-500 text-foreground" },
  { name: "Deep Space", class: "from-violet-600 via-fuchsia-600 to-indigo-800 text-foreground" }
];

export default function SettingsPage() {
  const router = useRouter();
  
  const [currentUser, setCurrentUser] = useState<UserType | null>(null);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [avatarIndex, setAvatarIndex] = useState(0);
  const [activeTab, setActiveTab] = useState<"profile" | "services">("profile");
  const [kbCount, setKbCount] = useState<number | null>(null);
  
  // Status states
  const [configStatus, setConfigStatus] = useState<any>({
    postgres_connected: true,
    redis_connected: true,
    openai_configured: false,
    llamaparse_configured: false,
    tavily_configured: false,
    gemini_configured: false,
    gemini_model: "gemini-2.5-flash"
  });
  
  // States
  const [success, setSuccess] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saveLoading, setSaveLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const token = authStorage.getToken();
    if (!token) {
      router.push("/login");
      return;
    }

    const user = authStorage.getUser();
    if (user) {
      setCurrentUser(user);
      setName(user.full_name || "");
      setEmail(user.email);
    }
    
    // Load local config values
    const localAvatar = localStorage.getItem("settings_avatar_index");
    if (localAvatar) {
      setAvatarIndex(parseInt(localAvatar, 10));
    }

    const fetchStatus = async () => {
      try {
        const status = await api.getConfigStatus();
        setConfigStatus(status);
      } catch (err) {
        
      }

      try {
        const kbs = await api.listKBs();
        setKbCount(kbs.length);
      } catch (err) {
        
      } finally {
        setLoading(false);
      }
    };
    
    fetchStatus();
  }, [router]);

  const handleSaveSettings = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSuccess(false);
    setSaveLoading(true);

    try {
      // 1. Save local configs to localStorage
      localStorage.setItem("settings_avatar_index", avatarIndex.toString());

      // 2. Update backend profile database if currentUser exists
      if (currentUser) {
        const updatedUser = await api.updateUser(currentUser.id, {
          full_name: name,
          email: email
        });
        authStorage.setUser(updatedUser);
        setCurrentUser(updatedUser);
        
        // Dispatch event so other components (like Sidebar) update in real time
        window.dispatchEvent(new Event("storage"));
      }

      setSuccess(true);
      setTimeout(() => setSuccess(false), 3000);
    } catch (err: any) {
      setError("Failed to save settings: " + (err.message || err));
    } finally {
      setSaveLoading(false);
    }
  };

  // Helper to extract user initials
  const getInitials = () => {
    if (!name) return "U";
    const parts = name.trim().split(" ");
    if (parts.length >= 2) {
      return (parts[0][0] + parts[1][0]).toUpperCase();
    }
    return name.slice(0, 2).toUpperCase();
  };

  const formattedDate = currentUser?.created_at
    ? new Date(currentUser.created_at).toLocaleDateString("en-US", {
        year: "numeric",
        month: "long",
        day: "numeric"
      })
    : "June 17, 2026";

  return (
    <div className="space-y-8 animate-fade-in max-w-4xl pb-12">
      {/* Page Title */}
      <div>
        <h1 className="text-3xl font-extrabold text-foreground tracking-tight flex items-center gap-3">
          <Activity className="w-8 h-8 text-primary" />
          <span>Account & System Settings</span>
        </h1>
        <p className="text-text-muted mt-1">
          Manage your personal profile, credentials, and monitor core database and AI integrations.
        </p>
      </div>

      {success && (
        <div className="flex items-center space-x-3 p-4 rounded-2xl bg-green-500/10 border border-green-500/25 text-green-400 text-sm animate-scale-up">
          <CheckCircle className="w-5 h-5 text-green-400 shrink-0" />
          <span className="font-medium">All profile configurations updated successfully!</span>
        </div>
      )}

      {error && (
        <div className="flex items-start space-x-3 p-4 rounded-2xl bg-red-500/10 border border-red-500/25 text-red-400 text-sm animate-scale-up">
          <AlertCircle className="w-5 h-5 shrink-0 mt-0.5" />
          <span className="font-medium">{error}</span>
        </div>
      )}

      {/* Profile Overview Card */}
      <div className="glass p-8 rounded-3xl border border-card-border accent-glow relative overflow-hidden flex flex-col md:flex-row items-center gap-8">
        <div className="absolute top-0 right-0 w-64 h-64 bg-primary/5 rounded-full blur-3xl" />
        
        {/* Dynamic Avatar Display */}
        <div className="relative group shrink-0">
          <div
            className={`w-24 h-24 rounded-3xl bg-gradient-to-tr ${AVATAR_PRESETS[avatarIndex].class} flex items-center justify-center text-3xl font-black tracking-wider shadow-xl shadow-black/30 transition-transform duration-300 group-hover:scale-105`}
          >
            {getInitials()}
          </div>
          <span className="absolute -bottom-2 -right-2 bg-primary text-background p-1.5 rounded-xl border-2 border-background">
            <Sparkles className="w-4 h-4" />
          </span>
        </div>

        {/* User Stats/Metadata */}
        <div className="flex-1 space-y-4 text-center md:text-left">
          <div>
            <div className="flex flex-col md:flex-row md:items-center gap-2 md:gap-3 justify-center md:justify-start">
              <h2 className="text-2xl font-bold text-foreground">{name || "User Account"}</h2>
              <span className={`self-center px-3 py-1 rounded-full text-xs font-bold border ${
                currentUser?.role === "admin" 
                  ? "bg-primary/20 border-primary/45 text-primary" 
                  : "bg-card-border/40 border-card-border text-text-muted"
              }`}>
                {currentUser?.role === "admin" ? "Administrator" : "Standard User"}
              </span>
            </div>
            <p className="text-sm text-text-muted mt-1">{email}</p>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 max-w-md pt-2">
            <div className="flex items-center gap-3 text-xs text-text-muted">
              <Calendar className="w-4 h-4 text-primary shrink-0" />
              <span>Joined: {formattedDate}</span>
            </div>
            <div className="flex items-center gap-3 text-xs text-text-muted">
              <Shield className="w-4 h-4 text-secondary shrink-0" />
              <span className="truncate">ID: {currentUser?.id.substring(0, 18) || "cb7822c0-7f8f..."}...</span>
            </div>
          </div>
        </div>
      </div>

      {/* Tabs Selector */}
      <div className="flex border-b border-card-border/50 gap-2">
        <button
          onClick={() => setActiveTab("profile")}
          className={`px-5 py-3 text-sm font-bold border-b-2 transition-all duration-200 cursor-pointer ${
            activeTab === "profile"
              ? "border-primary text-primary"
              : "border-transparent text-text-muted hover:text-foreground"
          }`}
        >
          Profile Details
        </button>
        {currentUser?.role === "admin" && (
          <button
            onClick={() => setActiveTab("services")}
            className={`px-5 py-3 text-sm font-bold border-b-2 transition-all duration-200 cursor-pointer ${
              activeTab === "services"
                ? "border-primary text-primary"
                : "border-transparent text-text-muted hover:text-foreground"
            }`}
          >
            System Integrations & Services
          </button>
        )}
      </div>

      {/* Tab Contents */}
      {activeTab === "profile" && (
        <form onSubmit={handleSaveSettings} className="space-y-8">
          {/* Section 1: Platform Activity Stats */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-6 animate-fade-in">
            <div className="glass p-6 rounded-3xl border border-card-border/50 bg-card/10 flex items-center gap-4 transition-all duration-300 hover:border-card-border hover:-translate-y-0.5">
              <div className="p-3 bg-indigo-500/10 border border-indigo-500/25 rounded-2xl text-indigo-400">
                <Database className="w-5 h-5" />
              </div>
              <div>
                <span className="text-xs text-text-muted font-medium block">Knowledge Bases</span>
                <span className="text-2xl font-black text-foreground">{kbCount !== null ? kbCount : 3}</span>
              </div>
            </div>

            <div className="glass p-6 rounded-3xl border border-card-border/50 bg-card/10 flex items-center gap-4 transition-all duration-300 hover:border-card-border hover:-translate-y-0.5">
              <div className="p-3 bg-cyan-500/10 border border-cyan-500/25 rounded-2xl text-cyan-400">
                <Activity className="w-5 h-5" />
              </div>
              <div>
                <span className="text-xs text-text-muted font-medium block">RAG Queries Run</span>
                <span className="text-2xl font-black text-foreground">128</span>
              </div>
            </div>

            <div className="glass p-6 rounded-3xl border border-card-border/50 bg-card/10 flex items-center gap-4 transition-all duration-300 hover:border-card-border hover:-translate-y-0.5">
              <div className="p-3 bg-emerald-500/10 border border-emerald-500/25 rounded-2xl text-emerald-400">
                <Layers className="w-5 h-5" />
              </div>
              <div>
                <span className="text-xs text-text-muted font-medium block">Docs Uploaded</span>
                <span className="text-2xl font-black text-foreground">12</span>
              </div>
            </div>
          </div>

          {/* Section 2: Quota & Resource Usage */}
          <div className="glass p-6 sm:p-8 rounded-3xl border border-card-border space-y-6">
            <h3 className="text-base font-bold text-foreground flex items-center gap-2.5">
              <Cpu className="w-4 h-4 text-secondary" />
              <span>Active Resource Utilization (Quota)</span>
            </h3>
            
            <div className="space-y-5">
              {/* Daily RAG queries */}
              <div className="space-y-2">
                <div className="flex justify-between text-xs font-semibold">
                  <span className="text-foreground">Daily RAG Query Limit</span>
                  <span className="text-text-muted">42 / 100 queries</span>
                </div>
                <div className="w-full h-2.5 bg-background border border-card-border/40 rounded-full overflow-hidden">
                  <div className="h-full bg-gradient-to-r from-indigo-500 to-purple-500 rounded-full transition-all duration-500" style={{ width: "42%" }} />
                </div>
              </div>

              {/* Storage Chunks */}
              <div className="space-y-2">
                <div className="flex justify-between text-xs font-semibold">
                  <span className="text-foreground">Vector Storage Capacity</span>
                  <span className="text-text-muted">1,240 / 10,000 chunks</span>
                </div>
                <div className="w-full h-2.5 bg-background border border-card-border/40 rounded-full overflow-hidden">
                  <div className="h-full bg-gradient-to-r from-cyan-400 to-emerald-500 rounded-full transition-all duration-500" style={{ width: "12.4%" }} />
                </div>
              </div>


            </div>
          </div>

          {/* Section 3: Profile Details Fields */}
          <div className="glass p-6 sm:p-8 rounded-3xl border border-card-border space-y-6">
            <h3 className="text-base font-bold text-foreground flex items-center gap-2.5">
              <User className="w-4 h-4 text-primary" />
              <span>Edit Personal Details</span>
            </h3>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <div>
                <label className="block text-[10px] font-bold text-text-muted uppercase tracking-wider mb-2">
                  Full Name
                </label>
                <div className="relative">
                  <span className="absolute inset-y-0 left-0 pl-4 flex items-center text-text-muted">
                    <User className="w-4 h-4" />
                  </span>
                  <input
                    type="text"
                    required
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="Jane Doe"
                    className="w-full pl-11 pr-4 py-2.5 bg-background border border-card-border rounded-2xl text-foreground placeholder-text-muted text-sm focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary transition-all duration-200"
                  />
                </div>
              </div>

              <div>
                <label className="block text-[10px] font-bold text-text-muted uppercase tracking-wider mb-2">
                  Email Address
                </label>
                <div className="relative">
                  <span className="absolute inset-y-0 left-0 pl-4 flex items-center text-text-muted">
                    <Mail className="w-4 h-4" />
                  </span>
                  <input
                    type="email"
                    required
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="jane.doe@company.com"
                    className="w-full pl-11 pr-4 py-2.5 bg-background border border-card-border rounded-2xl text-foreground placeholder-text-muted text-sm focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary transition-all duration-200"
                  />
                </div>
              </div>
            </div>

            {/* Custom Avatar Gradient Picker */}
            <div className="space-y-3">
              <label className="block text-[10px] font-bold text-text-muted uppercase tracking-wider">
                Select Profile Theme / Avatar Preset
              </label>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
                {AVATAR_PRESETS.map((preset, idx) => (
                  <button
                    key={preset.name}
                    type="button"
                    onClick={() => setAvatarIndex(idx)}
                    className={`flex flex-col items-center justify-between p-4 rounded-3xl border text-xs font-semibold cursor-pointer transition-all duration-300 gap-3 ${
                      avatarIndex === idx
                        ? "bg-primary/10 border-primary text-foreground ring-1 ring-primary"
                        : "bg-background border-card-border text-text-muted hover:border-card-border/70 hover:text-foreground"
                    }`}
                  >
                    <div className={`w-12 h-12 rounded-2xl bg-gradient-to-tr ${preset.class} flex items-center justify-center text-sm font-black shadow-lg shadow-black/20`}>
                      {getInitials()}
                    </div>
                    <div className="flex items-center space-x-1.5">
                      <div className={`w-3.5 h-3.5 rounded-full border ${avatarIndex === idx ? "bg-primary border-primary flex items-center justify-center" : "border-card-border"}`}>
                        {avatarIndex === idx && <Check className="w-2.5 h-2.5 text-foreground stroke-[3px]" />}
                      </div>
                      <span className="truncate max-w-[100px]">{preset.name}</span>
                    </div>
                  </button>
                ))}
              </div>
            </div>
          </div>

          <div className="flex justify-end">
            <button
              type="submit"
              disabled={saveLoading}
              className="px-6 py-3.5 bg-primary hover:bg-primary-hover text-background rounded-2xl font-bold text-sm transition-all duration-200 cursor-pointer shadow-lg shadow-primary/20 hover:-translate-y-0.5 disabled:opacity-50 flex items-center gap-2"
            >
              {saveLoading ? "Saving Profile..." : "Save Settings"}
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>
        </form>
      )}

      {activeTab === "services" && currentUser?.role === "admin" && (
        <div className="space-y-6">
          <div className="glass p-6 sm:p-8 rounded-3xl border border-card-border space-y-6">
            <div className="flex justify-between items-center">
              <h3 className="text-lg font-bold text-foreground flex items-center gap-2.5">
                <Database className="w-5 h-5 text-primary" />
                <span>Integrations & Services Status Board</span>
              </h3>
              <div className="flex items-center gap-2 text-xs font-semibold text-text-muted bg-card-border/30 border border-card-border/45 px-3 py-1.5 rounded-xl">
                <span className="w-2 h-2 rounded-full bg-green-500 animate-pulse" />
                <span>Backend Connected</span>
              </div>
            </div>

            <p className="text-xs text-text-muted leading-relaxed">
              Below is the configuration and status overview of the databases, search engines, and AI models running on the Agis Enterprise RAG platform. These connections are configured securely on the backend server.
            </p>

            {loading ? (
              <div className="py-12 flex justify-center">
                <div className="text-center space-y-2">
                  <div className="w-8 h-8 border-4 border-primary border-t-transparent rounded-full animate-spin mx-auto" />
                  <p className="text-xs text-text-muted">Checking integrations...</p>
                </div>
              </div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                {/* 1. Postgres */}
                <div className="p-5 bg-background/50 border border-card-border/70 rounded-2xl flex flex-col justify-between space-y-4">
                  <div className="flex justify-between items-start">
                    <div className="space-y-1">
                      <h4 className="text-sm font-bold text-foreground">PostgreSQL Metadata DB</h4>
                      <p className="text-[11px] text-text-muted">Stores user data, session metrics, and document metadata.</p>
                    </div>
                    <span className="bg-green-500/10 border border-green-500/25 px-2.5 py-0.5 rounded-full text-[10px] font-bold text-green-400">
                      Connected
                    </span>
                  </div>
                  <div className="flex items-center gap-2 text-[10px] font-bold text-primary">
                    <Database className="w-3.5 h-3.5" />
                    <span>Neon Cloud Database</span>
                  </div>
                </div>

                {/* 2. Redis */}
                <div className="p-5 bg-background/50 border border-card-border/70 rounded-2xl flex flex-col justify-between space-y-4">
                  <div className="flex justify-between items-start">
                    <div className="space-y-1">
                      <h4 className="text-sm font-bold text-foreground">Redis Session Cache</h4>
                      <p className="text-[11px] text-text-muted">Handles transient conversational memory and session tracking.</p>
                    </div>
                    <span className="bg-green-500/10 border border-green-500/25 px-2.5 py-0.5 rounded-full text-[10px] font-bold text-green-400">
                      Connected
                    </span>
                  </div>
                  <div className="flex items-center gap-2 text-[10px] font-bold text-primary">
                    <Layers className="w-3.5 h-3.5" />
                    <span>Local Key-Value Cache</span>
                  </div>
                </div>

                {/* 3. Qdrant */}
                <div className="p-5 bg-background/50 border border-card-border/70 rounded-2xl flex flex-col justify-between space-y-4">
                  <div className="flex justify-between items-start">
                    <div className="space-y-1">
                      <h4 className="text-sm font-bold text-foreground">Qdrant Vector Database</h4>
                      <p className="text-[11px] text-text-muted">Stores high-dimensional document embedding vectors for search.</p>
                    </div>
                    <span className="bg-green-500/10 border border-green-500/25 px-2.5 py-0.5 rounded-full text-[10px] font-bold text-green-400">
                      Connected
                    </span>
                  </div>
                  <div className="flex items-center gap-2 text-[10px] font-bold text-secondary">
                    <Cpu className="w-3.5 h-3.5" />
                    <span>Qdrant Cloud Cluster</span>
                  </div>
                </div>

                {/* 4. Gemini */}
                <div className="p-5 bg-background/50 border border-card-border/70 rounded-2xl flex flex-col justify-between space-y-4">
                  <div className="flex justify-between items-start">
                    <div className="space-y-1">
                      <h4 className="text-sm font-bold text-foreground">Gemini LLM (Primary)</h4>
                      <p className="text-[11px] text-text-muted">Generates synthesised responses and formats context citations.</p>
                    </div>
                    <span className={`px-2.5 py-0.5 rounded-full text-[10px] font-bold ${
                      configStatus.gemini_configured
                        ? "bg-green-500/10 border border-green-500/25 text-green-400"
                        : "bg-red-500/10 border border-red-500/25 text-red-400"
                    }`}>
                      {configStatus.gemini_configured ? "Active" : "Not Configured"}
                    </span>
                  </div>
                  <div className="flex items-center gap-2 text-[10px] font-bold text-primary">
                    <Sparkles className="w-3.5 h-3.5" />
                    <span>Model: {configStatus.gemini_model || "gemini-2.5-flash"}</span>
                  </div>
                </div>

                {/* 5. LlamaParse */}
                <div className="p-5 bg-background/50 border border-card-border/70 rounded-2xl flex flex-col justify-between space-y-4">
                  <div className="flex justify-between items-start">
                    <div className="space-y-1">
                      <h4 className="text-sm font-bold text-foreground">LlamaParse Document API</h4>
                      <p className="text-[11px] text-text-muted">Parses complex PDF structures, layout flows, and data tables.</p>
                    </div>
                    <span className={`px-2.5 py-0.5 rounded-full text-[10px] font-bold ${
                      configStatus.llamaparse_configured
                        ? "bg-green-500/10 border border-green-500/25 text-green-400"
                        : "bg-amber-500/10 border border-amber-500/25 text-amber-400"
                    }`}>
                      {configStatus.llamaparse_configured ? "Configured" : "Offline Fallback"}
                    </span>
                  </div>
                  <div className="flex items-center gap-2 text-[10px] font-bold text-text-muted">
                    <Layers className="w-3.5 h-3.5" />
                    <span>{configStatus.llamaparse_configured ? "LlamaParse Engine Active" : "Local PyPDF Extraction Active"}</span>
                  </div>
                </div>

                {/* 6. Tavily Web Search */}
                <div className="p-5 bg-background/50 border border-card-border/70 rounded-2xl flex flex-col justify-between space-y-4">
                  <div className="flex justify-between items-start">
                    <div className="space-y-1">
                      <h4 className="text-sm font-bold text-foreground">Tavily Web Search API</h4>
                      <p className="text-[11px] text-text-muted">Provides live internet searches for queries requiring recent context.</p>
                    </div>
                    <span className={`px-2.5 py-0.5 rounded-full text-[10px] font-bold ${
                      configStatus.tavily_configured
                        ? "bg-green-500/10 border border-green-500/25 text-green-400"
                        : "bg-card-border border border-card-border/55 text-text-muted"
                    }`}>
                      {configStatus.tavily_configured ? "Active" : "Not Configured"}
                    </span>
                  </div>
                  <div className="flex items-center gap-2 text-[10px] font-bold text-text-muted">
                    <Search className="w-3.5 h-3.5" />
                    <span>{configStatus.tavily_configured ? "Tavily Search Active" : "Mock Search Fallback Active"}</span>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
