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

export interface Citation {
  index?: number;
  source_doc: string;
  page: number | null;
  score: number;
  snippet?: string;
  doc_id?: string;
  chunk_id?: string;
  url?: string;
}

export interface IndexingProgress {
  doc_id: string;
  stage: "queued" | "receiving" | "parsing" | "chunking" | "embedding" | "saving" | "done" | "failed";
  label: string;
  percent: number;
  message: string | null;
  status?: string;
  updated_at?: number;
}

export interface ChunkContext {
  chunk: { id: string; content: string; page_number: number | null; chunk_index: number | null };
  before: string | null;
  after: string | null;
  document: {
    id: string;
    kb_id: string;
    filename: string;
    file_type: string;
    source_url: string | null;
    has_file: boolean;
  };
}

export type AnswerMode = "quick" | "detailed" | "compare";

export interface GoldenQuestion {
  id: string;
  kb_id: string;
  question: string;
  expected_answer: string;
  created_at: string | null;
}

export interface GoldenResult {
  question_id: string;
  question: string;
  expected_answer: string;
  answer: string;
  correctness: number;
  faithfulness: number;
  context_recall: number;
  score: number;
  passed: boolean;
  reason?: string | null;
  sources: Array<{ source_doc: string | null; page: number | null; chunk_id?: string | null }>;
  latency: number;
}

export interface GoldenRun {
  id: string;
  created_at: string;
  method: string;
  overall_score: number | null;
  passed: number;
  total: number;
  pass: boolean;
  threshold: number;
  faithfulness?: number | null;
  correctness?: number | null;
  context_recall?: number | null;
  results: GoldenResult[];
  usage?: { prompt_tokens: number; completion_tokens: number; cost_usd: number; model: string | null };
}

export interface CostReport {
  days: number;
  totals: { queries: number; cached: number; prompt_tokens: number; completion_tokens: number; cost_usd: number; avg_cost_per_query_usd: number };
  per_day: Array<{ day: string; queries: number; prompt_tokens: number; completion_tokens: number; cost_usd: number; cached: number }>;
  per_kb: Array<{ kb_id: string | null; kb_name: string; queries: number; prompt_tokens: number; completion_tokens: number; cost_usd: number; avg_latency: number }>;
  per_model: Array<{ model: string; queries: number; prompt_tokens: number; completion_tokens: number; cost_usd: number }>;
  note: string;
}

export interface AuditEntry {
  id: string;
  user_email: string | null;
  action: string;
  target_type: string | null;
  target_id: string | null;
  detail: Record<string, unknown>;
  created_at: string;
}

export interface Message {
  id: string;
  sender: "user" | "assistant";
  content: string;
  citations?: Citation[];
  latency?: number;
  retrieval_score?: number;
  // "llm" when a judge scored it, "heuristic" when it is a lexical proxy.
  confidence_method?: string;
  // True when the answer came from the semantic answer cache.
  cached?: boolean;
  mode?: AnswerMode;
  usage?: { prompt_tokens: number; completion_tokens: number; model: string | null; cost_usd: number };
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
  // Nullable: a metric the backend could not compute is null, not zero.
  faithfulness: number | null;
  context_precision: number | null;
  context_recall: number | null;
  answer_relevancy: number | null;
  // "ragas" = LLM-judged RAGAS metrics. "heuristic" = local lexical-overlap
  // proxies, which are NOT RAGAS metrics and must not be presented as such.
  method?: string | null;
  created_at: string;
}

// Token Storage
const TOKEN_KEY = "rag_access_token";

// Same-tab listeners (useCurrentUser) do not receive "storage" events.
function notifyAuthChange() {
  if (typeof window !== "undefined") window.dispatchEvent(new Event("agis:user"));
}
const USER_KEY = "rag_user_data";

export const authStorage = {
  getToken: () => (typeof window !== "undefined" ? localStorage.getItem(TOKEN_KEY) : null),
  setToken: (token: string) => {
    if (typeof window !== "undefined") {
      localStorage.setItem(TOKEN_KEY, token);
    }
    if (typeof document !== "undefined") {
      // NOTE: this cookie cannot be HttpOnly — it is set from JS so the Next
      // middleware can read it. That means XSS can read the token. Moving token
      // issuance to a server route that sets an HttpOnly cookie is the real fix.
      // Until then, at least refuse to send it in cleartext over HTTP.
      const secure = window.location.protocol === "https:" ? "; secure" : "";
      document.cookie = `${TOKEN_KEY}=${token}; path=/; max-age=604800; samesite=lax${secure}`;
    }
    notifyAuthChange();
  },
  clear: () => {
    if (typeof window !== "undefined") {
      localStorage.removeItem(TOKEN_KEY);
      localStorage.removeItem(USER_KEY);
    }
    if (typeof document !== "undefined") {
      document.cookie = `${TOKEN_KEY}=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT; max-age=0; samesite=lax`;
    }
    clearApiCache();
    notifyAuthChange();
  },
  getUser: (): User | null => {
    if (typeof window === "undefined") return null;
    const data = localStorage.getItem(USER_KEY);
    return data ? JSON.parse(data) : null;
  },
  setUser: (user: User) => {
    if (typeof window !== "undefined") {
      localStorage.setItem(USER_KEY, JSON.stringify(user));
    }
    notifyAuthChange();
  },
};

// Client-side caching layer to speed up page transitions and avoid blocking loaders
const apiCache: Record<string, { data: unknown; timestamp: number }> = {};
const CACHE_TTL = 30000; // 30 seconds cache validity
const STALE_TTL = 10 * 60 * 1000; // stale data may still be shown instantly for 10 min

/**
 * Last known response for a GET path, even if it is past its fresh window.
 * Pages render this immediately and refresh in the background
 * (stale-while-revalidate), so revisiting a page never shows a blank loader.
 */
export function peekApiCache<T>(path: string): T | undefined {
  if (typeof window === "undefined") return undefined;
  const hit = apiCache[path];
  if (hit && Date.now() - hit.timestamp < STALE_TTL) return hit.data as T;
  return undefined;
}

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
async function request<T>(
  path: string,
  options: RequestInit = {},
  opts: { noCache?: boolean } = {}
): Promise<T> {
  const method = options.method || "GET";

  // Return cached result if valid (only for GET requests, and only when the
  // caller has not explicitly asked for fresh data — pollers must opt out or
  // they just re-read the same 30s-old snapshot every tick).
  if (method === "GET" && !opts.noCache) {
    const cached = apiCache[path];
    if (cached && Date.now() - cached.timestamp < CACHE_TTL) {
      return cached.data as T;
    }
  } else if (method !== "GET") {
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
    // Only 401 means "your session is invalid". A 403 means "you are correctly
    // authenticated but not allowed to do this" — signing the user out for that
    // kicks any non-admin off the app the moment they touch an admin endpoint.
    if (response.status === 401) {
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
    } catch {}
    // FastAPI's own "Not Found" means the route does not exist at all - the
    // backend is older than this frontend.
    if (response.status === 404 && errMsg === "Not Found") {
      errMsg = "This feature is not available on the server yet. Deploy the latest backend and try again.";
    }
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
  listDocs: (kbId: string, opts?: { noCache?: boolean }) =>
    request<DocumentInfo[]>(`/documents/${kbId}`, {}, opts),
  importUrl: (kbId: string, url: string, chunkSize: number = 1000, chunkOverlap: number = 200) =>
    request<DocumentInfo>("/documents/import-url", {
      method: "POST",
      body: JSON.stringify({ kb_id: kbId, url, chunk_size: chunkSize, chunk_overlap: chunkOverlap }),
    }),
  getIndexingProgress: (kbId: string) =>
    request<Record<string, IndexingProgress>>(`/documents/kb/${kbId}/progress`, {}, { noCache: true }),
  getChunkContext: (chunkId: string) => request<ChunkContext>(`/documents/chunks/${chunkId}/context`),
  /** Fetch the original file (authenticated) as a blob URL the browser can open. */
  getDocumentFileUrl: async (docId: string): Promise<string> => {
    const token = authStorage.getToken();
    const res = await fetch(`${API_BASE_URL}/documents/${docId}/file`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!res.ok) {
      let msg = "Could not open the original file.";
      try {
        msg = (await res.json()).detail || msg;
      } catch {}
      throw new Error(msg);
    }
    return URL.createObjectURL(await res.blob());
  },
  deleteDoc: (docId: string) => request<void>(`/documents/${docId}`, { method: "DELETE" }),
  reindexDoc: (docId: string) => request<DocumentInfo>(`/documents/${docId}/reindex`, { method: "POST" }),

  // Admin Document Management
  listAllDocumentsAdmin: (opts?: { noCache?: boolean }) =>
    request<AdminDocumentInfo[]>("/documents/admin/all", {}, opts),
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

  // Golden question sets
  listGoldenQuestions: (kbId: string) => request<GoldenQuestion[]>(`/evaluation/golden/${kbId}`, {}, { noCache: true }),
  addGoldenQuestion: (kbId: string, question: string, expected_answer: string) =>
    request<GoldenQuestion>("/evaluation/golden", { method: "POST", body: JSON.stringify({ kb_id: kbId, question, expected_answer }) }),
  deleteGoldenQuestion: (id: string) => request<void>(`/evaluation/golden/${id}`, { method: "DELETE" }),
  suggestGoldenQuestions: (kbId: string, n = 5) =>
    request<{ items: Array<{ question: string; expected_answer: string }> }>("/evaluation/golden/suggest", { method: "POST", body: JSON.stringify({ kb_id: kbId, n }) }),
  runGolden: (kbId: string, threshold?: number) =>
    request<GoldenRun & { kb_id: string }>("/evaluation/golden/run", { method: "POST", body: JSON.stringify({ kb_id: kbId, threshold }) }),
  goldenRunHistory: (kbId: string) => request<GoldenRun[]>(`/evaluation/golden/${kbId}/runs`, {}, { noCache: true }),

  // Costs and audit (admin)
  getCosts: (days = 30) => request<CostReport>(`/analytics/costs?days=${days}`),
  getAuditLog: (params: { limit?: number; offset?: number; action?: string; user?: string } = {}) => {
    const q = new URLSearchParams();
    if (params.limit) q.set("limit", String(params.limit));
    if (params.offset) q.set("offset", String(params.offset));
    if (params.action) q.set("action", params.action);
    if (params.user) q.set("user", params.user);
    return request<{ total: number; actions: string[]; items: AuditEntry[] }>(`/analytics/audit?${q.toString()}`, {}, { noCache: true });
  },

  // Export a conversation as Markdown (downloads the file)
  exportConversation: async (convId: string, title: string) => {
    const token = authStorage.getToken();
    const res = await fetch(`${API_BASE_URL}/chat/conversations/${convId}/export`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
    if (!res.ok) throw new Error("Export failed.");
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${(title || "conversation").replace(/[^\w\- ]+/g, "").trim() || "conversation"}.md`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
  },
  
  // Streaming event listener utility
  streamMessage: (
    queryData: { conversation_id: string; query: string; web_search_enabled: boolean; document_ids?: string[]; mode?: AnswerMode },
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
