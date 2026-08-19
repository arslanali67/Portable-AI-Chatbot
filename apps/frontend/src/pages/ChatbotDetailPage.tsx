import { useEffect, useState } from "react";
import { Link, NavLink, Route, Routes, useParams } from "react-router-dom";

import { api } from "../api/client";
import { errorMessage } from "../auth/AuthContext";
import type { Chatbot } from "../api/types";
import ChatConsolePage from "./ChatConsolePage";
import KnowledgePage from "./KnowledgePage";
import WidgetConfigPage from "./WidgetConfigPage";

export default function ChatbotDetailPage() {
  const { organizationId, chatbotId } = useParams<{
    organizationId: string;
    chatbotId: string;
  }>();
  const orgId = Number(organizationId);
  const botId = Number(chatbotId);

  const [chatbot, setChatbot] = useState<Chatbot | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .getChatbot(orgId, botId)
      .then(setChatbot)
      .catch((err) => setError(errorMessage(err)));
  }, [orgId, botId]);

  if (error) {
    return (
      <section>
        <div className="error-box">{error}</div>
        <Link to={`/organizations/${orgId}`}>Back to chatbots</Link>
      </section>
    );
  }

  if (!chatbot) {
    return <div className="center-screen">Loading…</div>;
  }

  const base = `/organizations/${orgId}/chatbots/${botId}`;

  return (
    <section>
      <div className="page-head">
        <div>
          <h1>{chatbot.name}</h1>
          <p className="muted">
            /{chatbot.slug} · <span className={`badge badge-${chatbot.status}`}>{chatbot.status}</span>{" "}
            · {chatbot.provider_id}/{chatbot.model_id}
          </p>
        </div>
        <Link to={`/organizations/${orgId}`} className="button secondary">
          Back
        </Link>
      </div>

      <nav className="tabs">
        <NavLink to={base} end>
          Chat
        </NavLink>
        <NavLink to={`${base}/knowledge`}>Knowledge</NavLink>
        <NavLink to={`${base}/widget`}>Widget</NavLink>
      </nav>

      <Routes>
        <Route index element={<ChatConsolePage />} />
        <Route path="knowledge" element={<KnowledgePage />} />
        <Route path="widget" element={<WidgetConfigPage />} />
      </Routes>
    </section>
  );
}