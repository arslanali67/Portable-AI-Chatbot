// Mirrors apps/api schemas. Provider/model metadata is read from the API at
// runtime — never hardcoded in the frontend.

export interface User {
  id: number;
  email: string;
  full_name: string;
  is_active: boolean;
  is_platform_admin: boolean;
  created_at: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
}

export interface Organization {
  id: number;
  name: string;
  slug: string;
  created_at: string;
}

export interface OrganizationCreate {
  name: string;
  slug: string;
}

export interface OrganizationUpdate {
  name: string;
}

export type MembershipRole = "owner" | "admin" | "member";

export interface Membership {
  id: number;
  organization_id: number;
  user_id: number;
  role: MembershipRole;
  created_at: string;
  user_email: string;
  user_full_name: string;
}

export interface MembershipCreate {
  email: string;
  role: MembershipRole;
}

export type ChatbotStatus = "draft" | "active" | "archived";
export type ChatbotVisibility = "public" | "private";

export interface Chatbot {
  id: number;
  organization_id: number;
  name: string;
  slug: string;
  description: string;
  system_prompt: string;
  welcome_message: string;
  status: ChatbotStatus;
  visibility: ChatbotVisibility;
  language: string;
  provider_id: string;
  model_id: string;
  rag_enabled: boolean;
  rag_top_k: number | null;
  response_schema: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}

export interface ChatbotCreate {
  name: string;
  slug: string;
  description: string;
  system_prompt: string;
  welcome_message: string;
  language: string;
  visibility: ChatbotVisibility;
  provider_id: string;
  model_id: string;
  rag_enabled?: boolean;
  rag_top_k?: number | null;
  response_schema?: Record<string, unknown> | null;
}

export interface ChatbotUpdate {
  name?: string;
  slug?: string;
  description?: string;
  system_prompt?: string;
  welcome_message?: string;
  language?: string;
  visibility?: ChatbotVisibility;
  provider_id?: string;
  model_id?: string;
  rag_enabled?: boolean;
  rag_top_k?: number | null;
  response_schema?: Record<string, unknown> | null;
}

export type AICapability =
  | "text_generation"
  | "streaming"
  | "tool_calling"
  | "structured_output"
  | "vision"
  | "audio_input"
  | "audio_output"
  | "embeddings"
  | "image_generation"
  | "json_mode"
  | "reasoning";

export interface Provider {
  provider_id: string;
  display_name: string;
  description: string;
  enabled: boolean;
  authentication_type: string;
  compatibility_type: string;
  capabilities: AICapability[];
}

export interface ModelInfo {
  provider_id: string;
  model_id: string;
  display_name: string;
  context_window: number;
  max_output_tokens: number;
  enabled: boolean;
  capabilities: AICapability[];
}

export interface DisabledUpdate {
  disabled: boolean;
}

export interface AICredentialStatus {
  provider_id: string;
  masked_key: string;
  updated_at: string;
  updated_by_email: string | null;
}

export type SourceType = "text" | "file" | "url";

export interface KnowledgeDocument {
  id: number;
  name: string;
  source_type: SourceType;
  status: string;
  chunk_count: number;
  original_filename: string | null;
  source_uri: string | null;
  created_at: string;
  updated_at: string;
}

export interface KnowledgeDocumentList {
  items: KnowledgeDocument[];
  total: number;
}

export interface RetrievedChunk {
  document_id: number;
  chunk_id: number;
  content: string;
  score: number;
  metadata: Record<string, unknown> | null;
}

export interface KnowledgeSearchResult {
  results: RetrievedChunk[];
}

export type ConversationStatus = "active" | "archived";

export interface Conversation {
  id: number;
  organization_id: number;
  chatbot_id: number;
  user_id: number;
  title: string;
  status: ConversationStatus;
  created_at: string;
  updated_at: string;
}

export interface ConversationList {
  items: Conversation[];
  total: number;
  limit: number;
  offset: number;
}

export type MessageRole = "user" | "assistant" | "system";

export interface Message {
  id: number;
  conversation_id: number;
  role: MessageRole;
  content: string;
  sequence_number: number;
  metadata: Record<string, unknown> | null;
  created_at: string;
}

export interface MessageList {
  items: Message[];
  total: number;
  limit: number;
  offset: number;
}

export type WidgetPosition = "bottom_right" | "bottom_left";

export interface WidgetConfig {
  public_key: string;
  enabled: boolean;
  revoked_at: string | null;
  allowed_origins: string[];
  theme_color: string | null;
  widget_position: WidgetPosition | null;
  avatar_url: string | null;
}

export interface WidgetConfigUpdate {
  allowed_origins?: string[];
  theme_color?: string | null;
  widget_position?: WidgetPosition | null;
}

export interface ApiError {
  status: number;
  detail: string | Record<string, unknown>;
  message: string;
}

export interface StreamEvent {
  type: "start" | "user" | "token" | "end" | "error";
  data: Record<string, unknown>;
}