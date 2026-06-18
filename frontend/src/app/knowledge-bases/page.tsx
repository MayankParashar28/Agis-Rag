"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Database,
  Plus,
  Trash2,
  Cpu,
  Layers,
  FileText,
  Clock,
  X,
  AlertCircle
} from "lucide-react";
import { api, authStorage, KnowledgeBase, KBStats } from "@/lib/api";

export default function KnowledgeBasesPage() {
  const router = useRouter();
  const [kbs, setKbs] = useState<KnowledgeBase[]>([]);
  const [statsMap, setStatsMap] = useState<Record<string, KBStats>>({});
  const [loading, setLoading] = useState(true);
  
  // Modal states
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [embedModel, setEmbedModel] = useState("BAAI/bge-large-en-v1.5");
  const [modalLoading, setModalLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const token = authStorage.getToken();
    if (!token) {
      router.push("/login");
      return;
    }
    fetchData();
  }, [router]);

  const fetchData = async () => {
    setLoading(true);
    try {
      const kbList = await api.listKBs();
      setKbs(kbList);
      
      // Fetch stats for each KB
      const statsPromises = kbList.map(async (kb) => {
        try {
          const stats = await api.getKBStats(kb.id);
          return { id: kb.id, stats };
        } catch (e) {
          // Fallback stats if DB holds empty values
          return {
            id: kb.id,
            stats: {
              total_documents: 0,
              total_chunks: 0,
              embedding_model: kb.embedding_model,
              vector_count: 0,
              last_indexed_date: null
            }
          };
        }
      });
      
      const statsResults = await Promise.all(statsPromises);
      const newStatsMap: Record<string, KBStats> = {};
      statsResults.forEach((res) => {
        newStatsMap[res.id] = res.stats;
      });
      setStatsMap(newStatsMap);
    } catch (err: any) {
      setError(err.message || "Failed to load knowledge bases.");
    } finally {
      setLoading(false);
    }
  };

  const handleCreateKB = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    setError(null);
    setModalLoading(true);
    
    try {
      const newKB = await api.createKB({
        name,
        description,
        embedding_model: embedModel
      });
      setKbs((prev) => [...prev, newKB]);
      setStatsMap((prev) => ({
        ...prev,
        [newKB.id]: {
          total_documents: 0,
          total_chunks: 0,
          embedding_model: newKB.embedding_model,
          vector_count: 0,
          last_indexed_date: null
        }
      }));
      setIsModalOpen(false);
      setName("");
      setDescription("");
    } catch (err: any) {
      setError(err.message || "Failed to create knowledge base.");
    } finally {
      setModalLoading(false);
    }
  };

  const handleDeleteKB = async (kbId: string, name: string) => {
    if (!confirm(`Are you sure you want to delete the Knowledge Base "${name}"? All associated document files and Qdrant vectors will be permanently deleted.`)) {
      return;
    }

    try {
      await api.deleteKB(kbId);
      setKbs((prev) => prev.filter((kb) => kb.id !== kbId));
      // Remove stats
      const newStats = { ...statsMap };
      delete newStats[kbId];
      setStatsMap(newStats);
    } catch (err: any) {
      alert(err.message || "Failed to delete knowledge base.");
    }
  };

  return (
    <div className="space-y-8">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-extrabold text-foreground tracking-tight">Knowledge Bases</h1>
          <p className="text-text-muted mt-1">Manage isolated indexing directories</p>
        </div>
        <button
          onClick={() => setIsModalOpen(true)}
          className="flex items-center space-x-2 px-5 py-3 bg-primary hover:bg-primary-hover text-background rounded-2xl font-semibold transition-all duration-200 text-sm cursor-pointer shadow-lg shadow-primary/20"
        >
          <Plus className="w-4 h-4" />
          <span>New Knowledge Base</span>
        </button>
      </div>

      {loading ? (
        <div className="flex items-center justify-center min-h-[40vh] text-foreground">
          <div className="text-center space-y-2">
            <div className="w-8 h-8 border-4 border-primary border-t-transparent rounded-full animate-spin mx-auto" />
            <p className="text-sm text-text-muted">Loading databases...</p>
          </div>
        </div>
      ) : kbs.length === 0 ? (
        <div className="glass p-12 rounded-3xl border border-card-border text-center">
          <Database className="w-12 h-12 text-text-muted mx-auto mb-4" />
          <h3 className="text-lg font-bold text-foreground mb-2">No Knowledge Bases Found</h3>
          <p className="text-sm text-text-muted max-w-sm mx-auto mb-6">
            Create a knowledge base to hold your document collections and generate embeddings for hybrid query search.
          </p>
          <button
            onClick={() => setIsModalOpen(true)}
            className="px-5 py-3 bg-primary hover:bg-primary-hover text-background rounded-2xl font-semibold transition-all duration-200 text-sm cursor-pointer"
          >
            Create Your First KB
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {kbs.map((kb) => {
            const stats = statsMap[kb.id];
            return (
              <div
                key={kb.id}
                className="glass p-6 rounded-3xl border border-card-border flex flex-col justify-between hover:border-card-border/60 transition-all duration-200"
              >
                <div>
                  <div className="flex justify-between items-start">
                    <div className="flex items-center space-x-3">
                      <div className="bg-primary/15 p-2.5 rounded-xl border border-primary/30 text-primary">
                        <Database className="w-5 h-5" />
                      </div>
                      <h3 className="text-lg font-bold text-foreground leading-tight">{kb.name}</h3>
                    </div>
                    <button
                      onClick={() => handleDeleteKB(kb.id, kb.name)}
                      className="p-2 rounded-xl text-text-muted hover:bg-red-500/10 hover:text-red-400 transition-all duration-200 cursor-pointer"
                      title="Delete Knowledge Base"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                  <p className="text-sm text-text-muted mt-3 line-clamp-2 leading-relaxed">
                    {kb.description || "No description provided."}
                  </p>
                </div>

                <div className="border-t border-card-border/50 mt-6 pt-4 grid grid-cols-3 gap-4">
                  <div className="flex flex-col">
                    <span className="text-[10px] uppercase font-bold tracking-wider text-text-muted">Documents</span>
                    <span className="text-base font-bold text-foreground mt-0.5">{stats?.total_documents ?? 0}</span>
                  </div>
                  <div className="flex flex-col">
                    <span className="text-[10px] uppercase font-bold tracking-wider text-text-muted">Vectors</span>
                    <span className="text-base font-bold text-foreground mt-0.5">{(stats?.vector_count ?? 0).toLocaleString()}</span>
                  </div>
                  <div className="flex flex-col">
                    <span className="text-[10px] uppercase font-bold tracking-wider text-text-muted">Model</span>
                    <span className="text-xs font-bold text-primary truncate mt-1">BGE Large</span>
                  </div>
                </div>

                <div className="mt-6 flex gap-4">
                  <button
                    onClick={() => router.push(`/upload?kb_id=${kb.id}`)}
                    className="flex-1 py-2.5 bg-background hover:bg-card-border/20 border border-card-border text-foreground text-xs font-semibold rounded-xl transition-all duration-200 cursor-pointer text-center"
                  >
                    Manage Uploads
                  </button>
                  <button
                    onClick={() => router.push(`/chat?kb_id=${kb.id}`)}
                    className="flex-1 py-2.5 bg-primary/20 hover:bg-primary/30 text-primary border border-primary/30 text-xs font-semibold rounded-xl transition-all duration-200 cursor-pointer text-center"
                  >
                    Query Chat
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Modal Dialog */}
      {isModalOpen && (
        <div className="fixed inset-0 bg-background/80 backdrop-blur-sm z-[100] flex items-center justify-center p-4 md:pl-72">
          <div className="w-full max-w-md glass border border-card-border rounded-3xl p-6 relative animate-scale-up">
            <button
              onClick={() => setIsModalOpen(false)}
              className="absolute top-4 right-4 p-1.5 text-text-muted hover:bg-card-border/30 hover:text-foreground rounded-lg transition-all duration-200"
            >
              <X className="w-5 h-5" />
            </button>

            <h2 className="text-xl font-bold text-foreground mb-1 flex items-center space-x-2">
              <Plus className="w-5 h-5 text-primary" />
              <span>Create Knowledge Base</span>
            </h2>
            <p className="text-xs text-text-muted mb-6">Create a namespace to segment parsed vectors</p>

            {error && (
              <div className="mb-4 flex items-start space-x-2 p-3 rounded-xl bg-red-500/10 border border-red-500/20 text-red-400 text-xs">
                <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
                <span>{error}</span>
              </div>
            )}

            <form onSubmit={handleCreateKB} className="space-y-4">
              <div>
                <label className="block text-[10px] font-bold text-text-muted uppercase tracking-wider mb-1.5">
                  Name
                </label>
                <input
                  type="text"
                  required
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Financial Q2 Reports"
                  className="w-full px-4 py-2.5 bg-background border border-card-border rounded-xl text-foreground placeholder-text-muted text-sm focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary"
                />
              </div>

              <div>
                <label className="block text-[10px] font-bold text-text-muted uppercase tracking-wider mb-1.5">
                  Description
                </label>
                <textarea
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="Contains PDF and Word filings relating to quarterly company financial balances."
                  className="w-full px-4 py-2.5 bg-background border border-card-border rounded-xl text-foreground placeholder-text-muted text-sm focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary h-24 resize-none"
                />
              </div>

              <div>
                <label className="block text-[10px] font-bold text-text-muted uppercase tracking-wider mb-1.5">
                  Embedding Model
                </label>
                <select
                  value={embedModel}
                  onChange={(e) => setEmbedModel(e.target.value)}
                  className="w-full px-4 py-2.5 bg-background border border-card-border rounded-xl text-foreground text-sm focus:outline-none focus:border-primary"
                >
                  <option value="BAAI/bge-large-en-v1.5">BAAI BGE Large v1.5 (1024 Dim) [Recommended]</option>
                  <option value="text-embedding-3-small">OpenAI text-embedding-3-small (1536 Dim)</option>
                  <option value="text-embedding-3-large">OpenAI text-embedding-3-large (3072 Dim)</option>
                </select>
              </div>

              <div className="pt-2 flex gap-4">
                <button
                  type="button"
                  onClick={() => setIsModalOpen(false)}
                  className="flex-1 py-2.5 bg-background hover:bg-card-border/20 border border-card-border text-foreground text-sm font-semibold rounded-xl transition-all duration-200"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={modalLoading}
                  className="flex-1 py-2.5 bg-primary hover:bg-primary-hover text-background text-sm font-semibold rounded-xl transition-all duration-200 disabled:opacity-50"
                >
                  {modalLoading ? "Creating..." : "Create"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
