const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

export interface User {
  id: string;
  email: string;
  full_name: string | null;
  role: string;
  is_active: boolean;
  created_at: string;
}

export interface AuthResponse {
  access_token: string;
  token_type: string;
  user: User;
}

export interface KnowledgeBase {
  id: string;
  name: string;
  description: string | null;
  embedding_model: string;
  created_at: string;
  updated_at: string;
}

export interface DocumentInfo {
  id: string;
  kb_id: string;
  filename: string;
  file_type: string;
  file_size: number;
  status: string;
  meta_info: any;
  created_at: string;
}

export interface Message {
  id: string;
  sender: "user" | "assistant";
  content: string;
  citations?: Array<{
    source_doc: string;
    page: number;
    score: number;
  }>;
  latency?: number;
  retrieval_score?: number;
  created_at: string;
  query_log_id?: string;
  rating?: number;
}

export interface Conversation {
  id: string;
  title: string;
  kb_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface KBStats {
  total_documents: number;
  total_chunks: number;
  embedding_model: string;
  vector_count: number;
  last_indexed_date: string | null;
}

export interface DashboardStats {
  total_users: number;
  total_documents: number;
  total_chunks: number;
  total_queries: number;
  average_latency: number;
  average_retrieval_score: number;
  average_context_precision?: number;
  average_context_recall?: number;
  average_answer_relevancy?: number;
  average_hallucination_rate?: number;
  average_faithfulness?: number;
  user_satisfaction_rate?: number;
}

export interface DocumentChunk {
  id: string;
  doc_id: string;
  content: string;
  page_number: number | null;
  chunk_index: number | null;
  qdrant_point_id: string | null;
}

export interface KBGuide {
  summary: string;
  key_terms: Array<{ term: string; definition: string }>;
  faqs: Array<{ question: string; answer: string }>;
}

export interface UserNote {
  id: string;
  user_id: string;
  kb_id: string;
  title: string;
  content: string;
  created_at: string;
}

export interface AdminDocumentInfo {
  id: string;
  kb_id: string;
  kb_name: string;
  filename: string;
  file_type: string;
  file_size: number;
  status: string;
  chunk_count: number;
  created_at: string;
}


export interface ObservabilityLog {
  timestamp: string;
  query_latency: number;
  embedding_latency: number;
  retrieval_latency: number;
  hallucination_rate: number;
  retrieval_score: number;
}

export interface EvaluationResult {
  id: string;
  kb_id: string;
  faithfulness: number;
  context_precision: number;
  context_recall: number;
  answer_relevancy: number;
  created_at: string;
}

// Token Storage
const TOKEN_KEY = "rag_access_token";
const USER_KEY = "rag_user_data";

export const authStorage = {
  getToken: () => (typeof window !== "undefined" ? localStorage.getItem(TOKEN_KEY) : null),
  setToken: (token: string) => {
    localStorage.setItem(TOKEN_KEY, token);
    if (typeof document !== "undefined") {
      document.cookie = `${TOKEN_KEY}=${token}; path=/; max-age=604800; samesite=lax`;
    }
  },
  clear: () => {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
    if (typeof document !== "undefined") {
      document.cookie = `${TOKEN_KEY}=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT`;
    }
  },
  getUser: (): User | null => {
    if (typeof window === "undefined") return null;
    const data = localStorage.getItem(USER_KEY);
    return data ? JSON.parse(data) : null;
  },
  setUser: (user: User) => localStorage.setItem(USER_KEY, JSON.stringify(user)),
};

// Client-side caching layer to speed up page transitions and avoid blocking loaders
const apiCache: Record<string, { data: any; timestamp: number }> = {};
const CACHE_TTL = 30000; // 30 seconds cache validity

export const clearApiCache = (pathPrefix?: string) => {
  if (typeof window === "undefined") return;
  if (!pathPrefix) {
    for (const key in apiCache) {
      delete apiCache[key];
    }
  } else {
    for (const key in apiCache) {
      if (key.startsWith(pathPrefix)) {
        delete apiCache[key];
      }
    }
  }
};

// Request wrapper
async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const method = options.method || "GET";
  
  // Return cached result if valid (only for GET requests)
  if (method === "GET") {
    const cached = apiCache[path];
    if (cached && Date.now() - cached.timestamp < CACHE_TTL) {
      return cached.data as T;
    }
  } else {
    // Invalidate relevant cache sections on write operations
    if (path.startsWith("/knowledge-bases")) {
      clearApiCache("/knowledge-bases");
      clearApiCache("/analytics");
    } else if (path.startsWith("/documents")) {
      clearApiCache("/documents");
      clearApiCache("/knowledge-bases");
      clearApiCache("/analytics");
    } else if (path.startsWith("/chat")) {
      clearApiCache("/chat");
    } else if (path.startsWith("/auth")) {
      clearApiCache();
    } else {
      clearApiCache();
    }
  }

  const token = authStorage.getToken();
  const headers = new Headers(options.headers);
  
  if (token && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  
  if (!(options.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers,
  });

  if (response.status === 204) {
    return null as unknown as T;
  }

  if (!response.ok) {
    if (response.status === 401 || response.status === 403) {
      authStorage.clear();
      clearApiCache();
      if (typeof window !== "undefined") {
        const pathName = window.location.pathname;
        if (pathName !== "/login" && pathName !== "/register") {
          window.location.href = "/login";
        }
      }
    }
    let errMsg = "API Request failed";
    try {
      const errorJson = await response.json();
      errMsg = errorJson.detail || errMsg;
    } catch (_) {}
    throw new Error(errMsg);
  }

  const data = await response.json();
  
  // Cache successful GET requests
  if (method === "GET") {
    apiCache[path] = { data, timestamp: Date.now() };
  }
  
  return data;
}

export const api = {
  // Auth
  signup: (data: any) => request<User>("/auth/signup", { method: "POST", body: JSON.stringify(data) }),
  login: async (data: any) => {
    const res = await request<AuthResponse>("/auth/login", { method: "POST", body: JSON.stringify(data) });
    authStorage.setToken(res.access_token);
    authStorage.setUser(res.user);
    return res;
  },
  googleLogin: async (data: { id_token: string; full_name?: string }) => {
    const res = await request<AuthResponse>("/auth/google", { method: "POST", body: JSON.stringify(data) });
    authStorage.setToken(res.access_token);
    authStorage.setUser(res.user);
    return res;
  },
  logout: () => authStorage.clear(),

  // User Management
  listUsers: () => request<User[]>("/auth/users"),
  updateUser: (userId: string, data: { email?: string; full_name?: string; role?: string; is_active?: boolean }) => 
    request<User>(`/auth/users/${userId}`, { method: "PUT", body: JSON.stringify(data) }),


  // KB
  listKBs: () => request<KnowledgeBase[]>("/knowledge-bases"),
  createKB: (data: any) => request<KnowledgeBase>("/knowledge-bases", { method: "POST", body: JSON.stringify(data) }),
  deleteKB: (kbId: string) => request<void>(`/knowledge-bases/${kbId}`, { method: "DELETE" }),
  getKBStats: (kbId: string) => request<KBStats>(`/knowledge-bases/${kbId}/stats`),

  // Docs
  uploadDoc: (kbId: string, file: File, chunkSize: number = 1000, chunkOverlap: number = 200) => {
    const fd = new FormData();
    fd.append("kb_id", kbId);
    fd.append("file", file);
    fd.append("chunk_size", chunkSize.toString());
    fd.append("chunk_overlap", chunkOverlap.toString());
    return request<DocumentInfo>("/documents/upload", { method: "POST", body: fd });
  },
  listDocs: (kbId: string) => request<DocumentInfo[]>(`/documents/${kbId}`),
  deleteDoc: (docId: string) => request<void>(`/documents/${docId}`, { method: "DELETE" }),
  reindexDoc: (docId: string) => request<DocumentInfo>(`/documents/${docId}/reindex`, { method: "POST" }),

  // Admin Document Management
  listAllDocumentsAdmin: () => request<AdminDocumentInfo[]>("/documents/admin/all"),
  deleteDocumentAdmin: (docId: string) => request<void>(`/documents/admin/${docId}`, { method: "DELETE" }),
  reindexDocumentAdmin: (docId: string) => request<any>(`/documents/admin/${docId}/reindex`, { method: "POST" }),
  listDocChunks: (docId: string) => request<DocumentChunk[]>(`/documents/${docId}/chunks`),
  getKBGuide: (kbId: string) => request<KBGuide>(`/documents/kb/${kbId}/guide`),

  // Sticky Notes
  listUserNotes: (kbId: string) => request<UserNote[]>(`/notes?kb_id=${kbId}`),
  createUserNote: (data: { kb_id: string; title: string; content: string }) =>
    request<UserNote>("/notes", { method: "POST", body: JSON.stringify(data) }),
  updateUserNote: (noteId: string, data: { title?: string; content?: string }) =>
    request<UserNote>(`/notes/${noteId}`, { method: "PUT", body: JSON.stringify(data) }),
  deleteUserNote: (noteId: string) => request<void>(`/notes/${noteId}`, { method: "DELETE" }),
  synthesizeNotes: (noteIds: string[], format?: string) =>
    request<{ synthesis: string }>("/notes/synthesize", { method: "POST", body: JSON.stringify({ note_ids: noteIds, format }) }),


  // Chat
  listConversations: () => request<Conversation[]>("/chat/conversations"),
  createConversation: (kbId: string, title?: string) => 
    request<Conversation>("/chat/conversations", { method: "POST", body: JSON.stringify({ kb_id: kbId, title }) }),
  renameConversation: (convId: string, title: string) =>
    request<Conversation>(`/chat/conversations/${convId}`, { method: "PUT", body: JSON.stringify({ title }) }),
  deleteConversation: (convId: string) =>
    request<void>(`/chat/conversations/${convId}`, { method: "DELETE" }),
  listMessages: (convId: string) => request<Message[]>(`/chat/conversations/${convId}/messages`),

  // Diagnostics
  debugRetrieval: (kbId: string, query: string) => 
    request<any>("/retrieval/debug", { method: "POST", body: JSON.stringify({ kb_id: kbId, query }) }),

  // Analytics
  getDashboardStats: () => request<DashboardStats>("/analytics/dashboard"),
  getObservabilityLogs: () => request<ObservabilityLog[]>("/analytics/observability"),
  getConfigStatus: () => request<any>("/analytics/config-status"),
  rateQueryLog: (logId: string, rating: number) =>
    request<any>(`/analytics/query-logs/${logId}/rate`, { method: "POST", body: JSON.stringify({ rating }) }),

  // Evaluation
  runEvaluation: (kbId: string) => request<EvaluationResult>("/evaluation/run", { method: "POST", body: JSON.stringify({ kb_id: kbId }) }),
  getEvaluationHistory: (kbId: string) => request<EvaluationResult[]>(`/evaluation/results/${kbId}`),
  
  // Streaming event listener utility
  streamMessage: (
    queryData: { conversation_id: string; query: string; web_search_enabled: boolean; document_ids?: string[] },
    onEvent: (event: string, data: any) => void,
    onComplete: () => void,
    onError: (error: Error) => void
  ) => {
    const token = authStorage.getToken();
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
    };
    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    }

    const abortController = new AbortController();

    fetch(`${API_BASE_URL}/chat/message`, {
      method: "POST",
      headers,
      body: JSON.stringify(queryData),
      signal: abortController.signal,
    })
      .then((response) => {
        if (!response.ok) {
          throw new Error("Failed to start message stream");
        }
        
        const reader = response.body?.getReader();
        const decoder = new TextDecoder();
        if (!reader) {
          throw new Error("No reader available on response body");
        }
        const activeReader = reader;

        let buffer = "";

        function read() {
          activeReader.read()
            .then(({ done, value }) => {
              if (done) {
                onComplete();
                return;
              }

              buffer += decoder.decode(value, { stream: true });
              const lines = buffer.split("\n\n");
              // Keep the last partial line in buffer
              buffer = lines.pop() || "";

              for (const line of lines) {
                if (line.startsWith("data: ")) {
                  const dataStr = line.slice(6).trim();
                  if (dataStr === "[DONE]") {
                    onComplete();
                    return;
                  }

                  try {
                    const parsed = JSON.parse(dataStr);
                    onEvent(parsed.event, parsed);
                  } catch {
                    
                  }
                }
              }
              
              read();
            })
            .catch((err) => {
              if (err.name === "AbortError") {
                onComplete();
              } else {
                onError(err);
              }
            });
        }

        read();
      })
      .catch((err) => {
        onError(err);
      });

    return () => abortController.abort();
  }
};
