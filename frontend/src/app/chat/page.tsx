"use client";

import { useEffect, useState, useRef, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  MessageSquare,
  Send,
  Plus,
  Compass,
  Cpu,
  Globe,
  Loader2,
  FileText,
  Clock,
  Sparkles,
  ChevronRight,
  Database,
  Edit2,
  Trash2,
  Check,
  X,
  ThumbsUp,
  ThumbsDown,
  Eye,
  BookOpen,
  Pin,
  Notebook,
  Menu
} from "lucide-react";
import MarkdownRenderer from "@/components/MarkdownRenderer";
import { api, authStorage, KnowledgeBase, Conversation, Message, UserNote } from "@/lib/api";

function ChatPageContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const chatBottomRef = useRef<HTMLDivElement>(null);

  const [showMobileSidebar, setShowMobileSidebar] = useState(false);
  const [kbs, setKbs] = useState<KnowledgeBase[]>([]);
  const [selectedKBId, setSelectedKBId] = useState("");
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeConvId, setActiveConvId] = useState<string>("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [query, setQuery] = useState("");
  const [editingConvId, setEditingConvId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const [deletingIds, setDeletingIds] = useState<string[]>([]);
  const [renamingIds, setRenamingIds] = useState<string[]>([]);
  
  // Streaming/Agent status
  const [isStreaming, setIsStreaming] = useState(false);
  const [agentStatus, setAgentStatus] = useState<string | null>(null);
  const [streamingText, setStreamingText] = useState("");
  const [streamingCitations, setStreamingCitations] = useState<any[]>([]);
  const [webSearchEnabled, setWebSearchEnabled] = useState(false);
  
  // Diagnostics comparison (pre/post rerank vectors)
  const [retrievalStats, setRetrievalStats] = useState<any>(null);

  // NotebookLM Checklist Sources
  const [kbDocs, setKbDocs] = useState<any[]>([]);
  const [selectedDocIds, setSelectedDocIds] = useState<string[]>([]);

  // Citation split-screen inspector
  const [inspectorDocId, setInspectorDocId] = useState<string | null>(null);
  const [inspectorDocName, setInspectorDocName] = useState<string | null>(null);
  const [inspectorChunks, setInspectorChunks] = useState<any[]>([]);
  const [inspectorLoading, setInspectorLoading] = useState(false);
  const [highlightText, setHighlightText] = useState<string | null>(null);
  const [activeCitationPage, setActiveCitationPage] = useState<number | null>(null);

  // Notebook Guide Tab
  const [activeMainTab, setActiveMainTab] = useState<"chat" | "guide">("chat");
  const [guide, setGuide] = useState<any | null>(null);
  const [guideLoading, setGuideLoading] = useState(false);

  // Sticky Notes states
  const [showNotesPanel, setShowNotesPanel] = useState(false);
  const [notes, setNotes] = useState<UserNote[]>([]);
  const [selectedNoteIds, setSelectedNoteIds] = useState<string[]>([]);
  const [synthesisText, setSynthesisText] = useState<string | null>(null);
  const [synthesisLoading, setSynthesisLoading] = useState(false);
  const [isNoteModalOpen, setIsNoteModalOpen] = useState(false);
  const [noteTitle, setNoteTitle] = useState("");
  const [noteContent, setNoteContent] = useState("");
  const [editingNoteId, setEditingNoteId] = useState<string | null>(null);

  useEffect(() => {
    const token = authStorage.getToken();
    if (!token) {
      router.push("/login");
      return;
    }
    initChat();
  }, [router]);

  useEffect(() => {
    // Autoscroll to bottom when streaming or new message arrives
    chatBottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streamingText, agentStatus]);

  // Load documents and notes when KB selection changes
  useEffect(() => {
    if (!selectedKBId) return;
    
    api.listDocs(selectedKBId)
      .then((docs) => {
        setKbDocs(docs || []);
        setSelectedDocIds([]); // reset selection
      })
      ;
      
    loadNotes();
    setGuide(null);
    if (activeMainTab === "guide") {
      loadGuide();
    }
  }, [selectedKBId]);

  // Load guide when guide tab is opened
  useEffect(() => {
    if (activeMainTab === "guide" && !guide && !guideLoading) {
      loadGuide();
    }
  }, [activeMainTab]);

  // Autoscroll to target citation page chunk in inspector
  useEffect(() => {
    if (inspectorChunks.length > 0 && activeCitationPage !== null) {
      setTimeout(() => {
        const element = document.getElementById(`chunk-page-${activeCitationPage}`);
        if (element) {
          element.scrollIntoView({ behavior: "smooth", block: "center" });
        }
      }, 100);
    }
  }, [inspectorChunks, activeCitationPage]);

  const loadNotes = async () => {
    if (!selectedKBId) return;
    try {
      const data = await api.listUserNotes(selectedKBId);
      setNotes(data || []);
    } catch (e) {
      
    }
  };

  const loadGuide = async () => {
    if (!selectedKBId) return;
    setGuideLoading(true);
    try {
      const data = await api.getKBGuide(selectedKBId);
      setGuide(data);
    } catch (e) {
      
    } finally {
      setGuideLoading(false);
    }
  };

  const handleOpenCitationInspector = async (docName: string, pageNum: number, highlightContent: string) => {
    const docObj = kbDocs.find((d) => d.filename === docName);
    if (!docObj) return;
    
    setInspectorDocId(docObj.id);
    setInspectorDocName(docName);
    setInspectorLoading(true);
    setHighlightText(highlightContent);
    setActiveCitationPage(pageNum);
    
    try {
      const data = await api.listDocChunks(docObj.id);
      setInspectorChunks(data || []);
    } catch (err) {
      
    } finally {
      setInspectorLoading(false);
    }
  };

  const handleFaqClick = (question: string) => {
    setQuery(question);
    setActiveMainTab("chat");
    handleSendMessage(undefined, question);
  };

  const handleSaveMessageToNotes = async (msg: Message) => {
    if (!selectedKBId) return;
    try {
      const summaryTitle = msg.content.substring(0, 30).trim() + "...";
      await api.createUserNote({
        kb_id: selectedKBId,
        title: `Pinned response: ${summaryTitle}`,
        content: msg.content
      });
      alert("Pinned to Sticky Notes successfully!");
      await loadNotes();
    } catch (err) {
      
      alert("Failed to pin note.");
    }
  };

  const handleSaveCustomNote = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!noteTitle.trim() || !noteContent.trim() || !selectedKBId) return;
    try {
      if (editingNoteId) {
        await api.updateUserNote(editingNoteId, { title: noteTitle, content: noteContent });
      } else {
        await api.createUserNote({
          kb_id: selectedKBId,
          title: noteTitle,
          content: noteContent
        });
      }
      setIsNoteModalOpen(false);
      setNoteTitle("");
      setNoteContent("");
      setEditingNoteId(null);
      await loadNotes();
    } catch (e) {
      
      alert("Failed to save note.");
    }
  };

  const handleEditNote = (note: UserNote) => {
    setEditingNoteId(note.id);
    setNoteTitle(note.title);
    setNoteContent(note.content);
    setIsNoteModalOpen(true);
  };

  const handleDeleteNote = async (noteId: string) => {
    if (!confirm("Are you sure you want to delete this note?")) return;
    try {
      await api.deleteUserNote(noteId);
      setSelectedNoteIds((prev) => prev.filter((id) => id !== noteId));
      await loadNotes();
    } catch (e) {
      
    }
  };

  const handleSynthesizeNotes = async (format: string = "outline") => {
    if (selectedNoteIds.length === 0) return;
    setSynthesisLoading(true);
    setSynthesisText(null);
    try {
      const res = await api.synthesizeNotes(selectedNoteIds, format);
      setSynthesisText(res.synthesis);
    } catch (e) {
      
      alert("Failed to synthesize notes.");
    } finally {
      setSynthesisLoading(false);
    }
  };

  const initChat = async () => {
    try {
      // 1. Fetch KBs
      const kbList = await api.listKBs();
      setKbs(kbList);
      
      const queryKBId = searchParams.get("kb_id");
      if (queryKBId) {
        setSelectedKBId(queryKBId);
      } else if (kbList.length > 0) {
        setSelectedKBId(kbList[0].id);
      }

      // 2. Fetch Conversations
      const convList = await api.listConversations();
      setConversations(convList);
      if (convList.length > 0) {
        await handleSelectConversation(convList[0].id);
      } else if (kbList.length > 0) {
        // Create initial conversation
        const targetKB = queryKBId || kbList[0].id;
        await handleCreateConversation(targetKB);
      }
    } catch (err) {
      
    }
  };

  const handleSelectConversation = async (convId: string) => {
    setActiveConvId(convId);
    setStreamingText("");
    setStreamingCitations([]);
    setAgentStatus(null);
    setRetrievalStats(null);
    try {
      const msgList = await api.listMessages(convId);
      setMessages(msgList);
      
      // Update selected KB dropdown based on this conversation's KB
      const convObj = conversations.find((c) => c.id === convId);
      if (convObj && convObj.kb_id) {
        setSelectedKBId(convObj.kb_id);
      }
    } catch (err) {
      
    }
  };

  const handleCreateConversation = async (kbId: string) => {
    if (!kbId) return;
    try {
      const kbName = kbs.find((k) => k.id === kbId)?.name || "Chat";
      const newConv = await api.createConversation(kbId, `Chat - ${kbName}`);
      setConversations((prev) => [newConv, ...prev]);
      setActiveConvId(newConv.id);
      setMessages([]);
      setStreamingText("");
      setStreamingCitations([]);
      setAgentStatus(null);
      setRetrievalStats(null);
    } catch (err) {
      
    }
  };

  const handleStartRename = (conv: Conversation, e: React.MouseEvent) => {
    e.stopPropagation();
    setEditingConvId(conv.id);
    setEditTitle(conv.title);
  };

  const handleSaveRename = async (convId: string, e: React.FormEvent | React.MouseEvent) => {
    if (e) e.preventDefault();
    if (!editTitle.trim() || renamingIds.includes(convId)) return;
    setRenamingIds((prev) => [...prev, convId]);
    try {
      const updatedConv = await api.renameConversation(convId, editTitle.trim());
      setConversations((prev) =>
        prev.map((c) => (c.id === convId ? { ...c, title: updatedConv.title } : c))
      );
      setEditingConvId(null);
    } catch (err) {
      
    } finally {
      setRenamingIds((prev) => prev.filter((id) => id !== convId));
    }
  };

  const handleDeleteConversation = async (convId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (deletingIds.includes(convId)) return;
    if (!window.confirm("Are you sure you want to delete this conversation?")) {
      return;
    }
    setDeletingIds((prev) => [...prev, convId]);
    try {
      await api.deleteConversation(convId);
      const newConvList = conversations.filter((c) => c.id !== convId);
      setConversations(newConvList);
      if (activeConvId === convId) {
        if (newConvList.length > 0) {
          await handleSelectConversation(newConvList[0].id);
        } else {
          await handleCreateConversation(selectedKBId);
        }
      }
    } catch (err) {
      
    } finally {
      setDeletingIds((prev) => prev.filter((id) => id !== convId));
    }
  };

  const handleRateMessage = async (msgId: string, logId: string, rating: number) => {
    try {
      const msg = messages.find((m) => m.id === msgId);
      const targetRating = msg?.rating === rating ? 0 : rating;
      await api.rateQueryLog(logId, targetRating);
      setMessages((prev) =>
        prev.map((m) => (m.id === msgId ? { ...m, rating: targetRating } : m))
      );
    } catch (err) {
      
    }
  };

  const handleSendMessage = async (e?: React.FormEvent, customQuery?: string) => {
    if (e) e.preventDefault();
    const queryText = (customQuery || query).trim();
    if (!queryText || isStreaming || !activeConvId) return;

    setQuery("");
    setIsStreaming(true);
    setStreamingText("");
    setStreamingCitations([]);
    setAgentStatus("Planning retrieval...");
    setRetrievalStats(null);

    // Add user message locally
    const tempUserMsg: Message = {
      id: `temp-user-${Date.now()}`,
      sender: "user",
      content: queryText,
      created_at: new Date().toISOString()
    };
    setMessages((prev) => [...prev, tempUserMsg]);

    let accumulatedText = "";
    let finalCitations: any[] = [];
    let finalMetadata: any = null;

    const cancelStream = api.streamMessage(
      {
        conversation_id: activeConvId,
        query: queryText,
        web_search_enabled: webSearchEnabled,
        document_ids: selectedDocIds.length > 0 ? selectedDocIds : undefined
      },
      (event, data) => {
        if (event === "status") {
          setAgentStatus(data.message);
        } else if (event === "retrieval_debug") {
          // Store raw search data before BGE Rerank comparison
          setRetrievalStats(data);
        } else if (event === "token") {
          setAgentStatus(null); // clear status once generation starts
          accumulatedText += data.text;
          setStreamingText(accumulatedText);
        } else if (event === "metadata") {
          finalCitations = data.citations || [];
          setStreamingCitations(finalCitations);
          finalMetadata = data;
        }
      },
      () => {
        // Complete
        setIsStreaming(false);
        setAgentStatus(null);
        setStreamingText("");
        
        // Add final assistant message locally
        const tempAssistantMsg: Message = {
          id: `temp-assistant-${Date.now()}`,
          sender: "assistant",
          content: accumulatedText,
          citations: finalCitations,
          latency: finalMetadata?.latency,
          retrieval_score: finalMetadata?.confidence_score ? finalMetadata.confidence_score / 100 : 0.8,
          query_log_id: finalMetadata?.query_log_id,
          created_at: new Date().toISOString()
        };
        setMessages((prev) => [...prev, tempAssistantMsg]);
        
        // Reload conversations to refresh timestamps/ordering
        api.listConversations().then(setConversations);
      },
      (err) => {
        setIsStreaming(false);
        setAgentStatus(`Error: ${err.message}`);
        
      }
    );
  };

  const followUps = [
    "Summarize the key takeaways of the document.",
    "Show me tables or structured metrics mentioned.",
    "What are the specific parameters described?"
  ];

  const renderSidebar = (isMobile: boolean = false) => {
    return (
      <div className="h-full flex flex-col justify-between overflow-hidden">
        <div className="space-y-4 overflow-hidden flex flex-col h-full">
          <div className="flex justify-between items-center pb-2 border-b border-card-border/50">
            <span className="text-sm font-bold text-foreground">Conversations</span>
            <button
              onClick={() => {
                handleCreateConversation(selectedKBId);
                if (isMobile) setShowMobileSidebar(false);
              }}
              className="p-1.5 bg-primary/20 border border-primary/30 rounded-lg text-primary hover:bg-primary/30 cursor-pointer"
              title="New Conversation"
            >
              <Plus className="w-4 h-4" />
            </button>
          </div>

          <div className="flex-1 overflow-y-auto space-y-1 pr-1">
            {conversations.map((conv) => {
              const isActive = conv.id === activeConvId;
              const isEditing = conv.id === editingConvId;

              if (isEditing) {
                return (
                  <form
                    key={conv.id}
                    onSubmit={(e) => handleSaveRename(conv.id, e)}
                    className="w-full flex items-center space-x-1.5 px-2.5 py-2 rounded-2xl bg-card-border/20 border border-card-border"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <input
                      type="text"
                      required
                      autoFocus
                      value={editTitle}
                      onChange={(e) => setEditTitle(e.target.value)}
                      className="bg-background border border-card-border rounded-xl px-2 py-1.5 text-xs text-foreground focus:outline-none flex-1 min-w-0"
                    />
                    <button
                      type="submit"
                      className="p-1 text-emerald-400 hover:bg-card-border/30 rounded-lg cursor-pointer"
                      title="Save"
                    >
                      <Check className="w-3.5 h-3.5" />
                    </button>
                    <button
                      type="button"
                      onClick={() => setEditingConvId(null)}
                      className="p-1 text-red-400 hover:bg-card-border/30 rounded-lg cursor-pointer"
                      title="Cancel"
                    >
                      <X className="w-3.5 h-3.5" />
                    </button>
                  </form>
                );
              }

              return (
                <div
                  key={conv.id}
                  onClick={() => {
                    handleSelectConversation(conv.id);
                    if (isMobile) setShowMobileSidebar(false);
                  }}
                  className={`w-full flex items-center justify-between px-3 py-2.5 rounded-2xl text-left transition-all duration-200 group cursor-pointer ${
                    isActive
                      ? "bg-primary/10 border border-primary/25 text-foreground"
                      : "text-text-muted hover:bg-card-border/20 hover:text-foreground"
                  }`}
                >
                  <div className="flex items-center space-x-2.5 min-w-0 flex-1">
                    <MessageSquare className={`w-4 h-4 shrink-0 ${isActive ? "text-primary" : "text-text-muted"}`} />
                    <span className="truncate text-xs font-semibold block">{conv.title}</span>
                  </div>
                  
                  <div className="flex items-center space-x-1 opacity-0 group-hover:opacity-100 transition-opacity ml-2 shrink-0">
                    <button
                      onClick={(e) => handleStartRename(conv, e)}
                      className="p-1 hover:bg-card-border/30 text-text-muted hover:text-foreground rounded-lg cursor-pointer transition-colors"
                      title="Rename Conversation"
                    >
                      <Edit2 className="w-3.5 h-3.5" />
                    </button>
                    <button
                      onClick={(e) => handleDeleteConversation(conv.id, e)}
                      className="p-1 hover:bg-red-500/20 text-text-muted hover:text-red-400 rounded-lg cursor-pointer transition-colors"
                      title="Delete Conversation"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* KB Selection in Chat */}
        <div className="border-t border-card-border pt-4 mt-2">
          <label className="block text-[10px] font-bold text-text-muted uppercase tracking-wider mb-2 flex items-center gap-1.5">
            <Database className="w-3.5 h-3.5 text-primary" />
            <span>Target Index</span>
          </label>
          <select
            value={selectedKBId}
            onChange={(e) => {
              setSelectedKBId(e.target.value);
              handleCreateConversation(e.target.value);
              if (isMobile) setShowMobileSidebar(false);
            }}
            className="w-full bg-background border border-card-border rounded-2xl py-2 px-3 text-xs text-foreground focus:outline-none"
          >
            {kbs.map((kb) => (
              <option key={kb.id} value={kb.id}>
                {kb.name}
              </option>
            ))}
          </select>
        </div>

        {/* KB Documents Checklist (NotebookLM style sources) */}
        {selectedKBId && (
          <div className="border-t border-card-border pt-4 mt-4 flex-1 min-h-0 flex flex-col">
            <label className="block text-[10px] font-bold text-text-muted uppercase tracking-wider mb-2 flex items-center justify-between">
              <span className="flex items-center gap-1.5">
                <FileText className="w-3.5 h-3.5 text-secondary" />
                <span>Sources ({selectedDocIds.length}/{kbDocs.length})</span>
              </span>
              {selectedDocIds.length > 0 && (
                <button
                  type="button"
                  onClick={() => setSelectedDocIds([])}
                  className="text-[9px] text-primary hover:underline font-bold cursor-pointer"
                >
                  Clear
                </button>
              )}
            </label>
            <div className="flex-1 overflow-y-auto space-y-2 pr-1">
              {kbDocs.length === 0 ? (
                <span className="text-[10px] text-text-muted italic block py-2">No documents indexed. Go to Uploads.</span>
              ) : (
                kbDocs.map((doc) => {
                  const isChecked = selectedDocIds.includes(doc.id);
                  return (
                    <label
                      key={doc.id}
                      className={`flex items-center space-x-2 p-2 rounded-xl border text-[10px] font-semibold cursor-pointer transition-all duration-200 ${
                        isChecked
                          ? "bg-secondary/15 border-secondary/35 text-foreground"
                          : "bg-background/40 border-card-border text-text-muted hover:border-card-border/60 hover:text-foreground"
                      }`}
                    >
                      <input
                        type="checkbox"
                        checked={isChecked}
                        onChange={(e) => {
                          if (e.target.checked) {
                            setSelectedDocIds((prev) => [...prev, doc.id]);
                          } else {
                            setSelectedDocIds((prev) => prev.filter((id) => id !== doc.id));
                          }
                        }}
                        className="rounded border-card-border text-primary focus:ring-primary h-3.5 w-3.5 shrink-0 cursor-pointer"
                      />
                      <span className="truncate flex-1" title={doc.filename}>{doc.filename}</span>
                    </label>
                  );
                })
              )}
            </div>
          </div>
        )}
      </div>
    );
  };

  return (
    <div className="mt-4 h-[calc(100dvh-7rem)] md:mt-6 md:h-[calc(100vh-7.5rem)] flex gap-4 md:gap-6 overflow-hidden relative">
      {/* MOBILE LEFT: Conversation sidebar drawer */}
      {showMobileSidebar && (
        <>
          <div
            className="fixed inset-0 bg-background/60 backdrop-blur-sm z-50 lg:hidden"
            onClick={() => setShowMobileSidebar(false)}
          />
          <div className="fixed inset-y-0 left-0 z-50 w-64 glass border-r border-card-border p-4 flex flex-col justify-between bg-background/95 animate-slide-in-left lg:hidden">
            {renderSidebar(true)}
          </div>
        </>
      )}

      {/* DESKTOP LEFT: Conversation sidebar */}
      <div className="w-64 glass border border-card-border rounded-3xl p-4 flex flex-col justify-between shrink-0 lg:flex hidden">
        {renderSidebar(false)}
      </div>

      {/* RIGHT: Chat Window */}
      <div className="flex-1 glass border border-card-border rounded-3xl flex flex-col justify-between overflow-hidden">
        {/* Top Header */}
        <div className="px-4 sm:px-6 py-3 sm:py-4 border-b border-card-border/50 flex flex-wrap gap-3 justify-between items-center bg-card/25">
          <div className="flex items-center space-x-2 sm:space-x-3">
            <button
              onClick={() => setShowMobileSidebar(true)}
              className="lg:hidden p-2 -ml-2 text-text-muted hover:text-foreground hover:bg-card-border/30 rounded-xl"
            >
              <Menu className="w-5 h-5" />
            </button>
            <div className="hidden sm:block bg-primary/15 p-2 rounded-xl text-primary border border-primary/25">
              <Cpu className="w-4 h-4" />
            </div>
            <div>
              <span className="text-sm font-bold text-foreground block max-w-[120px] sm:max-w-none truncate">
                {kbs.find((k) => k.id === selectedKBId)?.name || "Agentic RAG Engine"}
              </span>
              <span className="text-[10px] text-text-muted hidden sm:block">GPT-4o + BM25 & Qdrant Hybrid Search</span>
            </div>
          </div>

          {/* Center Tab Selectors */}
          <div className="flex bg-background/50 border border-card-border/50 p-1 rounded-2xl order-3 w-full sm:w-auto sm:order-2 justify-center">
            <button
              onClick={() => setActiveMainTab("chat")}
              className={`flex items-center space-x-1.5 px-3.5 py-1.5 rounded-xl text-xs font-semibold transition-all duration-200 cursor-pointer flex-1 sm:flex-none justify-center ${
                activeMainTab === "chat"
                  ? "bg-primary text-background shadow-md shadow-primary/15"
                  : "text-text-muted hover:text-background"
              }`}
            >
              <MessageSquare className="w-3.5 h-3.5" />
              <span>Chat Console</span>
            </button>
            <button
              onClick={() => setActiveMainTab("guide")}
              className={`flex items-center space-x-1.5 px-3.5 py-1.5 rounded-xl text-xs font-semibold transition-all duration-200 cursor-pointer flex-1 sm:flex-none justify-center ${
                activeMainTab === "guide"
                  ? "bg-primary text-background shadow-md shadow-primary/15"
                  : "text-text-muted hover:text-background"
              }`}
            >
              <BookOpen className="w-3.5 h-3.5" />
              <span>Notebook Guide</span>
            </button>
          </div>

          {/* Right side controls */}
          <div className="flex items-center space-x-2 sm:space-x-2.5 order-2 sm:order-3">
            {/* Notes Panel Toggle */}
            <button
              onClick={() => setShowNotesPanel(!showNotesPanel)}
              className={`flex items-center space-x-1.5 px-2 sm:px-3 py-1.5 rounded-full text-xs font-semibold border transition-all duration-200 cursor-pointer ${
                showNotesPanel
                  ? "bg-accent/15 text-accent border-accent/35"
                  : "bg-background text-text-muted border-card-border hover:text-foreground"
              }`}
              title="Sticky Notes"
            >
              <Notebook className="w-3.5 h-3.5" />
              <span className="hidden sm:inline">Sticky Notes ({notes.length})</span>
              <span className="sm:hidden">{notes.length}</span>
            </button>

            {/* Web search toggle */}
            <button
              onClick={() => setWebSearchEnabled(!webSearchEnabled)}
              className={`flex items-center space-x-1.5 px-2 sm:px-3 py-1.5 rounded-full text-xs font-semibold border transition-all duration-200 cursor-pointer ${
                webSearchEnabled
                  ? "bg-secondary/15 text-secondary border-secondary/35"
                  : "bg-background text-text-muted border-card-border hover:text-foreground"
              }`}
              title="Web Search"
            >
              <Globe className="w-3.5 h-3.5" />
              <span className="hidden sm:inline">Web Search</span>
            </button>
          </div>
        </div>

        {activeMainTab === "chat" ? (
          <>
            {/* Message area */}
            <div className="flex-1 overflow-y-auto p-4 sm:p-6 space-y-4 sm:space-y-6">
              {messages.length === 0 && !isStreaming ? (
                <div className="flex flex-col items-center justify-center h-full text-center px-4 animate-in fade-in zoom-in duration-500">
                  <div className="w-16 h-16 bg-primary/15 rounded-full flex items-center justify-center mb-6 shadow-[0_0_30px_rgba(var(--primary-rgb),0.15)] border border-primary/20">
                    <Sparkles className="w-8 h-8 text-primary" />
                  </div>
                  <h2 className="text-2xl font-bold text-foreground mb-2">Welcome to Aegis RAG</h2>
                  <p className="text-sm text-text-muted max-w-md mb-8">
                    Start by typing a query below, or choose one of our suggested prompts to explore your knowledge base.
                  </p>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 max-w-2xl w-full">
                    {[
                      "Summarize the key takeaways of the uploaded documents.",
                      "What are the main parameters or metrics described?",
                      "Find any tables or structured data and explain them.",
                      "Are there any specific action items or recommendations?"
                    ].map((prompt, idx) => (
                      <button
                        key={idx}
                        onClick={() => handleSendMessage(undefined, prompt)}
                        className="text-left p-4 rounded-2xl bg-card border border-card-border/60 hover:border-primary/50 hover:bg-primary/5 transition-all group cursor-pointer"
                      >
                        <p className="text-sm text-muted-foreground group-hover:text-primary transition-colors">{prompt}</p>
                      </button>
                    ))}
                  </div>
                </div>
              ) : (
                <>
                  {messages.map((msg) => {
                    const isUser = msg.sender === "user";
                    return (
                      <div key={msg.id} className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
                        <div className={`max-w-[90%] sm:max-w-[75%] rounded-3xl p-4 sm:p-5 ${
                          isUser
                            ? "bg-primary text-background rounded-br-none shadow-md shadow-primary/10"
                            : "glass border border-card-border/50 text-foreground rounded-bl-none"
                        }`}>
                          {isUser ? (
                            <p className="text-sm leading-relaxed">{msg.content}</p>
                          ) : (
                            <div>
                              <MarkdownRenderer content={msg.content} />

                          {/* Assistant actions bar (Metas and Note Pinning) */}
                          <div className="mt-4 pt-3 border-t border-card-border/30 flex items-center justify-between text-[10px] text-text-muted font-mono">
                            <div className="flex items-center space-x-4">
                              {msg.latency && (
                                <span className="flex items-center gap-1">
                                  <Clock className="w-3 h-3 text-violet-400" />
                                  <span>Latency: {msg.latency.toFixed(2)}s</span>
                                </span>
                              )}
                              {msg.retrieval_score && (
                                <span className="flex items-center gap-1">
                                  <Sparkles className="w-3 h-3 text-cyan-400" />
                                  <span>Confidence: {(msg.retrieval_score * 100).toFixed(0)}%</span>
                                </span>
                              )}
                            </div>
                            
                            <div className="flex items-center space-x-2">
                              <button
                                onClick={() => handleSaveMessageToNotes(msg)}
                                className="p-1 hover:bg-accent/15 text-text-muted hover:text-accent rounded-lg cursor-pointer transition-colors flex items-center gap-1"
                                title="Pin to Notes"
                              >
                                <Pin className="w-3 h-3" />
                                <span>Pin</span>
                              </button>

                              {msg.query_log_id && (
                                <div className="flex items-center space-x-2 border-l border-card-border/30 pl-2">
                                  <button
                                    onClick={() => handleRateMessage(msg.id, msg.query_log_id!, 1)}
                                    className={`p-1 hover:bg-green-500/10 rounded-lg cursor-pointer transition-colors ${
                                      msg.rating === 1 ? "text-green-400" : "text-text-muted hover:text-green-400"
                                    }`}
                                    title="Thumbs Up (Helpful)"
                                  >
                                    <ThumbsUp className="w-3.5 h-3.5" />
                                  </button>
                                  <button
                                    onClick={() => handleRateMessage(msg.id, msg.query_log_id!, -1)}
                                    className={`p-1 hover:bg-red-500/10 rounded-lg cursor-pointer transition-colors ${
                                      msg.rating === -1 ? "text-red-400" : "text-text-muted hover:text-red-400"
                                    }`}
                                    title="Thumbs Down (Unhelpful)"
                                  >
                                    <ThumbsDown className="w-3.5 h-3.5" />
                                  </button>
                                </div>
                              )}
                            </div>
                          </div>

                          {/* Source Citations */}
                          {msg.citations && msg.citations.length > 0 && (
                            <div className="mt-4 pt-3 border-t border-card-border/30">
                              <span className="text-[10px] uppercase font-bold text-text-muted block mb-2 tracking-wider">Citations</span>
                              <div className="flex flex-wrap gap-2">
                                {msg.citations.map((cit, cIdx) => (
                                  <button
                                    key={cIdx}
                                    onClick={() => handleOpenCitationInspector(cit.source_doc, cit.page, msg.content)}
                                    className="flex items-center space-x-1.5 px-3 py-1 bg-card border border-card-border rounded-xl text-xs text-primary hover:border-primary/50 transition-colors cursor-pointer text-left"
                                    title="Inspect Passage"
                                  >
                                    <FileText className="w-3 h-3 shrink-0" />
                                    <span className="max-w-[120px] truncate">{cit.source_doc}</span>
                                    <span className="text-[10px] text-text-muted font-bold shrink-0">p.{cit.page}</span>
                                  </button>
                                ))}
                              </div>
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}

              {/* Streaming Assistant output */}
              {isStreaming && (streamingText || agentStatus) && (
                <div className="flex justify-start animate-pulse-slow">
                  <div className="max-w-[90%] sm:max-w-[75%] rounded-3xl p-4 sm:p-5 glass border border-card-border/50 text-foreground rounded-bl-none">
                    {agentStatus && (
                      <div className="flex items-center space-x-2.5 text-xs text-text-muted py-1.5">
                        <Loader2 className="w-4 h-4 text-primary animate-spin" />
                        <span>{agentStatus}</span>
                      </div>
                    )}
                    {streamingText && (
                      <div>
                        <MarkdownRenderer content={streamingText} />
                        
                        {/* Citations preview */}
                        {streamingCitations.length > 0 && (
                          <div className="mt-4 pt-3 border-t border-card-border/30">
                            <span className="text-[10px] uppercase font-bold text-text-muted block mb-2 tracking-wider">Citations</span>
                            <div className="flex flex-wrap gap-2">
                              {streamingCitations.map((cit, cIdx) => (
                                <button
                                  key={cIdx}
                                  onClick={() => handleOpenCitationInspector(cit.source_doc, cit.page, streamingText)}
                                  className="flex items-center space-x-1.5 px-3 py-1 bg-card border border-card-border rounded-xl text-xs text-primary hover:border-primary/50 transition-colors cursor-pointer text-left"
                                  title="Inspect Passage"
                                >
                                  <FileText className="w-3 h-3 shrink-0" />
                                  <span className="max-w-[120px] truncate">{cit.source_doc}</span>
                                  <span className="text-[10px] text-text-muted font-bold shrink-0">p.{cit.page}</span>
                                </button>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              )}

              <div ref={chatBottomRef} />
                </>
              )}
            </div>

            {/* Suggested Queries */}
            {!isStreaming && messages.length > 0 && (
              <div className="px-6 py-2 flex flex-wrap gap-2 bg-card/10 border-t border-card-border/30">
                {followUps.map((item, idx) => (
                  <button
                    key={idx}
                    onClick={() => handleSendMessage(undefined, item)}
                    className="flex items-center space-x-1 text-xs text-text-muted hover:text-foreground px-3 py-1.5 bg-card border border-card-border/50 rounded-xl hover:border-card-border transition-colors cursor-pointer"
                  >
                    <span>{item}</span>
                    <ChevronRight className="w-3 h-3" />
                  </button>
                ))}
              </div>
            )}

            {/* Input Bar */}
            <div className="p-4 sm:p-6 border-t border-card-border/50 bg-card/25">
              <form onSubmit={handleSendMessage} className="relative flex items-center">
                <input
                  type="text"
                  required
                  disabled={isStreaming || !activeConvId}
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder={activeConvId ? "Query knowledge base using agent RAG..." : "Select a conversation to query..."}
                  className="w-full bg-background border border-card-border rounded-2xl pl-4 pr-16 py-4 text-foreground placeholder-text-muted focus:outline-none focus:border-primary disabled:opacity-50 text-sm"
                />
                <button
                  type="submit"
                  disabled={isStreaming || !query.trim() || !activeConvId}
                  className="absolute right-3 p-3 bg-primary hover:bg-primary-hover text-background rounded-xl shadow-lg transition-all duration-200 disabled:opacity-50 cursor-pointer"
                >
                  <Send className="w-4 h-4" />
                </button>
              </form>
            </div>
          </>
        ) : (
          /* Notebook Guide View */
          <div className="flex-1 overflow-y-auto p-4 sm:p-6 space-y-4 sm:space-y-6">
            {guideLoading ? (
              <div className="flex flex-col items-center justify-center h-64 text-text-muted">
                <Loader2 className="w-8 h-8 animate-spin text-primary mb-2" />
                <p className="text-sm">Synthesizing notebook guide from sources...</p>
              </div>
            ) : guide ? (
              <div className="space-y-6">
                {/* Briefing Summary */}
                <div className="glass border border-card-border/50 rounded-3xl p-6 relative overflow-hidden">
                  <div className="absolute top-0 right-0 w-32 h-32 bg-primary/10 rounded-full blur-3xl pointer-events-none" />
                  <div className="flex items-center space-x-2 mb-4">
                    <Sparkles className="w-5 h-5 text-primary animate-pulse" />
                    <h3 className="text-base font-bold text-foreground">Knowledge Briefing</h3>
                  </div>
                  <p className="text-sm text-muted-foreground leading-relaxed whitespace-pre-wrap">{guide.summary}</p>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  {/* FAQs Section */}
                  <div className="glass border border-card-border/50 rounded-3xl p-6 flex flex-col h-fit">
                    <div className="flex items-center space-x-2 mb-4">
                      <BookOpen className="w-5 h-5 text-secondary" />
                      <h3 className="text-base font-bold text-foreground">Suggested FAQs</h3>
                    </div>
                    <div className="space-y-3">
                      {guide.faqs && guide.faqs.length > 0 ? (
                        guide.faqs.map((faq: any, index: number) => (
                          <div key={index} className="border border-card-border/40 rounded-2xl overflow-hidden bg-card/20 hover:border-card-border transition-colors">
                            <details className="group">
                              <summary className="flex justify-between items-center p-4 text-xs font-bold text-foreground cursor-pointer select-none">
                                <span className="pr-4">{faq.question}</span>
                                <span className="transition group-open:rotate-180 text-text-muted">
                                  <ChevronRight className="w-4 h-4" />
                                </span>
                              </summary>
                              <div className="px-4 pb-4 text-xs leading-relaxed text-text-muted border-t border-card-border/20 pt-3 space-y-3">
                                <p>{faq.answer}</p>
                                <button
                                  onClick={() => handleFaqClick(faq.question)}
                                  className="flex items-center space-x-1.5 px-3 py-1.5 bg-primary/10 border border-primary/20 hover:bg-primary/25 rounded-lg text-[10px] font-bold text-primary transition-colors cursor-pointer"
                                >
                                  <Send className="w-3 h-3" />
                                  <span>Ask in Chat</span>
                                </button>
                              </div>
                            </details>
                          </div>
                        ))
                      ) : (
                        <p className="text-xs text-text-muted italic">No FAQs available.</p>
                      )}
                    </div>
                  </div>

                  {/* Glossary Section */}
                  <div className="glass border border-card-border/50 rounded-3xl p-6 flex flex-col h-fit">
                    <div className="flex items-center space-x-2 mb-4">
                      <Compass className="w-5 h-5 text-accent" />
                      <h3 className="text-base font-bold text-foreground">Glossary of Key Terms</h3>
                    </div>
                    <div className="space-y-3">
                      {guide.key_terms && guide.key_terms.length > 0 ? (
                        <div className="grid grid-cols-1 gap-3">
                          {guide.key_terms.map((item: any, index: number) => (
                            <div key={index} className="p-4 rounded-2xl border border-card-border/30 bg-card/10 hover:border-card-border transition-colors">
                              <span className="text-xs font-bold text-foreground block mb-1">{item.term}</span>
                              <span className="text-xs text-text-muted leading-relaxed">{item.definition}</span>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <p className="text-xs text-text-muted italic">No key terms identified.</p>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            ) : (
              <div className="flex flex-col items-center justify-center h-64 text-text-muted space-y-3">
                <BookOpen className="w-10 h-10 text-text-muted/50 animate-pulse" />
                <p className="text-sm">No guide loaded for this Knowledge Base.</p>
                <button
                  onClick={loadGuide}
                  className="px-4 py-2 bg-primary hover:bg-primary-hover text-background text-xs font-semibold rounded-xl transition-all cursor-pointer"
                >
                  Generate Guide
                </button>
              </div>
            )}
          </div>
        )}
      </div>

      {/* STICKY NOTES SIDEBAR PANEL */}
      {showNotesPanel && (
        <>
          {/* Mobile Overlay */}
          <div
            className="fixed inset-0 bg-background/60 backdrop-blur-sm z-[60] lg:hidden"
            onClick={() => setShowNotesPanel(false)}
          />
          <div className="fixed inset-y-0 right-0 z-[70] w-full max-w-[320px] bg-background/95 border-l border-card-border p-4 flex flex-col justify-between overflow-hidden animate-slide-in-right lg:relative lg:inset-auto lg:w-80 lg:bg-transparent lg:border lg:rounded-3xl lg:z-auto shrink-0 glass">
          <div className="flex flex-col h-full overflow-hidden space-y-4">
            {/* Header */}
            <div className="flex justify-between items-center pb-2 border-b border-card-border/50">
              <div className="flex items-center space-x-2">
                <Notebook className="w-4 h-4 text-accent" />
                <span className="text-sm font-bold text-foreground">Sticky Notes</span>
              </div>
              <div className="flex items-center space-x-1.5">
                <button
                  onClick={() => {
                    setEditingNoteId(null);
                    setNoteTitle("");
                    setNoteContent("");
                    setIsNoteModalOpen(true);
                  }}
                  className="p-1 bg-accent/20 border border-accent/30 rounded-lg text-accent hover:bg-accent/30 cursor-pointer"
                  title="Create Custom Note"
                >
                  <Plus className="w-3.5 h-3.5" />
                </button>
                <button
                  onClick={() => setShowNotesPanel(false)}
                  className="p-1 hover:bg-card-border/30 rounded-lg text-text-muted hover:text-foreground cursor-pointer"
                  title="Close Notes Panel"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              </div>
            </div>

            {/* List */}
            <div className="flex-1 overflow-y-auto space-y-3 pr-1">
              {notes.length === 0 ? (
                <div className="flex flex-col items-center justify-center h-48 text-text-muted text-center space-y-2">
                  <Notebook className="w-8 h-8 text-text-muted/40" />
                  <p className="text-xs">No notes saved yet. Pin assistant responses or add custom notes.</p>
                </div>
              ) : (
                notes.map((note) => {
                  const isSelected = selectedNoteIds.includes(note.id);
                  return (
                    <div
                      key={note.id}
                      className={`p-3 rounded-2xl border text-xs relative group transition-all duration-200 ${
                        isSelected
                          ? "bg-accent/10 border-accent/45"
                          : "bg-card/25 border-card-border/60 hover:border-card-border"
                      }`}
                    >
                      <div className="flex items-start justify-between gap-2 mb-1.5">
                        <label className="flex items-center gap-2 cursor-pointer min-w-0 flex-1">
                          <input
                            type="checkbox"
                            checked={isSelected}
                            onChange={(e) => {
                              if (e.target.checked) {
                                setSelectedNoteIds((prev) => [...prev, note.id]);
                              } else {
                                setSelectedNoteIds((prev) => prev.filter((id) => id !== note.id));
                              }
                            }}
                            className="rounded border-card-border text-accent focus:ring-accent h-3.5 w-3.5 cursor-pointer shrink-0"
                          />
                          <span className="font-bold text-foreground truncate block">{note.title}</span>
                        </label>
                        <div className="flex items-center space-x-1 opacity-0 group-hover:opacity-100 transition-opacity shrink-0">
                          <button
                            onClick={() => handleEditNote(note)}
                            className="p-1 text-text-muted hover:text-foreground hover:bg-card-border/30 rounded-md cursor-pointer"
                            title="Edit"
                          >
                            <Edit2 className="w-3 h-3" />
                          </button>
                          <button
                            onClick={() => handleDeleteNote(note.id)}
                            className="p-1 text-text-muted hover:text-red-400 hover:bg-red-500/10 rounded-md cursor-pointer"
                            title="Delete"
                          >
                            <Trash2 className="w-3 h-3" />
                          </button>
                        </div>
                      </div>
                      <p className="text-[11px] text-text-muted whitespace-pre-wrap line-clamp-3 leading-normal">{note.content}</p>
                    </div>
                  );
                })
              )}
            </div>

            {/* Actions */}
            {selectedNoteIds.length > 0 && (
              <div className="border-t border-card-border/50 pt-3 space-y-2">
                <div className="flex justify-between items-center text-[10px] text-text-muted">
                  <span>{selectedNoteIds.length} notes selected</span>
                  <button
                    onClick={() => setSelectedNoteIds([])}
                    className="text-accent hover:underline font-semibold cursor-pointer"
                  >
                    Deselect
                  </button>
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <button
                    onClick={() => handleSynthesizeNotes("outline")}
                    disabled={synthesisLoading}
                    className="py-2 px-3 bg-accent/20 border border-accent/30 hover:bg-accent/35 text-foreground text-xs font-semibold rounded-xl transition-all cursor-pointer disabled:opacity-50 flex items-center justify-center gap-1.5"
                  >
                    {synthesisLoading ? <Loader2 className="w-3 h-3 animate-spin" /> : <Sparkles className="w-3 h-3" />}
                    <span>Write Outline</span>
                  </button>
                  <button
                    onClick={() => handleSynthesizeNotes("report")}
                    disabled={synthesisLoading}
                    className="py-2 px-3 bg-primary/20 border border-primary/30 hover:bg-primary/35 text-foreground text-xs font-semibold rounded-xl transition-all cursor-pointer disabled:opacity-50 flex items-center justify-center gap-1.5"
                  >
                    {synthesisLoading ? <Loader2 className="w-3 h-3 animate-spin" /> : <Sparkles className="w-3 h-3" />}
                    <span>Write Briefing</span>
                  </button>
                </div>
              </div>
            )}
          </div>

          {/* Synthesis Drawer overlay */}
          {synthesisText && (
            <div className="absolute inset-0 bg-background/95 z-50 p-4 flex flex-col justify-between overflow-hidden animate-slide-in-right">
              <div className="flex flex-col h-full overflow-hidden space-y-4">
                <div className="flex justify-between items-center pb-2 border-b border-card-border/50">
                  <div className="flex items-center space-x-2">
                    <Sparkles className="w-4 h-4 text-accent animate-pulse" />
                    <span className="text-xs font-bold text-foreground">Synthesized Draft</span>
                  </div>
                  <button
                    onClick={() => setSynthesisText(null)}
                    className="p-1 hover:bg-card-border/30 rounded-lg text-text-muted hover:text-foreground cursor-pointer"
                    title="Close Draft"
                  >
                    <X className="w-3.5 h-3.5" />
                  </button>
                </div>

                <div className="flex-1 overflow-y-auto pr-1 text-xs leading-relaxed text-muted-foreground space-y-3 bg-card/25 border border-card-border/40 p-3 rounded-2xl">
                  <MarkdownRenderer content={synthesisText} />
                </div>

                <div className="flex gap-2">
                  <button
                    onClick={() => {
                      navigator.clipboard.writeText(synthesisText);
                      alert("Copied draft to clipboard!");
                    }}
                    className="flex-1 py-2 bg-primary hover:bg-primary-hover text-background text-xs font-semibold rounded-xl transition-all cursor-pointer flex items-center justify-center gap-1.5"
                  >
                    <Check className="w-3.5 h-3.5" />
                    <span>Copy</span>
                  </button>
                  <button
                    onClick={() => setSynthesisText(null)}
                    className="px-3 py-2 bg-card border border-card-border text-text-muted hover:text-foreground text-xs font-semibold rounded-xl transition-all cursor-pointer"
                  >
                    Close
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
        </>
      )}

      {/* CITATION PASSAGE INSPECTOR PANEL */}
      {inspectorDocId && (
        <>
          {/* Mobile Overlay */}
          <div
            className="fixed inset-0 bg-background/60 backdrop-blur-sm z-[60] lg:hidden"
            onClick={() => {
              setInspectorDocId(null);
              setInspectorDocName(null);
              setInspectorChunks([]);
              setActiveCitationPage(null);
            }}
          />
          <div className="fixed inset-y-0 right-0 z-[70] w-full max-w-[320px] bg-background/95 border-l border-card-border p-4 flex flex-col justify-between overflow-hidden animate-slide-in-right lg:relative lg:inset-auto lg:w-80 lg:bg-transparent lg:border lg:rounded-3xl lg:z-auto shrink-0 glass">
          <div className="flex flex-col h-full overflow-hidden space-y-4">
            {/* Header */}
            <div className="flex justify-between items-center pb-2 border-b border-card-border/50">
              <div className="flex items-center space-x-2 min-w-0 flex-1">
                <Eye className="w-4 h-4 text-secondary" />
                <span className="text-sm font-bold text-foreground truncate" title={inspectorDocName || "Source Inspector"}>
                  {inspectorDocName || "Source Inspector"}
                </span>
              </div>
              <button
                onClick={() => {
                  setInspectorDocId(null);
                  setInspectorDocName(null);
                  setInspectorChunks([]);
                  setActiveCitationPage(null);
                }}
                className="p-1 hover:bg-card-border/30 rounded-lg text-text-muted hover:text-foreground cursor-pointer shrink-0"
                title="Close Inspector"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            </div>

            {/* Chunks list */}
            <div className="flex-1 overflow-y-auto space-y-4 pr-1">
              {inspectorLoading ? (
                <div className="flex flex-col items-center justify-center h-48 text-text-muted">
                  <Loader2 className="w-8 h-8 animate-spin text-secondary mb-2" />
                  <p className="text-xs">Loading source passages...</p>
                </div>
              ) : inspectorChunks.length === 0 ? (
                <div className="flex flex-col items-center justify-center h-48 text-text-muted text-center">
                  <FileText className="w-8 h-8 text-text-muted/40 mb-2" />
                  <p className="text-xs">No passages found for this document.</p>
                </div>
              ) : (
                inspectorChunks.map((chunk) => {
                  const isTargetPage = chunk.page_number === activeCitationPage;
                  return (
                    <div
                      key={chunk.id}
                      id={`chunk-page-${chunk.page_number}`}
                      className={`p-5 rounded-2xl border text-xs leading-relaxed transition-all duration-300 hover:border-primary/50 hover:bg-background/60 ${
                        isTargetPage
                          ? "bg-secondary/15 border-secondary/50 shadow-md shadow-secondary/5 accent-glow"
                          : "bg-card/25 border-card-border/60"
                      }`}
                    >
                      <div className="flex justify-between items-center mb-3 pb-2 border-b border-card-border/30 text-[10px] text-text-muted font-mono">
                        <span className="flex items-center gap-1">
                          <FileText className="w-3.5 h-3.5 text-secondary" />
                          <span>Page {chunk.page_number || "N/A"}</span>
                        </span>
                        <span>Index {chunk.chunk_index || 0}</span>
                      </div>
                      <p className="text-[11px] text-muted-foreground whitespace-pre-wrap leading-normal font-sans pr-1">
                        {chunk.content}
                      </p>
                    </div>
                  );
                })
              )}
            </div>
          </div>
        </div>
        </>
      )}

      {/* CREATE/EDIT STICKY NOTE MODAL DIALOG */}
      {isNoteModalOpen && (
        <div className="fixed inset-0 bg-background/80 backdrop-blur-sm z-[100] flex items-center justify-center p-4 md:pl-72">
          <div className="w-full max-w-md bg-card border border-card-border rounded-3xl p-6 shadow-2xl relative overflow-hidden animate-zoom-in">
            <div className="absolute top-0 right-0 w-32 h-32 bg-accent/10 rounded-full blur-3xl pointer-events-none" />
            <div className="flex justify-between items-center mb-4 pb-2 border-b border-card-border/50">
              <h3 className="text-sm font-bold text-foreground flex items-center gap-1.5">
                <Notebook className="w-4 h-4 text-accent" />
                <span>{editingNoteId ? "Edit Note" : "Create Sticky Note"}</span>
              </h3>
              <button
                onClick={() => setIsNoteModalOpen(false)}
                className="p-1 hover:bg-card-border/30 rounded-lg text-text-muted hover:text-foreground cursor-pointer"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
            <form onSubmit={handleSaveCustomNote} className="space-y-4">
              <div className="space-y-1">
                <label className="block text-[10px] uppercase font-bold text-text-muted">Title</label>
                <input
                  type="text"
                  required
                  placeholder="Enter note title..."
                  value={noteTitle}
                  onChange={(e) => setNoteTitle(e.target.value)}
                  className="w-full bg-background border border-card-border rounded-xl px-3 py-2 text-xs text-foreground focus:outline-none focus:border-accent"
                />
              </div>
              <div className="space-y-1">
                <label className="block text-[10px] uppercase font-bold text-text-muted">Content</label>
                <textarea
                  required
                  rows={6}
                  placeholder="Write your note content..."
                  value={noteContent}
                  onChange={(e) => setNoteContent(e.target.value)}
                  className="w-full bg-background border border-card-border rounded-xl px-3 py-2 text-xs text-foreground focus:outline-none focus:border-accent resize-none"
                />
              </div>
              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setIsNoteModalOpen(false)}
                  className="px-4 py-2 bg-card border border-card-border rounded-xl text-text-muted hover:text-foreground text-xs font-semibold cursor-pointer transition-all"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-4 py-2 bg-accent hover:bg-accent-hover text-foreground text-xs font-semibold rounded-xl cursor-pointer transition-all"
                >
                  Save Note
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

export default function ChatPage() {
  return (
    <Suspense fallback={
      <div className="flex h-[calc(100dvh-5.5rem)] md:h-[calc(100dvh-4rem)] items-center justify-center text-foreground">
        <Loader2 className="w-8 h-8 animate-spin text-primary" />
        <span className="ml-2 text-sm text-text-muted">Loading Chat...</span>
      </div>
    }>
      <ChatPageContent />
    </Suspense>
  );
}
