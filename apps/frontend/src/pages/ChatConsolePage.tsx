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

    // Optimistically append the user message (mimic the backend sequence).
    const userMsg: Message = {
      id: -Date.now(),
      conversation_id: selected,
      role: "user",
      content,
      sequence_number: messages.length + 1,
      metadata: null,
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, userMsg]);

    // Assistant placeholder
    const assistantId = -Date.now() + 1;
    const assistantMsg: Message = {
      id: assistantId,
      conversation_id: selected,
      role: "assistant",
      content: "",
      sequence_number: messages.length + 2,
      metadata: null,
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, assistantMsg]);

    try {
      await streamChat(orgId, selected, content, (event) => {
        if (event.type === "token") {
          const { token } = event.data as { token?: string };
          setMessages((prev) => {
            const next = [...prev];
            const last = next[next.length - 1];
            if (last && last.role === "assistant" && last.id === assistantId) {
              next[next.length - 1] = { ...last, content: last.content + (token ?? "") };
            }
            return next;
          });
        } else if (event.type === "error") {
          const { detail } = event.data as { detail?: string };
          setError(detail ?? "Streaming error");
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