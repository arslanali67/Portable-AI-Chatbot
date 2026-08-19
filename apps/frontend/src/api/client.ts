import type {
  ApiError,
  Chatbot,
  ChatbotCreate,
  ChatbotUpdate,
  Conversation,
  ConversationList,
  KnowledgeDocument,
  KnowledgeDocumentList,
  KnowledgeSearchResult,
  Message,
  MessageList,
  ModelInfo,
  Organization,
  OrganizationCreate,
  Provider,
  StreamEvent,
  TokenResponse,
  User,
  WidgetConfig,
} from "./types";

const TOKEN_KEY = "portableai_access_token";

// API base URL for deployed (cross-origin) frontends. Empty by default, which
// keeps the existing relative-path behavior (Vite dev proxy / same-origin
// nginx). Set VITE_API_BASE_URL at build time for a Render Static Site that
// calls a separate backend Web Service, e.g. https://portableai-api.onrender.com
export const API_BASE_URL: string =
  (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/+$/, "") ??
  "";

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string): void {
  try {
    localStorage.setItem(TOKEN_KEY, token);
  } catch {
    // localStorage unavailable (private mode); app works per-session only.
  }
}

export function clearToken(): void {
  try {
    localStorage.removeItem(TOKEN_KEY);
  } catch {
    // ignore
  }
}

function normalizeError(status: number, body: unknown): ApiError {
  let detail: string | Record<string, unknown> = "Request failed";
  if (body && typeof body === "object" && "detail" in body) {
    const d = (body as { detail: unknown }).detail;
    if (typeof d === "string") {
      detail = d;
    } else if (Array.isArray(d)) {
      detail = (d as { msg?: string }[]).map((i) => i.msg ?? "").join("; ") || detail;
    } else if (d && typeof d === "object") {
      detail = d as Record<string, unknown>;
    }
  }
  return { status, detail, message: typeof detail === "string" ? detail : "Request failed" };
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    ...(init.headers as Record<string, string> | undefined),
  };
  if (init.body && !(init.body instanceof FormData) && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const response = await fetch(API_BASE_URL + path, { ...init, headers });

  if (response.status === 401) {
    clearToken();
  }

  if (!response.ok) {
    let body: unknown = null;
    try {
      body = await response.json();
    } catch {
      body = null;
    }
    throw normalizeError(response.status, body);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  const text = await response.text();
  if (!text) {
    return undefined as T;
  }
  return JSON.parse(text) as T;
}

function jsonBody(data: unknown): RequestInit {
  return { body: JSON.stringify(data) };
}

export const api = {
  // Auth
  register(data: { email: string; password: string; full_name: string }): Promise<User> {
    return request<User>("/api/v1/auth/register", { method: "POST", ...jsonBody(data) });
  },
  login(username: string, password: string): Promise<TokenResponse> {
    const body = new URLSearchParams();
    body.append("username", username);
    body.append("password", password);
    return request<TokenResponse>("/api/v1/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body,
    });
  },
  me(): Promise<User> {
    return request<User>("/api/v1/auth/me");
  },

  // Organizations
  listOrganizations(): Promise<Organization[]> {
    return request<Organization[]>("/api/v1/organizations");
  },
  createOrganization(data: OrganizationCreate): Promise<Organization> {
    return request<Organization>("/api/v1/organizations", { method: "POST", ...jsonBody(data) });
  },

  // Chatbots
  listChatbots(orgId: number): Promise<Chatbot[]> {
    return request<Chatbot[]>(`/api/v1/organizations/${orgId}/chatbots`);
  },
  getChatbot(orgId: number, chatbotId: number): Promise<Chatbot> {
    return request<Chatbot>(`/api/v1/organizations/${orgId}/chatbots/${chatbotId}`);
  },
  createChatbot(orgId: number, data: ChatbotCreate): Promise<Chatbot> {
    return request<Chatbot>(`/api/v1/organizations/${orgId}/chatbots`, {
      method: "POST",
      ...jsonBody(data),
    });
  },
  updateChatbot(orgId: number, chatbotId: number, data: ChatbotUpdate): Promise<Chatbot> {
    return request<Chatbot>(`/api/v1/organizations/${orgId}/chatbots/${chatbotId}`, {
      method: "PATCH",
      ...jsonBody(data),
    });
  },
  activateChatbot(orgId: number, chatbotId: number): Promise<Chatbot> {
    return request<Chatbot>(`/api/v1/organizations/${orgId}/chatbots/${chatbotId}/activate`, {
      method: "POST",
    });
  },
  archiveChatbot(orgId: number, chatbotId: number): Promise<Chatbot> {
    return request<Chatbot>(`/api/v1/organizations/${orgId}/chatbots/${chatbotId}/archive`, {
      method: "POST",
    });
  },
  deleteChatbot(orgId: number, chatbotId: number): Promise<void> {
    return request<void>(`/api/v1/organizations/${orgId}/chatbots/${chatbotId}`, {
      method: "DELETE",
    });
  },

  // Widget config
  getWidgetConfig(orgId: number, chatbotId: number): Promise<WidgetConfig> {
    return request<WidgetConfig>(
      `/api/v1/organizations/${orgId}/chatbots/${chatbotId}/widget-config`,
    );
  },
  createWidgetConfig(
    orgId: number,
    chatbotId: number,
    allowedOrigins: string[],
  ): Promise<{ public_key: string; enabled: boolean }> {
    return request<{ public_key: string; enabled: boolean }>(
      `/api/v1/organizations/${orgId}/chatbots/${chatbotId}/widget-config`,
      { method: "POST", ...jsonBody({ allowed_origins: allowedOrigins }) },
    );
  },
  revokeWidgetConfig(orgId: number, chatbotId: number): Promise<void> {
    return request<void>(
      `/api/v1/organizations/${orgId}/chatbots/${chatbotId}/widget-config`,
      { method: "DELETE" },
    );
  },

  // AI management (read-only)
  listProviders(): Promise<Provider[]> {
    return request<Provider[]>("/api/v1/ai/providers");
  },
  listModels(providerId: string): Promise<ModelInfo[]> {
    return request<ModelInfo[]>(`/api/v1/ai/providers/${providerId}/models`);
  },

  // Conversations
  createConversation(
    orgId: number,
    chatbotId: number,
    title: string,
  ): Promise<Conversation> {
    return request<Conversation>(
      `/api/v1/organizations/${orgId}/chatbots/${chatbotId}/conversations`,
      { method: "POST", ...jsonBody({ title }) },
    );
  },
  listConversations(orgId: number, chatbotId: number): Promise<ConversationList> {
    return request<ConversationList>(
      `/api/v1/organizations/${orgId}/chatbots/${chatbotId}/conversations`,
    );
  },
  getConversation(orgId: number, conversationId: number): Promise<Conversation> {
    return request<Conversation>(
      `/api/v1/organizations/${orgId}/conversations/${conversationId}`,
    );
  },
  listMessages(orgId: number, conversationId: number): Promise<MessageList> {
    return request<MessageList>(
      `/api/v1/organizations/${orgId}/conversations/${conversationId}/messages`,
    );
  },
  createMessage(orgId: number, conversationId: number, content: string): Promise<Message> {
    return request<Message>(
      `/api/v1/organizations/${orgId}/conversations/${conversationId}/messages`,
      { method: "POST", ...jsonBody({ content }) },
    );
  },
  archiveConversation(orgId: number, conversationId: number): Promise<Conversation> {
    return request<Conversation>(
      `/api/v1/organizations/${orgId}/conversations/${conversationId}/archive`,
      { method: "POST" },
    );
  },

  // Knowledge
  listDocuments(orgId: number, chatbotId: number): Promise<KnowledgeDocumentList> {
    return request<KnowledgeDocumentList>(
      `/api/v1/organizations/${orgId}/chatbots/${chatbotId}/knowledge/documents`,
    );
  },
  ingestText(
    orgId: number,
    chatbotId: number,
    data: { name: string; content: string },
  ): Promise<KnowledgeDocument> {
    return request<KnowledgeDocument>(
      `/api/v1/organizations/${orgId}/chatbots/${chatbotId}/knowledge/documents`,
      { method: "POST", ...jsonBody({ ...data, source_type: "text" }) },
    );
  },
  ingestFile(
    orgId: number,
    chatbotId: number,
    file: File,
    title?: string,
  ): Promise<KnowledgeDocument> {
    const body = new FormData();
    body.append("file", file);
    if (title) {
      body.append("title", title);
    }
    return request<KnowledgeDocument>(
      `/api/v1/organizations/${orgId}/chatbots/${chatbotId}/knowledge/documents/file`,
      { method: "POST", body },
    );
  },
  ingestUrl(
    orgId: number,
    chatbotId: number,
    url: string,
    title?: string,
  ): Promise<KnowledgeDocument> {
    return request<KnowledgeDocument>(
      `/api/v1/organizations/${orgId}/chatbots/${chatbotId}/knowledge/documents/url`,
      { method: "POST", ...jsonBody({ url, title: title ?? null }) },
    );
  },
  deleteDocument(orgId: number, chatbotId: number, documentId: number): Promise<void> {
    return request<void>(
      `/api/v1/organizations/${orgId}/chatbots/${chatbotId}/knowledge/documents/${documentId}`,
      { method: "DELETE" },
    );
  },
  searchKnowledge(
    orgId: number,
    chatbotId: number,
    query: string,
    topK = 5,
  ): Promise<KnowledgeSearchResult> {
    return request<KnowledgeSearchResult>(
      `/api/v1/organizations/${orgId}/chatbots/${chatbotId}/knowledge/search`,
      { method: "POST", ...jsonBody({ query, top_k: topK }) },
    );
  },
};

export async function streamChat(
  orgId: number,
  conversationId: number,
  content: string,
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const token = getToken();
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const response = await fetch(
    API_BASE_URL + `/api/v1/organizations/${orgId}/conversations/${conversationId}/chat/stream`,
    {
      method: "POST",
      headers,
      body: JSON.stringify({ content }),
      signal,
    },
  );

  if (!response.ok) {
    let body: unknown = null;
    try {
      body = await response.json();
    } catch {
      body = null;
    }
    throw normalizeError(response.status, body);
  }

  if (!response.body) {
    throw new Error("Streaming not supported");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }
    buffer += decoder.decode(value, { stream: true });
    const events = buffer.split("\n\n");
    buffer = events.pop() ?? "";

    for (const block of events) {
      const eventLine = block.split("\n").find((l) => l.startsWith("event:"));
      const dataLine = block.split("\n").find((l) => l.startsWith("data:"));
      if (!eventLine || !dataLine) {
        continue;
      }
      const type = eventLine.slice("event:".length).trim() as StreamEvent["type"];
      let data: Record<string, unknown> = {};
      try {
        data = JSON.parse(dataLine.slice("data:".length).trim());
      } catch {
        data = {};
      }
      onEvent({ type, data });
    }
  }
}