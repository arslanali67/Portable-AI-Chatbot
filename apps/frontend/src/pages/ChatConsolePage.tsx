import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { useParams } from "react-router-dom";

import { api, streamChat } from "../api/client";
import { errorMessage } from "../auth/AuthContext";
import type { Conversation, Message } from "../api/types";

export default function ChatConsolePage() {
  const { organizationId, chatbotId } = useParams<{
    organizationId: string;
    chatbotId: string;
  }>();
  const orgId = Number(organizationId);
  const botId = Number(chatbotId);

  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loadingConv, setLoadingConv] = useState(false);
  const [loadingMsgs, setLoadingMsgs] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [newTitle, setNewTitle] = useState("");

  const scrollRef = useRef<HTMLDivElement | null>(null);

// Monotonic, session-unique negative ids for optimistic/temporary messages.
// Persisted messages use positive DB ids; the negatives can never collide
// with them, and each send gets a distinct value (no Date.now() races).
let clientMessageSeq = 0;

function nextClientMessageId(): number {
  clientMessageSeq -= 1;
  return clientMessageSeq;
}

  const loadConversations = useCallback(() => {
    api
      .listConversations(orgId, botId)
      .then((res) => setConversations(res.items))
      .catch((err) => setError(errorMessage(err)));
  }, [orgId, botId]);

  useEffect(loadConversations, [loadConversations]);

  useEffect(() => {
    if (!selected) {
      setMessages([]);
      return;
    }
    setLoadingMsgs(true);
    api
      .listMessages(orgId, selected)
      .then((res) => setMessages(res.items))
      .catch((err) => setError(errorMessage(err)))
      .finally(() => setLoadingMsgs(false));
  }, [orgId, selected]);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  async function createConversation(e: FormEvent) {
    e.preventDefault();
    setLoadingConv(true);
    setError(null);
    try {
      const conv = await api.createConversation(orgId, botId, newTitle.trim() || "New chat");
      setNewTitle("");
      setConversations((prev) => [conv, ...prev]);
      setSelected(conv.id);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoadingConv(false);
    }
  }

  async function sendMessage(e: FormEvent) {
    e.preventDefault();
    const content = input.trim();
    if (!content || !selected || streaming) {
      return;
    }
    setInput("");
    setError(null);
    setStreaming(true);

    // Optimistically append the user + assistant placeholders. Both use unique
    // client-side (negative) ids that are stable for the whole session and can
    // never collide with persisted positive DB ids or with each other.
    const userTempId = nextClientMessageId();
    const assistantTempId = nextClientMessageId();
    const userMsg: Message = {
      id: userTempId,
      conversation_id: selected,
      role: "user",
      content,
      sequence_number: messages.length + 1,
      metadata: null,
      created_at: new Date().toISOString(),
    };
    const assistantMsg: Message = {
      id: assistantTempId,
      conversation_id: selected,
      role: "assistant",
      content: "",
      sequence_number: messages.length + 2,
      metadata: null,
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, userMsg, assistantMsg]);

    try {
      await streamChat(orgId, selected, content, (event) => {
        if (event.type === "user") {
          // Reconcile the optimistic user message with its persisted record so
          // the real DB id becomes its React key (never duplicated).
          const data = event.data as Partial<Message>;
          if (typeof data.id === "number" && data.id > 0) {
            const persistedId = data.id;
            const persistedSequence = data.sequence_number;
            const persistedContent = data.content;
            setMessages((prev) =>
              prev.map((m) =>
                m.id === userTempId
                  ? {
                      id: persistedId,
                      conversation_id: m.conversation_id,
                      role: "user",
                      content: typeof persistedContent === "string" ? persistedContent : m.content,
                      sequence_number:
                        typeof persistedSequence === "number"
                          ? persistedSequence
                          : m.sequence_number,
                      metadata: m.metadata,
                      created_at: m.created_at,
                    }
                  : m,
              ),
            );
          }
        } else if (event.type === "token") {
          const { delta } = event.data as { delta?: string };
          if (delta) {
            // Append to the single temporary assistant message by its unique id.
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantTempId ? { ...m, content: m.content + delta } : m,
              ),
            );
          }
        } else if (event.type === "end") {
          // Stream succeeded: replace the temporary assistant with its persisted
          // record — same bubble, accumulated content, real DB id as the key.
          const data = event.data as { message_id?: number; sequence_number?: number };
          if (typeof data.message_id === "number" && data.message_id > 0) {
            const persistedId = data.message_id;
            const persistedSequence = data.sequence_number;
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantTempId
                  ? {
                      ...m,
                      id: persistedId,
                      sequence_number:
                        typeof persistedSequence === "number"
                          ? persistedSequence
                          : m.sequence_number,
                    }
                  : m,
              ),
            );
          }
        } else if (event.type === "error") {
          const { detail } = event.data as { detail?: string };
          setError(detail ?? "Streaming error");
          // Backend persists no assistant message on failure — drop the temp one.
          setMessages((prev) => prev.filter((m) => m.id !== assistantTempId));
        }
      });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setStreaming(false);
      loadConversations();
    }
  }

  return (
    <div className="console-layout">
      <div className="console-side">
        <form onSubmit={createConversation}>
          <input
            value={newTitle}
            onChange={(e) => setNewTitle(e.target.value)}
            placeholder="New conversation title…"
          />
          <button type="submit" disabled={loadingConv} className="button small">
            New
          </button>
        </form>
        {conversations.length === 0 ? (
          <p className="muted small">No conversations yet.</p>
        ) : (
          <ul className="conv-list">
            {conversations.map((conv) => (
              <li key={conv.id}>
                <button
                  className={`conv-item ${selected === conv.id ? "active" : ""}`}
                  onClick={() => setSelected(conv.id)}
                  title={conv.status}
                >
                  {conv.title}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="console-main">
        {!selected ? (
          <div className="center-screen">
            <p className="muted">Select or create a conversation to start chatting.</p>
          </div>
        ) : (
          <>
            <div className="console-messages" ref={scrollRef}>
              {loadingMsgs && <p className="muted small">Loading messages…</p>}
              {!loadingMsgs && messages.length === 0 && (
                <p className="muted">No messages yet. Say hello.</p>
              )}
              {messages.map((m) => (
                <div key={m.id} className={`bubble bubble-${m.role}`}>
                  <div className="bubble-role">{m.role}</div>
                  <div className="bubble-content">{m.content}</div>
                </div>
              ))}
            </div>
            <form className="console-input" onSubmit={sendMessage}>
              <input
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="Type a message…"
                disabled={streaming}
                autoFocus
              />
              <button type="submit" disabled={streaming || !selected}>
                {streaming ? "…" : "Send"}
              </button>
            </form>
          </>
        )}
        {error && <div className="error-box">{error}</div>}
      </div>
    </div>
  );
}