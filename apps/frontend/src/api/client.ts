import type {
  AICredentialStatus,
  ApiError,
  CheckoutResponse,
  Chatbot,
  ChatbotCreate,
  ChatbotUpdate,
  Conversation,
  ConversationList,
  DisabledUpdate,
  InvoiceList,
  KnowledgeCrawlResult,
  KnowledgeDocument,
  KnowledgeDocumentList,
  KnowledgeSearchResult,
  Membership,
  MembershipCreate,
  MembershipRole,
  Message,
  MessageList,
  ModelInfo,
  Organization,
  OrganizationCreate,
  OrganizationUpdate,
  PlatformOrganizationDetail,
  PlatformOrganizationList,
  PlatformOrganizationSummary,
  Provider,
  StreamEvent,
  StripeCredentialStatus,
  SubscriptionOverride,
  SubscriptionStatus,
  TokenResponse,
  User,
  WidgetConfig,
  WidgetConfigUpdate,
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

// Paths that must never trigger a refresh-retry themselves — refresh/login/
// register/logout failing with 401 means "not authenticated," not "needs a
// refresh," and retrying them would either loop or make no sense.
const NO_REFRESH_RETRY_SUFFIXES = [
  "/api/v1/auth/login",
  "/api/v1/auth/register",
  "/api/v1/auth/refresh",
  "/api/v1/auth/logout",
];

let refreshInFlight: Promise<boolean> | null = null;

async function attemptRefresh(): Promise<boolean> {
  if (!refreshInFlight) {
    refreshInFlight = (async () => {
      try {
        const response = await fetch(`${API_BASE_URL}/api/v1/auth/refresh`, {
          method: "POST",
          credentials: "include",
        });
        if (!response.ok) return false;
        const data = (await response.json()) as { access_token: string };
        setToken(data.access_token);
        return true;
      } catch {
        return false;
      } finally {
        refreshInFlight = null;
      }
    })();
  }
  return refreshInFlight;
}

async function rawFetch(path: string, init: RequestInit): Promise<Response> {
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
  // credentials:"include" is required for the httpOnly refresh cookie to be
  // sent/received, including when the frontend is deployed cross-origin
  // (VITE_API_BASE_URL) — CORS already allows this (allow_credentials=True
  // with an explicit origin allowlist, never "*").
  return fetch(API_BASE_URL + path, { ...init, headers, credentials: "include" });
}

async function request<T>(path: string, init: RequestInit = {}, isRetry = false): Promise<T> {
  const response = await rawFetch(path, init);

  if (
    response.status === 401 &&
    !isRetry &&
    !NO_REFRESH_RETRY_SUFFIXES.some((suffix) => path.endsWith(suffix))
  ) {
    const refreshed = await attemptRefresh();
    if (refreshed) {
      return request<T>(path, init, true);
    }
  }

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
  logout(): Promise<void> {
    return request<void>("/api/v1/auth/logout", { method: "POST" });
  },
  requestPasswordReset(email: string): Promise<void> {
    return request<void>("/api/v1/auth/password-reset/request", {
      method: "POST",
      ...jsonBody({ email }),
    });
  },
  confirmPasswordReset(token: string, newPassword: string): Promise<void> {
    return request<void>("/api/v1/auth/password-reset/confirm", {
      method: "POST",
      ...jsonBody({ token, new_password: newPassword }),
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
  getOrganization(organizationId: number): Promise<Organization> {
    return request<Organization>(`/api/v1/organizations/${organizationId}`);
  },
  updateOrganization(organizationId: number, data: OrganizationUpdate): Promise<Organization> {
    return request<Organization>(`/api/v1/organizations/${organizationId}`, {
      method: "PATCH",
      ...jsonBody(data),
    });
  },
  deleteOrganization(organizationId: number): Promise<void> {
    return request<void>(`/api/v1/organizations/${organizationId}`, { method: "DELETE" });
  },

  // Members
  listMembers(organizationId: number): Promise<Membership[]> {
    return request<Membership[]>(`/api/v1/organizations/${organizationId}/members`);
  },
  addMember(organizationId: number, data: MembershipCreate): Promise<Membership> {
    return request<Membership>(`/api/v1/organizations/${organizationId}/members`, {
      method: "POST",
      ...jsonBody(data),
    });
  },
  updateMemberRole(
    organizationId: number,
    membershipId: number,
    role: MembershipRole,
  ): Promise<Membership> {
    return request<Membership>(
      `/api/v1/organizations/${organizationId}/members/${membershipId}`,
      { method: "PATCH", ...jsonBody({ role }) },
    );
  },
  removeMember(organizationId: number, membershipId: number): Promise<void> {
    return request<void>(
      `/api/v1/organizations/${organizationId}/members/${membershipId}`,
      { method: "DELETE" },
    );
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
    theme?: WidgetConfigUpdate,
  ): Promise<WidgetConfig> {
    return request<WidgetConfig>(
      `/api/v1/organizations/${orgId}/chatbots/${chatbotId}/widget-config`,
      { method: "POST", ...jsonBody({ allowed_origins: allowedOrigins, ...theme }) },
    );
  },
  updateWidgetConfig(
    orgId: number,
    chatbotId: number,
    data: WidgetConfigUpdate,
  ): Promise<WidgetConfig> {
    return request<WidgetConfig>(
      `/api/v1/organizations/${orgId}/chatbots/${chatbotId}/widget-config`,
      { method: "PATCH", ...jsonBody(data) },
    );
  },
  uploadWidgetAvatar(orgId: number, chatbotId: number, file: File): Promise<WidgetConfig> {
    const body = new FormData();
    body.append("file", file);
    return request<WidgetConfig>(
      `/api/v1/organizations/${orgId}/chatbots/${chatbotId}/widget-config/avatar`,
      { method: "POST", body },
    );
  },
  revokeWidgetConfig(orgId: number, chatbotId: number): Promise<void> {
    return request<void>(
      `/api/v1/organizations/${orgId}/chatbots/${chatbotId}/widget-config`,
      { method: "DELETE" },
    );
  },

  // AI management
  listProviders(): Promise<Provider[]> {
    return request<Provider[]>("/api/v1/ai/providers");
  },
  listModels(providerId: string): Promise<ModelInfo[]> {
    return request<ModelInfo[]>(`/api/v1/ai/providers/${providerId}/models`);
  },
  updateProvider(providerId: string, data: DisabledUpdate): Promise<Provider> {
    return request<Provider>(`/api/v1/ai/providers/${providerId}`, {
      method: "PATCH",
      ...jsonBody(data),
    });
  },
  updateModel(providerId: string, modelId: string, data: DisabledUpdate): Promise<ModelInfo> {
    return request<ModelInfo>(`/api/v1/ai/providers/${providerId}/models/${modelId}`, {
      method: "PATCH",
      ...jsonBody(data),
    });
  },

  // BYOK AI provider credentials (organization-scoped, admin+)
  listAiCredentials(orgId: number): Promise<AICredentialStatus[]> {
    return request<AICredentialStatus[]>(`/api/v1/organizations/${orgId}/ai-credentials`);
  },
  setAiCredential(orgId: number, providerId: string, apiKey: string): Promise<AICredentialStatus> {
    return request<AICredentialStatus>(
      `/api/v1/organizations/${orgId}/ai-credentials/${providerId}`,
      { method: "PUT", ...jsonBody({ api_key: apiKey }) },
    );
  },
  removeAiCredential(orgId: number, providerId: string): Promise<void> {
    return request<void>(`/api/v1/organizations/${orgId}/ai-credentials/${providerId}`, {
      method: "DELETE",
    });
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
  answerPresetQuestion(
    orgId: number,
    conversationId: number,
    questionIndex: number,
  ): Promise<void> {
    return request<void>(
      `/api/v1/organizations/${orgId}/conversations/${conversationId}/faq`,
      { method: "POST", ...jsonBody({ question_index: questionIndex }) },
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
  updateConversation(orgId: number, conversationId: number, title: string): Promise<Conversation> {
    return request<Conversation>(
      `/api/v1/organizations/${orgId}/conversations/${conversationId}`,
      { method: "PATCH", ...jsonBody({ title }) },
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
  crawlUrl(
    orgId: number,
    chatbotId: number,
    url: string,
    title?: string,
  ): Promise<KnowledgeCrawlResult> {
    return request<KnowledgeCrawlResult>(
      `/api/v1/organizations/${orgId}/chatbots/${chatbotId}/knowledge/documents/crawl`,
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

  // Platform-owner dashboard (platform-admin only, cross-organization)
  listPlatformOrganizations(limit = 50, offset = 0): Promise<PlatformOrganizationList> {
    return request<PlatformOrganizationList>(
      `/api/v1/platform/organizations?limit=${limit}&offset=${offset}`,
    );
  },
  getPlatformOrganization(orgId: number): Promise<PlatformOrganizationDetail> {
    return request<PlatformOrganizationDetail>(`/api/v1/platform/organizations/${orgId}`);
  },
  disablePlatformOrganization(
    orgId: number,
    message: string | null,
  ): Promise<PlatformOrganizationSummary> {
    return request<PlatformOrganizationSummary>(
      `/api/v1/platform/organizations/${orgId}/disable`,
      { method: "POST", ...jsonBody({ message }) },
    );
  },
  enablePlatformOrganization(orgId: number): Promise<PlatformOrganizationSummary> {
    return request<PlatformOrganizationSummary>(
      `/api/v1/platform/organizations/${orgId}/enable`,
      { method: "POST" },
    );
  },
  overridePlatformSubscription(
    orgId: number,
    data: SubscriptionOverride,
  ): Promise<SubscriptionStatus> {
    return request<SubscriptionStatus>(
      `/api/v1/platform/organizations/${orgId}/subscription`,
      { method: "PATCH", ...jsonBody(data) },
    );
  },
  getStripeSettings(): Promise<StripeCredentialStatus | null> {
    return request<StripeCredentialStatus | null>("/api/v1/platform/settings/stripe");
  },
  setStripeSettings(secretKey: string): Promise<StripeCredentialStatus> {
    return request<StripeCredentialStatus>("/api/v1/platform/settings/stripe", {
      method: "PUT",
      ...jsonBody({ secret_key: secretKey }),
    });
  },

  // Billing (organization-scoped, OWNER only)
  createCheckoutSession(orgId: number, tier: string): Promise<CheckoutResponse> {
    return request<CheckoutResponse>(`/api/v1/organizations/${orgId}/billing/checkout`, {
      method: "POST",
      ...jsonBody({ tier }),
    });
  },
  getSubscription(orgId: number): Promise<SubscriptionStatus> {
    return request<SubscriptionStatus>(`/api/v1/organizations/${orgId}/billing/subscription`);
  },
  listInvoices(orgId: number): Promise<InvoiceList> {
    return request<InvoiceList>(`/api/v1/organizations/${orgId}/billing/invoices`);
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