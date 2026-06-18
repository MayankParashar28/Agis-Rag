"use client";

import { useEffect, useState, useRef, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  UploadCloud,
  FileText,
  Trash2,
  RefreshCw,
  Database,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Search,
  Eye,
  X
} from "lucide-react";
import { api, authStorage, KnowledgeBase, DocumentInfo } from "@/lib/api";

function UploadPageContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [kbs, setKbs] = useState<KnowledgeBase[]>([]);
  const [selectedKBId, setSelectedKBId] = useState<string>("");
  const [documents, setDocuments] = useState<DocumentInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Settings parameters
  const [chunkSize, setChunkSize] = useState(1000);
  const [chunkOverlap, setChunkOverlap] = useState(200);

  // Search & Filter
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");

  // Chunk inspector states
  const [inspectorDoc, setInspectorDoc] = useState<DocumentInfo | null>(null);
  const [chunks, setChunks] = useState<any[]>([]);
  const [chunksLoading, setChunksLoading] = useState(false);
  const [inspectorError, setInspectorError] = useState<string | null>(null);
  const [chunkSearchQuery, setChunkSearchQuery] = useState("");

  // Fetch KBs list on mount
  useEffect(() => {
    const token = authStorage.getToken();
    if (!token) {
      router.push("/login");
      return;
    }

    const fetchKBs = async () => {
      try {
        const kbList = await api.listKBs();
        setKbs(kbList);
        
        // Select KB from URL query parameter or default to first KB
        const queryKBId = searchParams.get("kb_id");
        if (queryKBId) {
          setSelectedKBId(queryKBId);
        } else if (kbList.length > 0) {
          setSelectedKBId(kbList[0].id);
        }
      } catch (err: any) {
        setError(err.message || "Failed to load knowledge bases.");
      } finally {
        setLoading(false);
      }
    };

    fetchKBs();
  }, [router, searchParams]);

  // Fetch documents when selectedKBId changes
  useEffect(() => {
    if (!selectedKBId) return;
    fetchDocs();

    // Start polling if there are documents processing
    const pollInterval = setInterval(() => {
      // Check if any doc is in processing status
      setDocuments((prev) => {
        const needsPolling = prev.some((d) => d.status === "processing");
        if (needsPolling) {
          // Trigger docs reload
          fetchDocsSilently();
        }
        return prev;
      });
    }, 3000);

    return () => clearInterval(pollInterval);
  }, [selectedKBId]);

  const fetchDocs = async () => {
    try {
      const docsList = await api.listDocs(selectedKBId);
      setDocuments(docsList);
    } catch (err: any) {
      setError(err.message || "Failed to load documents.");
    }
  };

  const fetchDocsSilently = async () => {
    try {
      const docsList = await api.listDocs(selectedKBId);
      setDocuments(docsList);
    } catch (_) {}
  };

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files || files.length === 0 || !selectedKBId) return;
    
    setError(null);
    setUploading(true);
    
    try {
      const file = files[0];
      
      // 50MB limit check
      if (file.size > 50 * 1024 * 1024) {
        setError("File exceeds the maximum allowed size of 50MB.");
        setUploading(false);
        if (fileInputRef.current) fileInputRef.current.value = "";
        return;
      }
      
      await api.uploadDoc(selectedKBId, file, chunkSize, chunkOverlap);
      await fetchDocs();
      // Clear file input
      if (fileInputRef.current) fileInputRef.current.value = "";
    } catch (err: any) {
      setError(err.message || "Failed to upload document.");
    } finally {
      setUploading(false);
    }
  };

  const handleDeleteDoc = async (docId: string, filename: string) => {
    if (!confirm(`Are you sure you want to delete "${filename}"? All chunks and embeddings will be removed from Qdrant.`)) {
      return;
    }

    try {
      await api.deleteDoc(docId);
      setDocuments((prev) => prev.filter((d) => d.id !== docId));
    } catch (err: any) {
      alert(err.message || "Failed to delete document.");
    }
  };

  const handleReindexDoc = async (docId: string) => {
    try {
      await api.reindexDoc(docId);
      await fetchDocs();
    } catch (err: any) {
      alert(err.message || "Failed to trigger reindexing.");
    }
  };

  const handleOpenInspector = async (doc: DocumentInfo) => {
    setInspectorDoc(doc);
    setChunks([]);
    setChunksLoading(true);
    setInspectorError(null);
    setChunkSearchQuery("");
    try {
      const data = await api.listDocChunks(doc.id);
      setChunks(data || []);
    } catch (err: any) {
      setInspectorError(err.message || "Failed to load document chunks.");
    } finally {
      setChunksLoading(false);
    }
  };

  const filteredDocs = documents.filter((doc) => {
    const matchesSearch = doc.filename.toLowerCase().includes(searchQuery.toLowerCase());
    const matchesStatus = statusFilter === "all" || doc.status === statusFilter;
    return matchesSearch && matchesStatus;
  });

  const filteredChunks = chunks.filter((chunk) =>
    chunk.content.toLowerCase().includes(chunkSearchQuery.toLowerCase())
  );

  const triggerFileSelect = () => {
    fileInputRef.current?.click();
  };

  const formatBytes = (bytes: number, decimals = 2) => {
    if (!+bytes) return "0 Bytes";
    const k = 1024;
    const dm = decimals < 0 ? 0 : decimals;
    const sizes = ["Bytes", "KB", "MB", "GB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return `${parseFloat((bytes / Math.pow(k, i)).toFixed(dm))} ${sizes[i]}`;
  };

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-extrabold text-foreground tracking-tight">Upload Documents</h1>
        <p className="text-text-muted mt-1">Ingest PDF, DOCX, TXT, or CSV files into your Knowledge Bases</p>
      </div>

      {/* Select KB Bar */}
      <div className="glass p-6 rounded-3xl border border-card-border flex flex-col md:flex-row gap-6 md:items-center justify-between">
        <div className="flex items-center space-x-3">
          <div className="bg-primary/20 p-2.5 rounded-xl border border-primary/30 text-primary">
            <Database className="w-5 h-5" />
          </div>
          <div>
            <label className="block text-xs font-semibold text-text-muted uppercase tracking-wider mb-1">
              Select Target Knowledge Base
            </label>
            {loading ? (
              <div className="h-6 w-32 bg-card-border/30 animate-pulse rounded" />
            ) : (
              <select
                value={selectedKBId}
                onChange={(e) => setSelectedKBId(e.target.value)}
                className="bg-transparent text-foreground font-bold text-lg focus:outline-none cursor-pointer"
              >
                {kbs.map((kb) => (
                  <option key={kb.id} value={kb.id} className="bg-card text-foreground">
                    {kb.name}
                  </option>
                ))}
              </select>
            )}
          </div>
        </div>

        {/* Chunk Parameter Details */}
        <div className="flex gap-6 border-t md:border-t-0 md:border-l border-card-border pt-4 md:pt-0 md:pl-6">
          <div>
            <label className="block text-[10px] font-bold text-text-muted uppercase tracking-wider mb-1">
              Chunk Size
            </label>
            <input
              type="number"
              value={chunkSize}
              onChange={(e) => setChunkSize(Number(e.target.value))}
              className="w-20 bg-background border border-card-border rounded-xl text-center py-1.5 text-foreground font-semibold focus:outline-none focus:border-primary text-sm"
            />
          </div>
          <div>
            <label className="block text-[10px] font-bold text-text-muted uppercase tracking-wider mb-1">
              Overlap
            </label>
            <input
              type="number"
              value={chunkOverlap}
              onChange={(e) => setChunkOverlap(Number(e.target.value))}
              className="w-20 bg-background border border-card-border rounded-xl text-center py-1.5 text-foreground font-semibold focus:outline-none focus:border-primary text-sm"
            />
          </div>
        </div>
      </div>

      {error && (
        <div className="flex items-start space-x-2 p-4 rounded-2xl bg-red-500/10 border border-red-500/20 text-red-400 text-sm">
          <AlertTriangle className="w-5 h-5 shrink-0 mt-0.5" />
          <span>{error}</span>
        </div>
      )}

      {selectedKBId ? (
        <div className="grid grid-cols-1 xl:grid-cols-3 gap-8">
          {/* Ingestion Dropzone */}
          <div className="xl:col-span-1 space-y-6">
            <div className="flex items-start space-x-2 p-4 rounded-2xl bg-yellow-500/10 border border-yellow-500/20 text-yellow-500 text-xs font-medium">
              <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
              <span>Warning: Maximum allowed file size is 50MB. Larger files will be rejected to prevent memory overload.</span>
            </div>
            
            <div
              onClick={triggerFileSelect}
              className={`glass border-2 border-dashed rounded-3xl p-8 text-center cursor-pointer transition-all duration-300 hover:border-primary/50 group flex flex-col justify-center items-center min-h-[300px] ${
                uploading ? "opacity-50 pointer-events-none" : "border-card-border"
              }`}
            >
              <input
                type="file"
                ref={fileInputRef}
                onChange={handleFileChange}
                accept=".pdf,.docx,.txt,.csv"
                className="hidden"
              />
              <div className="bg-primary/10 p-5 rounded-2xl border border-primary/20 mb-4 group-hover:scale-110 transition-transform duration-300">
                <UploadCloud className="w-8 h-8 text-primary" />
              </div>
              <h3 className="text-base font-bold text-foreground mb-2">Drag & Drop File Here</h3>
              <p className="text-xs text-text-muted max-w-xs leading-relaxed">
                or click to browse from local filesystem. Supported extensions: .pdf, .docx, .txt, .csv (Max 50MB)
              </p>
              {uploading && (
                <div className="mt-6 flex items-center space-x-2 text-primary text-sm font-semibold">
                  <div className="w-4 h-4 border-2 border-primary border-t-transparent rounded-full animate-spin" />
                  <span>Parsing & indexing document...</span>
                </div>
              )}
            </div>
            
            {/* Parser Instructions Tip */}
            <div className="glass p-6 rounded-3xl border border-card-border">
              <span className="text-[10px] uppercase font-bold tracking-wider text-primary">Advanced Pipeline</span>
              <h4 className="text-sm font-bold text-foreground mt-1 mb-2">LlamaParse Integration</h4>
              <p className="text-xs text-text-muted leading-relaxed">
                When a file is uploaded, our pipeline calls **LlamaParse** (or a local fallback) to parse tables and layout trees, applies **recursive hierarchy chunking**, and indexes BGE embeddings in Qdrant.
              </p>
            </div>
          </div>

          {/* Document list table */}
          <div className="xl:col-span-2 glass border border-card-border rounded-3xl p-6 overflow-hidden flex flex-col">
            <h3 className="text-lg font-bold text-foreground mb-4">Ingested Collections</h3>
            
            {documents.length > 0 && (
              <div className="flex flex-col sm:flex-row gap-4 mb-6">
                <div className="relative flex-1">
                  <span className="absolute inset-y-0 left-0 pl-3 flex items-center text-text-muted">
                    <Search className="w-4 h-4" />
                  </span>
                  <input
                    type="text"
                    placeholder="Search documents by name..."
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    className="w-full bg-background border border-card-border rounded-xl pl-10 pr-4 py-2 text-foreground placeholder-text-muted focus:outline-none focus:border-primary text-xs transition-colors"
                  />
                </div>
                <div className="w-full sm:w-48">
                  <select
                    value={statusFilter}
                    onChange={(e) => setStatusFilter(e.target.value)}
                    className="w-full bg-background border border-card-border rounded-xl px-3 py-2 text-foreground focus:outline-none text-xs cursor-pointer"
                  >
                    <option value="all">All Statuses</option>
                    <option value="indexed">Ready / Indexed</option>
                    <option value="processing">Indexing / Processing</option>
                    <option value="failed">Failed</option>
                  </select>
                </div>
              </div>
            )}

            {documents.length === 0 ? (
              <div className="py-16 text-center text-text-muted">
                <FileText className="w-10 h-10 mx-auto mb-2 opacity-50" />
                <p className="text-sm">No documents uploaded to this Knowledge Base yet.</p>
              </div>
            ) : filteredDocs.length === 0 ? (
              <div className="py-16 text-center text-text-muted border border-dashed border-card-border/50 rounded-2xl">
                <p className="text-sm">No documents match the search or filter criteria.</p>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead>
                    <tr className="border-b border-card-border/50 text-text-muted font-semibold">
                      <th className="py-3 pr-4">Filename</th>
                      <th className="py-3 px-4">Size</th>
                      <th className="py-3 px-4">Status</th>
                      <th className="py-3 pl-4 text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredDocs.map((doc) => (
                      <tr key={doc.id} className="border-b border-card-border/30 text-foreground hover:bg-card-border/10 transition-colors">
                        <td
                          className="py-4 pr-4 font-medium flex items-center space-x-3 cursor-pointer group/row"
                          onClick={() => doc.status === "indexed" && handleOpenInspector(doc)}
                          title={doc.status === "indexed" ? "Inspect vector chunks" : ""}
                        >
                          <FileText className="w-4 h-4 text-primary shrink-0 group-hover/row:scale-110 transition-transform" />
                          <span className="truncate max-w-[200px] md:max-w-xs group-hover/row:text-primary transition-colors" title={doc.filename}>{doc.filename}</span>
                        </td>
                        <td className="py-4 px-4 text-text-muted">{formatBytes(doc.file_size)}</td>
                        <td className="py-4 px-4">
                          {doc.status === "processing" && (
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
                          {doc.status === "failed" && (
                            <span className="inline-flex items-center space-x-1 text-xs text-red-400 font-semibold py-1 px-2.5 bg-red-500/10 rounded-full border border-red-500/20">
                              <XCircle className="w-3.5 h-3.5" />
                              <span>Failed</span>
                            </span>
                          )}
                        </td>
                        <td className="py-4 pl-4 text-right">
                          <div className="flex justify-end items-center space-x-2">
                            <button
                              onClick={() => handleOpenInspector(doc)}
                              disabled={doc.status !== "indexed"}
                              className="p-1.5 text-text-muted hover:bg-card-border/50 hover:text-foreground rounded-lg transition-all duration-200 cursor-pointer disabled:opacity-30 disabled:pointer-events-none"
                              title="Inspect Vector Chunks"
                            >
                              <Eye className="w-3.5 h-3.5" />
                            </button>
                            <button
                              onClick={() => handleReindexDoc(doc.id)}
                              disabled={doc.status === "processing"}
                              className="p-1.5 text-text-muted hover:bg-card-border/50 hover:text-foreground rounded-lg transition-all duration-200 cursor-pointer disabled:opacity-50"
                              title="Reindex Document"
                            >
                              <RefreshCw className="w-3.5 h-3.5" />
                            </button>
                            <button
                              onClick={() => handleDeleteDoc(doc.id, doc.filename)}
                              className="p-1.5 text-text-muted hover:bg-red-500/10 hover:text-red-400 rounded-lg transition-all duration-200 cursor-pointer"
                              title="Delete Document"
                            >
                              <Trash2 className="w-3.5 h-3.5" />
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      ) : (
        <div className="glass p-8 rounded-3xl border border-card-border text-center">
          <p className="text-sm text-text-muted">Please create a Knowledge Base first before uploading documents.</p>
        </div>
      )}

      {/* Chunk Inspector Modal Dialog */}
      {inspectorDoc && (
        <div className="fixed inset-0 bg-background/80 backdrop-blur-sm z-[100] flex items-center justify-center p-4 md:pl-72">
          <div className="w-full max-w-4xl glass border border-card-border rounded-3xl p-6 relative animate-scale-up flex flex-col max-h-[85vh]">
            <button
              onClick={() => setInspectorDoc(null)}
              className="absolute top-4 right-4 p-1.5 text-text-muted hover:bg-card-border/30 hover:text-foreground rounded-lg transition-all duration-200"
            >
              <X className="w-5 h-5" />
            </button>

            <div className="mb-4">
              <h2 className="text-xl font-bold text-foreground mb-1 flex items-center space-x-2">
                <FileText className="w-5 h-5 text-primary" />
                <span>Chunk Inspector</span>
              </h2>
              <p className="text-xs text-text-muted truncate max-w-2xl">
                Document: <span className="text-foreground font-semibold">{inspectorDoc.filename}</span> ({inspectorDoc.id})
              </p>
            </div>

            {/* Chunk Search Bar */}
            <div className="relative mb-4">
              <span className="absolute inset-y-0 left-0 pl-3 flex items-center text-text-muted">
                <Search className="w-4 h-4" />
              </span>
              <input
                type="text"
                placeholder="Filter parsed chunks by keyword..."
                value={chunkSearchQuery}
                onChange={(e) => setChunkSearchQuery(e.target.value)}
                className="w-full bg-background border border-card-border rounded-2xl pl-10 pr-4 py-2.5 text-foreground placeholder-text-muted focus:outline-none focus:border-primary text-xs"
              />
            </div>

            {/* Modal Body */}
            <div className="flex-1 overflow-y-auto min-h-0 space-y-4 pr-1">
              {chunksLoading ? (
                <div className="py-16 text-center space-y-2">
                  <div className="w-8 h-8 border-4 border-primary border-t-transparent rounded-full animate-spin mx-auto" />
                  <p className="text-sm text-text-muted">Retrieving document chunks from database...</p>
                </div>
              ) : inspectorError ? (
                <div className="py-12 flex items-start space-x-2 p-4 rounded-2xl bg-red-500/10 border border-red-500/20 text-red-400 text-xs">
                  <AlertTriangle className="w-5 h-5 shrink-0 mt-0.5" />
                  <span>{inspectorError}</span>
                </div>
              ) : filteredChunks.length === 0 ? (
                <div className="py-16 text-center text-text-muted border border-dashed border-card-border/50 rounded-2xl">
                  <p className="text-sm">No matching chunks found.</p>
                </div>
              ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  {filteredChunks.map((chunk) => (
                    <div
                      key={chunk.id}
                      className="p-6 bg-background/40 border border-card-border/60 rounded-2xl space-y-4 flex flex-col justify-between hover:border-primary/50 hover:bg-background/60 transition-all duration-300"
                    >
                      <div className="flex items-center justify-between text-[10px] font-bold text-text-muted border-b border-card-border/30 pb-3">
                        <span className="px-2 py-0.5 bg-primary/10 border border-primary/25 rounded-md text-primary">
                          Chunk #{chunk.chunk_index ?? 0}
                        </span>
                        {chunk.page_number !== null && (
                          <span className="px-2 py-0.5 bg-secondary/10 border border-secondary/25 rounded-md text-secondary">
                            Page {chunk.page_number}
                          </span>
                        )}
                        <span className="font-mono truncate max-w-[100px]" title={chunk.qdrant_point_id || ""}>
                          Pt: {chunk.qdrant_point_id ? chunk.qdrant_point_id.substring(0, 8) : "None"}...
                        </span>
                      </div>
                      
                      <p className="text-xs leading-relaxed text-muted-foreground font-mono whitespace-pre-wrap flex-1 max-h-48 overflow-y-auto pr-1">
                        {chunk.content}
                      </p>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="pt-4 border-t border-card-border/40 mt-4 flex justify-between items-center text-xs text-text-muted">
              <span>Total Chunks: {chunks.length}</span>
              <button
                type="button"
                onClick={() => setInspectorDoc(null)}
                className="px-5 py-2.5 bg-card border border-card-border hover:bg-card-border/20 text-foreground font-semibold rounded-xl transition-all duration-200 cursor-pointer"
              >
                Close Inspector
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default function UploadPage() {
  return (
    <Suspense fallback={
      <div className="flex h-full items-center justify-center text-foreground p-12">
        <RefreshCw className="w-8 h-8 animate-spin text-primary" />
        <span className="ml-2 text-sm text-text-muted">Loading Upload Page...</span>
      </div>
    }>
      <UploadPageContent />
    </Suspense>
  );
}
