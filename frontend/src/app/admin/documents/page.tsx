"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  FileText,
  Search,
  RefreshCw,
  Trash2,
  Database,
  Layers,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  FolderOpen
} from "lucide-react";
import { api, authStorage, AdminDocumentInfo } from "@/lib/api";

export default function AdminDocumentManagementPage() {
  const router = useRouter();
  
  const [documents, setDocuments] = useState<AdminDocumentInfo[]>([]);
  const [filteredDocs, setFilteredDocs] = useState<AdminDocumentInfo[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [actionLoadingId, setActionLoadingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const fetchDocs = async () => {
    try {
      const docList = await api.listAllDocumentsAdmin();
      setDocuments(docList);
      setFilteredDocs(docList);
    } catch (err: any) {
      setError(err.message || "Failed to retrieve global documents directory.");
    } finally {
      setLoading(false);
    }
  };

  const fetchDocsSilently = async () => {
    try {
      const docList = await api.listAllDocumentsAdmin();
      setDocuments(docList);
    } catch (_) {}
  };

  useEffect(() => {
    const token = authStorage.getToken();
    const user = authStorage.getUser();
    
    if (!token) {
      router.push("/login");
      return;
    }

    if (!user || user.role !== "admin") {
      router.push("/knowledge-bases");
      return;
    }

    fetchDocs();
  }, [router]);

  // Set up polling for active processing documents
  useEffect(() => {
    const pollInterval = setInterval(() => {
      const needsPolling = documents.some((d) => d.status === "processing");
      if (needsPolling) {
        fetchDocsSilently();
      }
    }, 4000);

    return () => clearInterval(pollInterval);
  }, [documents]);

  // Local Search Filtering
  useEffect(() => {
    const query = searchQuery.toLowerCase().trim();
    if (!query) {
      setFilteredDocs(documents);
      return;
    }

    const filtered = documents.filter(
      (d) =>
        d.filename.toLowerCase().includes(query) ||
        d.kb_name.toLowerCase().includes(query) ||
        d.file_type.toLowerCase().includes(query)
    );
    setFilteredDocs(filtered);
  }, [searchQuery, documents]);

  const handleReindex = async (docId: string, filename: string) => {
    try {
      setActionLoadingId(docId);
      setError(null);
      setSuccess(null);
      await api.reindexDocumentAdmin(docId);
      setSuccess(`Reindexing scheduled for "${filename}"`);
      await fetchDocs();
      setTimeout(() => setSuccess(null), 3000);
    } catch (err: any) {
      setError(err.message || `Failed to reindex document "${filename}"`);
    } finally {
      setActionLoadingId(null);
    }
  };

  const handleDelete = async (docId: string, filename: string) => {
    if (
      !confirm(
        `Are you sure you want to permanently delete "${filename}" globally? This clears all document chunks, metadata, and Qdrant vectors.`
      )
    ) {
      return;
    }

    try {
      setActionLoadingId(docId);
      setError(null);
      setSuccess(null);
      await api.deleteDocumentAdmin(docId);
      setSuccess(`Document "${filename}" deleted successfully.`);
      setDocuments((prev) => prev.filter((d) => d.id !== docId));
      setTimeout(() => setSuccess(null), 3000);
    } catch (err: any) {
      setError(err.message || `Failed to delete document "${filename}"`);
    } finally {
      setActionLoadingId(null);
    }
  };

  const formatBytes = (bytes: number, decimals = 2) => {
    if (!+bytes) return "0 Bytes";
    const k = 1024;
    const dm = decimals < 0 ? 0 : decimals;
    const sizes = ["Bytes", "KB", "MB", "GB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return `${parseFloat((bytes / Math.pow(k, i)).toFixed(dm))} ${sizes[i]}`;
  };

  if (loading && documents.length === 0) {
    return (
      <div className="flex items-center justify-center min-h-[50vh] text-foreground">
        <div className="text-center space-y-2">
          <div className="w-8 h-8 border-4 border-primary border-t-transparent rounded-full animate-spin mx-auto" />
          <p className="text-sm text-text-muted">Loading documents directory...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-8 animate-fade-in">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-extrabold text-foreground tracking-tight">Document Management</h1>
          <p className="text-text-muted mt-1">Audit chunk allocations, track pipeline statuses, and manage global collections</p>
        </div>
        <button
          onClick={fetchDocs}
          className="flex items-center space-x-2 px-4 py-2.5 bg-background border border-card-border hover:bg-card-border/20 text-foreground rounded-2xl font-semibold text-sm transition-all duration-200 cursor-pointer shrink-0"
        >
          <RefreshCw className="w-4 h-4" />
          <span>Refresh Directory</span>
        </button>
      </div>

      {/* Notifications */}
      {success && (
        <div className="flex items-center space-x-2 p-4 rounded-2xl bg-green-500/10 border border-green-500/20 text-green-400 text-sm animate-fade-in">
          <CheckCircle2 className="w-5 h-5 text-green-400 shrink-0" />
          <span>{success}</span>
        </div>
      )}

      {error && (
        <div className="flex items-start space-x-2 p-4 rounded-2xl bg-red-500/10 border border-red-500/20 text-red-400 text-sm animate-fade-in">
          <AlertTriangle className="w-5 h-5 shrink-0 mt-0.5" />
          <span>{error}</span>
        </div>
      )}

      {/* Search Filter bar */}
      <div className="glass p-4 rounded-3xl border border-card-border flex items-center space-x-3">
        <Search className="w-5 h-5 text-text-muted" />
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="Filter documents by filename, knowledge base name, or extension..."
          className="bg-transparent border-0 text-foreground placeholder-text-muted text-sm w-full focus:outline-none"
        />
      </div>

      {/* Main Table Directory */}
      <div className="glass border border-card-border rounded-3xl p-6 overflow-hidden">
        {filteredDocs.length === 0 ? (
          <div className="py-16 text-center text-text-muted">
            <FolderOpen className="w-12 h-12 mx-auto mb-2 opacity-30" />
            <p className="text-sm">No documents found matching your filter criteria.</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm border-collapse">
              <thead>
                <tr className="border-b border-card-border/50 text-text-muted font-semibold">
                  <th className="py-4 pr-4">File Name</th>
                  <th className="py-4 px-4">Knowledge Base</th>
                  <th className="py-4 px-4">Size</th>
                  <th className="py-4 px-4">Chunks</th>
                  <th className="py-4 px-4">Embedding Status</th>
                  <th className="py-4 pl-4 text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {filteredDocs.map((doc) => {
                  const isProcessing = doc.status === "processing";
                  const isFailed = doc.status === "failed";
                  const isActionLoading = actionLoadingId === doc.id;

                  return (
                    <tr
                      key={doc.id}
                      className="border-b border-card-border/30 text-foreground hover:bg-card-border/10 transition-colors"
                    >
                      {/* Name Details */}
                      <td className="py-4 pr-4 font-medium max-w-[200px] md:max-w-xs truncate">
                        <div className="flex items-center space-x-3">
                          <FileText className="w-5 h-5 text-primary shrink-0" />
                          <span title={doc.filename} className="truncate">{doc.filename}</span>
                        </div>
                      </td>

                      {/* Parent KB */}
                      <td className="py-4 px-4 text-text-muted">
                        <div className="flex items-center space-x-2 text-xs">
                          <Database className="w-3.5 h-3.5 text-card-border" />
                          <span className="font-semibold text-foreground/95">{doc.kb_name}</span>
                        </div>
                      </td>

                      {/* Size */}
                      <td className="py-4 px-4 text-text-muted">{formatBytes(doc.file_size)}</td>

                      {/* Chunk Allocation Count */}
                      <td className="py-4 px-4">
                        <div className="flex items-center space-x-1.5 text-xs text-amber-400 font-bold">
                          <Layers className="w-3.5 h-3.5" />
                          <span>{doc.chunk_count.toLocaleString()}</span>
                        </div>
                      </td>

                      {/* Embedding Status Badge */}
                      <td className="py-4 px-4">
                        {isProcessing && (
                          <span className="inline-flex items-center space-x-1 text-xs text-primary font-semibold py-1 px-2.5 bg-primary/10 rounded-full border border-primary/20">
                            <span className="w-1.5 h-1.5 bg-primary rounded-full animate-ping" />
                            <span>Indexing</span>
                          </span>
                        )}
                        {doc.status === "indexed" && (
                          <span className="inline-flex items-center space-x-1 text-xs text-emerald-400 font-semibold py-1 px-2.5 bg-emerald-500/10 rounded-full border border-emerald-500/20">
                            <CheckCircle2 className="w-3.5 h-3.5" />
                            <span>Ready</span>
                          </span>
                        )}
                        {isFailed && (
                          <span className="inline-flex items-center space-x-1 text-xs text-red-400 font-semibold py-1 px-2.5 bg-red-500/10 rounded-full border border-red-500/20">
                            <XCircle className="w-3.5 h-3.5" />
                            <span>Failed</span>
                          </span>
                        )}
                      </td>

                      {/* Reprocess / Delete Controls */}
                      <td className="py-4 pl-4 text-right">
                        <div className="flex justify-end items-center space-x-2">
                          {isActionLoading ? (
                            <div className="w-5 h-5 border-2 border-primary border-t-transparent rounded-full animate-spin mr-3" />
                          ) : (
                            <>
                              {/* Reindex Button */}
                              <button
                                onClick={() => handleReindex(doc.id, doc.filename)}
                                disabled={isProcessing}
                                className="p-2 text-text-muted hover:bg-card-border/50 hover:text-foreground rounded-xl transition-all duration-200 cursor-pointer disabled:opacity-50 disabled:pointer-events-none"
                                title="Reprocess & Reindex Document"
                              >
                                <RefreshCw className="w-4 h-4" />
                              </button>

                              {/* Delete Button */}
                              <button
                                onClick={() => handleDelete(doc.id, doc.filename)}
                                className="p-2 text-text-muted hover:bg-red-500/10 hover:text-red-400 rounded-xl transition-all duration-200 cursor-pointer"
                                title="Delete Document Globally"
                              >
                                <Trash2 className="w-4 h-4" />
                              </button>
                            </>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
